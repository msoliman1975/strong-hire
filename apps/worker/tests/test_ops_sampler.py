"""The metrics sampler cron (OB-5, OB-6): every catalog metric, probes that fail alone."""

from __future__ import annotations

import fnmatch
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from arq.cron import CronJob
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession, JobTarget, OpsSample, StripeEvent
from strong_core.ops import metrics as m
from strong_core.schemas import Difficulty, InterviewType, Mode, SessionStatus
from strong_worker.main import WorkerSettings
from strong_worker.ops import sampler
from strong_worker.ops.sampler import ProbeSettings, SamplerContext

Maker = async_sessionmaker[AsyncSession]


class FakeRedis:
    def __init__(self, beats: dict[str, dict[str, str]]) -> None:
        self.data = {k: json.dumps(v) for k, v in beats.items()}

    async def ping(self) -> bool:
        return True

    async def zcard(self, name: str) -> int:
        return 3 if name == sampler.ARQ_QUEUE else 0

    async def info(self, section: str) -> dict[str, Any]:
        return {"used_memory": 1_048_576}

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.data.get(k) for k in keys]

    async def scan_iter(self, match: str | None = None, count: int | None = None) -> Any:
        for key in list(self.data):
            if match is None or fnmatch.fnmatch(key, match):
                yield key


def _transport(request: httpx.Request) -> httpx.Response:
    if request.url.host == "stt":
        return httpx.Response(503)
    if request.url.host == "tts":
        raise httpx.ConnectError("refused")
    return httpx.Response(200)


async def _smtp_ok(host: str, port: int, limit_s: float) -> None:
    return None


def _proc(tmp_path: Path) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text("MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 250 kB\n")
    (proc / "loadavg").write_text("0.42 0.30 0.20 1/100 1234\n")
    return proc


async def _fill(maker: Maker, account: tuple[uuid.UUID, uuid.UUID], now: datetime) -> None:
    org_id, user_id = account
    async with maker() as db:
        job = JobTarget(org_id=org_id, user_id=user_id, raw_text="Engineer")
        db.add(job)
        await db.flush()
        for status in (SessionStatus.IN_PROGRESS, SessionStatus.IN_PROGRESS, SessionStatus.SCORING):
            db.add(
                InterviewSession(
                    org_id=org_id,
                    job_target_id=job.id,
                    type=InterviewType.BEHAVIORAL,
                    difficulty=Difficulty.REALISTIC,
                    mode=Mode.REALISTIC,
                    duration_min=30,
                    status=status,
                )
            )
        db.add(StripeEvent(id="evt_1", type="invoice.paid", received_at=now - timedelta(hours=2)))
        await db.commit()


def _context(maker: Maker, tmp_path: Path) -> SamplerContext:
    settings = ProbeSettings(
        probe_litellm_url="http://litellm:4000/health/liveliness",
        probe_livekit_url="http://livekit:7880",
        probe_stt_url="http://stt:8000/health",
        probe_tts_url="http://tts:8880/health",
        host_disk_paths=f"root={tmp_path},pgdata={tmp_path / 'not-mounted'}",
        proc_dir=_proc(tmp_path),
    )
    redis = FakeRedis(
        {
            "heartbeat:api:a-1": {"service": "api"},
            "heartbeat:worker:w-1": {"service": "worker"},
        }
    )
    return SamplerContext(
        sessionmaker=maker,
        redis=redis,
        settings=settings,
        http=lambda: httpx.AsyncClient(transport=httpx.MockTransport(_transport)),
        smtp_connect=_smtp_ok,
    )


