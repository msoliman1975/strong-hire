"""The metrics sampler cron (admin spec OB-5, OB-6). Runs every minute in the worker.

Writes one ops_samples row per metric (and label set) from strong_core.ops.metrics:
dependency probes (up and latency), heartbeats per service, queue depth, sessions in progress,
host disk, memory and load, database size, Redis memory and the age of the last Stripe webhook.

Every probe has a short time limit, and one that fails or raises never stops the others: a
down dependency is a `probe.up 0` sample, a reading that cannot be taken (no /proc on a dev
machine, no Stripe webhook yet) is left out.

Probe targets come from environment variables (ProbeSettings). An empty URL skips that probe.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import get_settings
from strong_core.db import get_sessionmaker
from strong_core.db.models import InterviewSession, OpsSample, StripeEvent
from strong_core.ops import metrics as m
from strong_core.ops.heartbeat import read_heartbeats
from strong_core.schemas.enums import SessionStatus

log = logging.getLogger(__name__)

CTX_KEY = "ops_sampler"
PROBE_TIMEOUT_S = 3.0
SMTP_EVERY_MIN = 10
ARQ_QUEUE = "arq:queue"


class ProbeSettings(BaseSettings):
    """Where the dependencies are, as the worker container reaches them (infra/compose.yaml)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    probe_litellm_url: str | None = Field(
        default=None,
        description="Defaults to MODEL_GATEWAY_URL without /v1, plus /health/liveliness. "
        "(LiteLLM's /health calls every model, so it is not used every minute.)",
    )
    probe_livekit_url: str = "http://livekit:7880"
    probe_stt_url: str = "http://stt:8000/health"
    probe_tts_url: str = "http://tts:8880/health"
    probe_timeout_s: float = PROBE_TIMEOUT_S
    # name=path pairs for host.disk_pct. The server mounts the Postgres volume read-only at
    # /mnt/pgdata in the worker (infra/compose.server.yaml); a missing path is skipped.
    host_disk_paths: str = "root=/,pgdata=/mnt/pgdata"
    proc_dir: Path = Path("/proc")

    def litellm_url(self) -> str | None:
        if self.probe_litellm_url is not None:
            return self.probe_litellm_url or None
        base = get_settings().model_gateway_url
        if not base:
            return None
        return base.rstrip("/").removesuffix("/v1") + "/health/liveliness"

    def disk_paths(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in self.host_disk_paths.split(","):
            name, _, path = pair.partition("=")
            if name.strip() and path.strip():
                out[name.strip()] = path.strip()
        return out


@dataclass
class Sample:
    metric: str
    value: float
    labels: dict[str, str] | None = None


@dataclass
class SamplerContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Any
    settings: ProbeSettings = field(default_factory=ProbeSettings)
    http: Callable[[], httpx.AsyncClient] | None = None  # tests pass a mock transport
    smtp_connect: Callable[[str, int, float], Awaitable[None]] | None = None


# --------------------------------------------------------------------------------- probes


async def _timed(check: Callable[[], Awaitable[Any]], timeout_s: float) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(check(), timeout=timeout_s)
        ok = True
    except Exception as exc:
        log.info("probe failed: %s", type(exc).__name__)
        ok = False
    return ok, round((time.perf_counter() - start) * 1000, 1)


def _probe_samples(dep: str, ok: bool, latency_ms: float) -> list[Sample]:
    labels = {"dep": dep}
    return [
        Sample(m.PROBE_UP, 1.0 if ok else 0.0, labels),
        Sample(m.PROBE_LATENCY_MS, latency_ms, labels),
    ]


async def _smtp_connect(host: str, port: int, timeout_s: float) -> None:
    """Connect and read the greeting only: no login, no mail."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_s)
    try:
        greeting = await asyncio.wait_for(reader.readline(), timeout_s)
        if not greeting.startswith(b"2"):
            raise ConnectionError("unexpected SMTP greeting")
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def probe_dependencies(sc: SamplerContext, now: datetime) -> list[Sample]:
    timeout = sc.settings.probe_timeout_s
    make_http = sc.http or (lambda: httpx.AsyncClient(timeout=timeout))

    async def postgres() -> None:
        async with sc.sessionmaker() as db:
            await db.execute(text("SELECT 1"))

    async def redis() -> None:
        await sc.redis.ping()

    def http_get(url: str) -> Callable[[], Awaitable[None]]:
        async def get() -> None:
            async with make_http() as client:
                resp = await client.get(url)
            if resp.status_code >= 500:
                raise ConnectionError(f"HTTP {resp.status_code}")

        return get

    checks: dict[str, Callable[[], Awaitable[Any]]] = {"postgres": postgres, "redis": redis}
    targets = {
        "litellm": sc.settings.litellm_url(),
        "livekit": sc.settings.probe_livekit_url,
        "stt": sc.settings.probe_stt_url,
        "tts": sc.settings.probe_tts_url,
    }
    for dep, url in targets.items():
        if url:
            checks[dep] = http_get(url)
    core = get_settings()
    if core.smtp_host and now.minute % SMTP_EVERY_MIN == 0:
        connect = sc.smtp_connect or _smtp_connect
        host, port = core.smtp_host, core.smtp_port
        checks["smtp"] = lambda: connect(host, port, timeout)
    names = list(checks)
    results = await asyncio.gather(*(_timed(checks[n], timeout) for n in names))
    samples: list[Sample] = []
    for name, (ok, latency) in zip(names, results, strict=True):
        samples += _probe_samples(name, ok, latency)
    return samples


# ----------------------------------------------------------------------------- readings


async def heartbeat_samples(redis: Any) -> list[Sample]:
    beats = await read_heartbeats(redis)
    live = {str(b.get("service")) for b in beats}
    return [
        Sample(m.HEARTBEAT_UP, 1.0 if service in live else 0.0, {"service": service})
        for service in m.HEARTBEAT_SERVICES
    ]


async def queue_samples(redis: Any) -> list[Sample]:
    depth = await redis.zcard(ARQ_QUEUE)
    return [Sample(m.QUEUE_DEPTH, float(depth or 0), {"queue": ARQ_QUEUE})]


async def database_samples(maker: async_sessionmaker[AsyncSession], now: datetime) -> list[Sample]:
    samples: list[Sample] = []
    async with maker() as db:
        running = await db.scalar(
            select(func.count())
            .select_from(InterviewSession)
            .where(InterviewSession.status == SessionStatus.IN_PROGRESS)
        )
        samples.append(Sample(m.SESSIONS_IN_PROGRESS, float(running or 0)))
        last = await db.scalar(select(func.max(StripeEvent.received_at)))
        if last is not None:
            at = last if last.tzinfo else last.replace(tzinfo=UTC)
            samples.append(Sample(m.STRIPE_WEBHOOK_AGE_S, max(0.0, (now - at).total_seconds())))
        if (await db.connection()).dialect.name == "postgresql":
            size = await db.scalar(text("SELECT pg_database_size(current_database())"))
            samples.append(Sample(m.DB_SIZE_BYTES, float(size or 0)))
    return samples


async def redis_memory_samples(redis: Any) -> list[Sample]:
    info = await redis.info("memory")
    used = info.get("used_memory") if isinstance(info, dict) else None
    return [Sample(m.REDIS_MEM_BYTES, float(used))] if used is not None else []


def disk_samples(paths: dict[str, str]) -> list[Sample]:
    samples = []
    for name, path in paths.items():
        if not os.path.exists(path):
            continue
        usage = shutil.disk_usage(path)
        if usage.total:
            pct = round(usage.used / usage.total * 100, 2)
            samples.append(Sample(m.HOST_DISK_PCT, pct, {"mount": name}))
    return samples


def memory_samples(proc_dir: Path) -> list[Sample]:
    """host.mem_pct from /proc/meminfo (host values, also inside a container)."""
    path = proc_dir / "meminfo"
    if not path.exists():
        return []
    fields: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            with contextlib.suppress(ValueError):
                fields[key.strip()] = float(parts[0])
    total, available = fields.get("MemTotal"), fields.get("MemAvailable")
    if not total or available is None:
        return []
    return [Sample(m.HOST_MEM_PCT, round((total - available) / total * 100, 2))]


def load_samples(proc_dir: Path) -> list[Sample]:
    path = proc_dir / "loadavg"
    if not path.exists():
        return []
    first = path.read_text(encoding="utf-8").split()
    return [Sample(m.HOST_LOAD1, float(first[0]))] if first else []


# ------------------------------------------------------------------------------ the cron


async def collect(sc: SamplerContext, now: datetime | None = None) -> list[Sample]:
    """Every catalog reading that can be taken now. Never raises."""
    now = now or datetime.now(UTC)
    timeout = sc.settings.probe_timeout_s
    readings: dict[str, Callable[[], Awaitable[list[Sample]]]] = {
        "probes": lambda: probe_dependencies(sc, now),
        "heartbeats": lambda: heartbeat_samples(sc.redis),
        "queue": lambda: queue_samples(sc.redis),
        "database": lambda: database_samples(sc.sessionmaker, now),
        "redis_memory": lambda: redis_memory_samples(sc.redis),
    }

    async def run(name: str) -> list[Sample]:
        try:
            # Probes have their own limit each; the group gets a little more.
            return await asyncio.wait_for(readings[name](), timeout=timeout + 2)
        except Exception as exc:
            log.warning("ops sampler: %s not read: %s", name, type(exc).__name__)
            return []

    groups = await asyncio.gather(*(run(n) for n in readings))
    samples = [s for group in groups for s in group]
    local: dict[str, Callable[[], list[Sample]]] = {
        "disk": lambda: disk_samples(sc.settings.disk_paths()),
        "memory": lambda: memory_samples(sc.settings.proc_dir),
        "load": lambda: load_samples(sc.settings.proc_dir),
    }
    for name, read in local.items():
        try:
            samples += read()
        except Exception as exc:
            log.warning("ops sampler: %s not read: %s", name, type(exc).__name__)
    return samples


async def write_samples(
    maker: async_sessionmaker[AsyncSession], samples: list[Sample], ts: datetime
) -> None:
    async with maker() as db:
        db.add_all(
            OpsSample(ts=ts, metric=s.metric, value=s.value, labels_json=s.labels) for s in samples
        )
        await db.commit()


async def sample_metrics(ctx: dict[str, Any]) -> dict[str, int]:
    """The Arq cron job (every minute)."""
    sc: SamplerContext | None = ctx.get(CTX_KEY)
    if sc is None:
        sc = SamplerContext(sessionmaker=get_sessionmaker(), redis=ctx["redis"])
    now = datetime.now(UTC).replace(microsecond=0)
    samples = await collect(sc, now)
    try:
        await write_samples(sc.sessionmaker, samples, now)
    except Exception as exc:
        log.warning("ops sampler: %d samples not written: %s", len(samples), type(exc).__name__)
        return {"samples": 0}
    return {"samples": len(samples)}
