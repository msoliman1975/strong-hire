"""Arq worker settings. Run with:  arq strong_worker.main.WorkerSettings

P0 registers one `ping` job to prove the queue works. Scraping, parsing, gap analysis, planner
and scorer jobs are added by later workstreams.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from strong_core.config import get_settings


async def ping(ctx: dict[str, Any], value: str = "pong") -> str:
    return value


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    health_check_interval = 10
