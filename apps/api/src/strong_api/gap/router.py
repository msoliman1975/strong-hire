"""Gap analysis endpoints (GA-1 to GA-4).

    POST /job-targets/{job_target_id}/gap-analysis   start or restart (202), body {resume_id}
    GET  /job-targets/{job_target_id}/gap-analysis   the latest run; poll while "running"
    GET  /gap-analyses/{gap_analysis_id}             one run, for the Reports page (R1)

A deleted job description or CV (R1) cannot start a run; its old reports can still be read.

Gap analysis is free and does not use plan minutes (GA-4). Each user may start a limited number
of runs per hour and per day; over the limit the API answers 429 with code "rate_limited" and a
Retry-After header.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from strong_api.gap import service
from strong_api.gap.schemas import GapAnalysisOut, GapAnalysisStart
from strong_api.gap.settings import GapSettings, get_gap_settings
from strong_api.inputs.deps import Db, Me, Queue
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import JobTarget
from strong_core.db.models import Resume as ResumeRow

router = APIRouter(tags=["gap analysis"])

Settings = Annotated[GapSettings, Depends(get_gap_settings)]

_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"description": "The job target, the resume or the analysis does not exist."},
    409: {"description": "The job posting or the resume is still being read."},
    429: {"description": "Rate limited. detail.code is 'rate_limited'; see Retry-After."},
}


async def _target(db: Db, me: Me, job_target_id: uuid.UUID, *, live: bool = False) -> JobTarget:
    target = await db.scalar(
        select(JobTarget).where(
            JobTarget.id == job_target_id,
            JobTarget.org_id == me.org_id,
            JobTarget.user_id == me.user_id,
        )
    )
    if target is None or (live and target.deleted_at is not None):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job target not found")
    return target


@router.post(
    "/job-targets/{job_target_id}/gap-analysis",
    status_code=status.HTTP_202_ACCEPTED,
    responses=_RESPONSES,
)
async def start_gap_analysis(
    job_target_id: uuid.UUID,
    body: GapAnalysisStart,
    db: Db,
    me: Me,
    queue: Queue,
    settings: Settings,
) -> GapAnalysisOut:
    """Start the gap analysis for a job and a resume. Free; rate limited per user (GA-4)."""
    target = await _target(db, me, job_target_id, live=True)
    resume_id = body.resume_id
    if resume_id is None:
        previous = await service.latest(db, target.id)
        if previous is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a resume first.")
        resume_id = previous.resume_id
    resume = await db.scalar(
        select(ResumeRow).where(
            ResumeRow.id == resume_id,
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
        )
    )
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    if target.parsed_json is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The job posting is still being read.")
    if resume.parsed_json is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The resume is still being read.")
    try:
        row = await service.start(
            db,
            queue,
            org_id=me.org_id,
            user_id=me.user_id,
            target=target,
            resume=resume,
            settings=settings,
            reuse_ready=body.reuse_ready,
        )
    except service.RateLimitedError as exc:
        minutes = max(1, round(exc.retry_after_s / 60))
        return JSONResponse(  # type: ignore[return-value]
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(exc.retry_after_s)},
            content={
                "detail": {
                    "code": "rate_limited",
                    "message": f"You started many analyses. Try again in {minutes} min.",
                    "retry_after_s": exc.retry_after_s,
                }
            },
        )
    return await service.to_out(db, row, target, settings)


@router.get("/job-targets/{job_target_id}/gap-analysis", responses=_RESPONSES)
async def get_gap_analysis(
    job_target_id: uuid.UUID, db: Db, me: Me, settings: Settings
) -> GapAnalysisOut:
    """The latest gap analysis for the job (GA-1 to GA-3). 404 when none was started."""
    target = await _target(db, me, job_target_id)
    row = await service.latest(db, target.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gap analysis not found")
    return await service.to_out(db, row, target, settings)


@router.get("/gap-analyses/{gap_analysis_id}", responses={404: _RESPONSES[404]})
async def get_gap_analysis_by_id(
    gap_analysis_id: uuid.UUID, db: Db, me: Me, settings: Settings
) -> GapAnalysisOut:
    """One gap analysis run of the signed-in user (R1 Reports page), also for a deleted job."""
    row = await db.scalar(
        select(GapRow)
        .join(JobTarget, JobTarget.id == GapRow.job_target_id)
        .where(
            GapRow.id == gap_analysis_id,
            GapRow.org_id == me.org_id,
            JobTarget.user_id == me.user_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gap analysis not found")
    target = await _target(db, me, row.job_target_id)
    return await service.to_out(db, row, target, settings)
