"""Arq worker settings. Run with:  arq strong_worker.main.WorkerSettings

P0 registers one `ping` job to prove the queue works. P2 adds the job and resume input jobs
(strong_worker.inputs.jobs). P6 adds the gap analysis and interviewer brief jobs
(strong_worker.gap.jobs). P8 adds the scorer job (strong_worker.scoring.jobs). P9 adds the
account export and file delete jobs (strong_worker.account.jobs). R1 adds the file delete for
one saved CV (delete_resume_file). R2 adds a daily cron job that deletes interviewer traces older
than 90 days (strong_worker.retention). A6 lets admins pause the gap analysis and scoring jobs
(OC-5, strong_worker.pause). A5 adds the alert engine (strong_worker.alerts): a cron every
minute, the optional daily digest, and seeding the default rules at startup. A3 adds the ops
plumbing (strong_core.ops: heartbeat, error capture, usage sink, JSON logs) and the metrics
sampler cron (strong_worker.ops.sampler), and the retention job also cleans the ops tables.
v2 S14 adds the auto-profile job for companies outside the curated list (strong_worker.profiles).
v2 S22 adds the story fit job for the plan page (strong_worker.gap.story_fit).
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings

from strong_core.config import get_settings
from strong_core.ops.logs import configure_logging
from strong_core.ops.runtime import start_ops
from strong_worker import retention
from strong_worker.account import jobs as account_jobs
from strong_worker.alerts import jobs as alert_jobs
from strong_worker.gap import jobs as gap_jobs
from strong_worker.gap import story_fit as story_fit_jobs
from strong_worker.inputs import jobs as inputs_jobs
from strong_worker.ops import sampler
from strong_worker.pause import PAUSED_MAX_TRIES
from strong_worker.profiles import jobs as profile_jobs
from strong_worker.scoring import jobs as scoring_jobs


async def ping(ctx: dict[str, Any], value: str = "pong") -> str:
    return value


OPS_KEY = "ops_runtime"


async def startup(ctx: dict[str, Any]) -> None:
    # OB-7 log lines; Arq's own handler is dropped so its lines are written once, by ours.
    configure_logging("worker", app_loggers=("strong_worker", "arq"), drop_handlers=("arq",))
    # OB-1 heartbeat (on Arq's Redis), OB-2 usage sink, OB-4 error capture.
    ctx[OPS_KEY] = await start_ops("worker", redis=ctx.get("redis"))
    await inputs_jobs.startup(ctx)
    await gap_jobs.startup(ctx)
    await scoring_jobs.startup(ctx)
    await account_jobs.startup(ctx)
    await alert_jobs.startup(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await inputs_jobs.shutdown(ctx)
    ops = ctx.pop(OPS_KEY, None)
    if ops is not None:
        await ops.stop()


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
        func(
            gap_jobs.run_gap_analysis_job,
            keep_result=gap_jobs.RESULT_TTL_S,
            timeout=600,
            max_tries=PAUSED_MAX_TRIES,  # OC-5: a paused job retries every 60 s
        ),
        func(
            gap_jobs.build_interviewer_brief,
            keep_result=gap_jobs.RESULT_TTL_S,
            timeout=600,
            max_tries=gap_jobs.BRIEF_MAX_TRIES,
        ),
        *(
            func(
                f,
                keep_result=scoring_jobs.RESULT_TTL_S,
                timeout=scoring_jobs.JOB_TIMEOUT_S,
                max_tries=PAUSED_MAX_TRIES,  # OC-5
            )
            for f in scoring_jobs.FUNCTIONS
        ),
        # ST-5: the story fit table the plan page asks for (v2 S22). The result lives in its
        # own Redis key; keep_result=0 frees the fixed job id as soon as a run ends.
        *(
            func(f, keep_result=0, timeout=300)
            for f in story_fit_jobs.FUNCTIONS
        ),
        func(account_jobs.export_account, keep_result=account_jobs.RESULT_TTL_S, timeout=600),
        # AP-1: auto-profiles for companies outside the curated list.
        *(
            func(f, keep_result=profile_jobs.RESULT_TTL_S, timeout=600)
            for f in profile_jobs.FUNCTIONS
        ),
        func(
            account_jobs.delete_account_files,
            keep_result=account_jobs.RESULT_TTL_S,
            timeout=600,
            max_tries=account_jobs.DELETE_MAX_TRIES,
        ),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(
            retention.trace_retention,
            hour=retention.RUN_AT_HOUR_UTC,
            minute=retention.RUN_AT_MINUTE,
            run_at_startup=False,
            unique=True,
        ),
        # AL-2: every minute, at second 0.
        cron(
            alert_jobs.evaluate_alerts,
            run_at_startup=False,
            unique=True,
            timeout=alert_jobs.TICK_TIMEOUT_S,
        ),
        # AL-7: off unless ALERT_DIGEST=true (checked inside the job).
        cron(
            alert_jobs.alert_digest,
            hour=get_settings().alert_digest_hour_utc,
            minute=0,
            run_at_startup=False,
            unique=True,
        ),
        # OB-5, OB-6: one ops_samples row per metric, every minute.
        cron(
            sampler.sample_metrics,
            second=0,
            run_at_startup=False,
            unique=True,
            timeout=50,
            keep_result=0,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    health_check_interval = 10