async def test_ob5_ob6_sampler_writes_every_catalog_metric(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID], tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    from strong_core.config import get_settings

    get_settings.cache_clear()
    now = datetime(2026, 10, 18, 12, 10, tzinfo=UTC)  # minute 10: the SMTP probe runs
    await _fill(sessionmaker, account, now)
    samples = await sampler.collect(_context(sessionmaker, tmp_path), now)

    def value(metric: str, **labels: str) -> float:
        hits = [s.value for s in samples if s.metric == metric and (s.labels or {}) == labels]
        assert len(hits) == 1, (metric, labels, hits)
        return hits[0]

    up = {s.labels["dep"]: s.value for s in samples if s.metric == m.PROBE_UP and s.labels}
    assert up == {
        "postgres": 1.0,
        "redis": 1.0,
        "litellm": 1.0,
        "livekit": 1.0,
        "stt": 0.0,  # HTTP 503
        "tts": 0.0,  # connection refused: the other probes still ran
        "smtp": 1.0,
    }
    assert set(up) == set(m.PROBE_DEPS)
    assert value(m.PROBE_LATENCY_MS, dep="postgres") >= 0
    assert value(m.HEARTBEAT_UP, service="api") == 1.0
    assert value(m.HEARTBEAT_UP, service="worker") == 1.0
    assert value(m.HEARTBEAT_UP, service="voice") == 0.0
    assert value(m.QUEUE_DEPTH, queue=sampler.ARQ_QUEUE) == 3
    assert value(m.SESSIONS_IN_PROGRESS) == 2
    assert 0 < value(m.HOST_DISK_PCT, mount="root") <= 100
    assert not [
        s for s in samples if s.metric == m.HOST_DISK_PCT and s.labels == {"mount": "pgdata"}
    ]
    assert value(m.HOST_MEM_PCT) == 75.0
    assert value(m.HOST_LOAD1) == 0.42
    assert value(m.REDIS_MEM_BYTES) == 1_048_576
    assert value(m.STRIPE_WEBHOOK_AGE_S) == 7200
    names = {s.metric for s in samples}
    assert names == set(m.SAMPLED_METRICS) - {m.DB_SIZE_BYTES}  # pg_database_size: Postgres only
    get_settings.cache_clear()


async def test_ob6_smtp_is_probed_only_every_10_minutes(
    sessionmaker: Maker, tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    from strong_core.config import get_settings

    get_settings.cache_clear()
    sc = _context(sessionmaker, tmp_path)
    samples = await sampler.probe_dependencies(sc, datetime(2026, 10, 18, 12, 11, tzinfo=UTC))
    assert "smtp" not in {s.labels["dep"] for s in samples if s.labels}
    get_settings.cache_clear()


async def test_ob5_cron_writes_rows_every_minute(sessionmaker: Maker, tmp_path: Path) -> None:
    jobs = [j for j in WorkerSettings.cron_jobs if isinstance(j, CronJob)]
    cron = next(j for j in jobs if j.coroutine is sampler.sample_metrics)
    assert cron.minute is None and cron.hour is None  # every minute
    result = await sampler.sample_metrics({sampler.CTX_KEY: _context(sessionmaker, tmp_path)})
    async with sessionmaker() as db:
        rows = list(await db.scalars(select(OpsSample)))
    assert result["samples"] == len(rows) > 10
    assert len({r.ts for r in rows}) == 1
    assert all(r.metric in m.SAMPLED_METRICS for r in rows)


async def test_ob5_sampler_survives_a_broken_reading(sessionmaker: Maker, tmp_path: Path) -> None:
    sc = _context(sessionmaker, tmp_path)

    class BrokenRedis(FakeRedis):
        async def zcard(self, name: str) -> int:
            raise ConnectionError("gone")

        async def ping(self) -> bool:
            raise ConnectionError("gone")

    sc.redis = BrokenRedis({})
    samples = await sampler.collect(sc)
    names = {s.metric for s in samples}
    assert m.QUEUE_DEPTH not in names and m.SESSIONS_IN_PROGRESS in names
    redis_up = [s.value for s in samples if s.metric == m.PROBE_UP and s.labels == {"dep": "redis"}]
    assert redis_up == [0.0]
