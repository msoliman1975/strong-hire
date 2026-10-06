"""Job queue used by the input and gap analysis endpoints. Production uses Arq; tests use a fake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus

# Names of the Arq functions in strong_worker.inputs.jobs. A test checks they stay in sync.
EXTRACT_JOB_TARGET = "extract_job_target"
MATCH_JOB_TARGET = "match_job_target"
PARSE_RESUME = "parse_resume"
# Names of the Arq functions in strong_worker.gap.jobs (P6).
RUN_GAP_ANALYSIS = "run_gap_analysis_job"
BUILD_INTERVIEWER_BRIEF = "build_interviewer_brief"


JobState = Literal["queued", "in_progress", "complete", "failed", "not_found"]


@dataclass(frozen=True)
class JobInfo:
    id: str
    status: JobState
    result: dict[str, Any] | None = None
    error: str | None = None


class JobQueue(Protocol):
    async def enqueue(self, function: str, job_id: str, **kwargs: Any) -> None: ...

    async def info(self, job_id: str) -> JobInfo: ...

    async def close(self) -> None: ...


class ArqJobQueue:
    def __init__(self, redis_url: str) -> None:
        self._settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def _redis(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(self._settings)
        return self._pool

    async def enqueue(self, function: str, job_id: str, **kwargs: Any) -> None:
        job = await (await self._redis()).enqueue_job(function, _job_id=job_id, **kwargs)
        if job is None:
            raise RuntimeError(f"Job {job_id} already exists")

    async def info(self, job_id: str) -> JobInfo:
        job = Job(job_id, await self._redis())
        status = await job.status()
        if status in (JobStatus.queued, JobStatus.deferred):
            return JobInfo(job_id, "queued")
        if status == JobStatus.in_progress:
            return JobInfo(job_id, "in_progress")
        if status == JobStatus.not_found:
            return JobInfo(job_id, "not_found")
        result = await job.result_info()
        if result is None:
            return JobInfo(job_id, "not_found")
        if not result.success:
            return JobInfo(job_id, "failed", error=f"{type(result.result).__name__}")
        value = result.result if isinstance(result.result, dict) else {"value": result.result}
        return JobInfo(job_id, "complete", result=value)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
