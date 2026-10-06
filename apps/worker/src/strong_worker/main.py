"""Arq worker settings. Run with:  arq strong_worker.main.WorkerSettings

P0 registers one `ping` job to prove the queue works. P2 adds the job and resume input jobs
(strong_worker.inputs.jobs). P6 adds the gap analysis and interviewer brief jobs
(strong_worker.gap.jobs). Scorer jobs are added by later workstreams.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import func
from arq.connections import RedisSettings

from strong_core.config import get_settings
from strong_worker.gap import jobs as gap_jobs
from strong_worker.inputs import jobs as inputs_jobs


async def ping(ctx: dict[str, Any], value: str = "pong") -> str:
    return value


async def startup(ctx: dict[str, Any]) -> None:
    await inputs_jobs.startup(ctx)
    await gap_jobs.startup(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await inputs_jobs.shutdown(ctx)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        *(
            func(f, keep_result=inputs_jobs.RESULT_TTL_S, timeout=600)
            for f in inputs_jobs.FUNCTIONS
        ),
        *(func(f, keep_result=gap_jobs.RESULT_TTL_S, timeout=600) for f in gap_jobs.FUNCTIONS),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    health_check_interval = 10
