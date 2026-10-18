"""Service heartbeats in Redis (admin spec OB-1).

Each api, worker and voice process writes `heartbeat:<service>:<instance>` every 15 s with a
60 s TTL. The value is JSON: {service, instance, version, model_profile, started_at, at}. A
service with no live key is down. The model profile in each value is how the admin app shows
what every service runs and flags a mismatch (D-11: no runtime profile switch, OC-6). The worker sampler turns the keys into `heartbeat.up`
samples, and GET /health fails when no worker key exists (AL-8).

    beat = Heartbeat(redis, "api", model_profile="local")
    beat.start()          # a background task; never raises
    ...
    await beat.stop()     # deletes the key, so a clean shutdown shows at once
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
from datetime import UTC, datetime
from typing import Any, Protocol

from strong_core import __version__

log = logging.getLogger(__name__)

KEY_PREFIX = "heartbeat"
INTERVAL_S = 15.0
TTL_S = 60
SERVICES = ("api", "worker", "voice")


class HeartbeatRedis(Protocol):
    """The part of redis.asyncio.Redis the heartbeat uses (tests pass a small fake)."""

    async def set(self, name: str, value: str, ex: int | None = None) -> Any: ...

    async def delete(self, *names: str) -> Any: ...

    async def mget(self, keys: list[str]) -> list[Any]: ...

    def scan_iter(self, match: str | None = None, count: int | None = None) -> Any: ...


def heartbeat_key(service: str, instance: str) -> str:
    return f"{KEY_PREFIX}:{service}:{instance}"


def default_instance() -> str:
    """Host name (the container id under Docker) and process id. No colons."""
    return f"{socket.gethostname()}-{os.getpid()}".replace(":", "-")


def release() -> str:
    """The running release: RELEASE (or GIT_SHA) when the deploy sets it, else the version."""
    return os.environ.get("RELEASE") or os.environ.get("GIT_SHA") or __version__


class Heartbeat:
    def __init__(
        self,
        redis: HeartbeatRedis,
        service: str,
        *,
        model_profile: str,
        instance: str | None = None,
        version: str | None = None,
        interval_s: float = INTERVAL_S,
        ttl_s: int = TTL_S,
    ) -> None:
        self.redis = redis
        self.service = service
        self.instance = instance or default_instance()
        self.key = heartbeat_key(service, self.instance)
        self.version = version or release()
        self.model_profile = model_profile
        self.started_at = datetime.now(UTC)
        self.interval_s = interval_s
        self.ttl_s = ttl_s
        self._task: asyncio.Task[None] | None = None

    def payload(self, at: datetime | None = None) -> dict[str, str]:
        return {
            "service": self.service,
            "instance": self.instance,
            "version": self.version,
            "model_profile": self.model_profile,
            "started_at": self.started_at.isoformat(),
            "at": (at or datetime.now(UTC)).isoformat(),
        }

    async def beat(self) -> bool:
        """Write the key once. False (logged) when Redis is unreachable."""
        try:
            await self.redis.set(self.key, json.dumps(self.payload()), ex=self.ttl_s)
            return True
        except Exception as exc:
            log.warning("heartbeat %s not written: %s", self.key, exc)
            return False

    async def run(self) -> None:
        while True:
            await self.beat()
            await asyncio.sleep(self.interval_s)

    def start(self) -> asyncio.Task[None]:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name=f"heartbeat-{self.service}")
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        with contextlib.suppress(Exception):
            await self.redis.delete(self.key)


async def read_heartbeats(
    redis: HeartbeatRedis, service: str | None = None
) -> list[dict[str, Any]]:
    """The live heartbeats (all services, or one), as their JSON values."""
    match = f"{KEY_PREFIX}:{service or '*'}:*"
    keys = [k.decode() if isinstance(k, bytes) else str(k) async for k in redis.scan_iter(match)]
    if not keys:
        return []
    out: list[dict[str, Any]] = []
    for key, raw in zip(keys, await redis.mget(keys), strict=True):
        if raw is None:
            continue  # expired between scan and get
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        parts = key.split(":", 2)
        value.setdefault("service", parts[1] if len(parts) > 1 else "")
        value.setdefault("instance", parts[2] if len(parts) > 2 else "")
        out.append(value)
    return out


async def service_up(redis: HeartbeatRedis, service: str) -> bool:
    return bool(await read_heartbeats(redis, service))
