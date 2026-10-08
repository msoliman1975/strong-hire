"""Arq worker settings. Run with:  arq strong_worker.main.WorkerSettings

P0 registers one `ping` job to prove the queue works. P2 adds the job and resume input jobs
(strong_worker.inputs.jobs). P6 adds the gap analysis and interviewer brief jobs
(strong_worker.gap.jobs). P8 adds the scorer job (strong_worker.scoring.jobs). P9 adds the
account export and file delete jobs (strong_worker.account.jobs). R1 adds the file delete for
one saved CV (delete_resume_file).
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import func
from arq.connections import RedisSettings

from strong_core.config import get_settings
from strong_worker.account import jobs as account_jobs
from strong_worker.gap import jobs as gap_jobs
from strong_worker.inputs import jobs as inputs_jobs
from strong_worker.scoring import jobs as scoring_jobs


async def ping(ctx: dict[str, Any], value: str = "pong") -> str:
    return value


async def startup(ctx: dict[str, Any]) -> None:
    await inputs_jobs.startup(ctx)
    await gap_jobs.startup(ctx)
    await scoring_jobs.startup(ctx)
    await account_jobs.startup(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await inputs_jobs.shutdown(ctx)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        *(
            func(f, keep_result=inputs_jobs.RESULT_TTL_S, timeout=600)
            for f in inputs_jobs.FUNCTIONS
            if f is not inputs_jobs.delete_resume_file
        ),
        func(
            inputs_jobs.delete_resume_file,
            keep_result=inputs_jobs.RESULT_TTL_S,
            timeout=600,
            max_tries=inputs_jobs.DELETE_FILE_MAX_TRIES,
        ),
        *(func(f, keep_result=gap_jobs.RESULT_TTL_S, timeout=600) for f in gap_jobs.FUNCTIONS),
        *(
            func(f, keep_result=scoring_jobs.RESULT_TTL_S, timeout=scoring_jobs.JOB_TIMEOUT_S)
            for f in scoring_jobs.FUNCTIONS
        ),
        func(account_jobs.export_account, keep_result=account_jobs.RESULT_TTL_S, timeout=600),
        func(
            account_jobs.delete_account_files,
            keep_result=account_jobs.RESULT_TTL_S,
            timeout=600,
            max_tries=account_jobs.DELETE_MAX_TRIES,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    health_check_interval = 10
