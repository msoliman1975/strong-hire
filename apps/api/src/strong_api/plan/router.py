"""Interview plan page (PP-1, PP-2, PP-4).

    GET /plan/{job_target_id}/{resume_id}          one PlanView for the job and CV pair
    PUT /plan/{job_target_id}/interview-date       set or clear the real interview date (PP-2)

The view is read-only and reuses the gap analysis (GA-1 to GA-3), reports (PR-3) and progress
(PR-2) code. Sessions start through the existing POST /sessions.

S23 (story fit) and S34 (readiness, day plan) add their own endpoint files in this package.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from strong_api.gap import service as gap_service
from strong_api.gap.settings import GapSettings, get_gap_settings
from strong_api.inputs.deps import Db, Me
from strong_api.inputs.router import _job_target_out, _owned_job_target, _owned_resume, _resume_out
from strong_api.plan import service
from strong_api.plan.schemas import InterviewDateIn, InterviewDateOut, PlanView
from strong_api.reports.router import list_reports
from strong_api.scoring.router import get_progress
from strong_core.db.models import User
from strong_core.profiles import resolve_profile
from strong_core.schemas import GapStatus, JobPosting

router = APIRouter(tags=["interview plan"])

Settings = Annotated[GapSettings, Depends(get_gap_settings)]

# A typo guard, not a rule: a date this far back is surely not the coming interview.
PAST_DAYS_ALLOWED = 1


@router.get(
    "/plan/{job_target_id}/{resume_id}",
    responses={404: {"description": "The job target or the resume does not exist."}},
)
async def get_plan(
    job_target_id: uuid.UUID, resume_id: uuid.UUID, db: Db, me: Me, settings: Settings
) -> PlanView:
    """PP-1: the plan page for one job and CV pair. PP-2: days left to the interview date."""
    target = await _owned_job_target(db, me, job_target_id)
    resume = await _owned_resume(db, me, resume_id)
    profile = await resolve_profile(db, target.company_id)

    gap_row = await service.latest_pair_gap(db, target.id, resume.id)
    gap = await gap_service.to_out(db, gap_row, target, settings) if gap_row else None
    analysis = gap.analysis if gap and gap.status == GapStatus.READY else None
    reports = await list_reports(db, me, job_target_id=target.id, resume_id=resume.id)
    progress = await get_progress(target.id, db, me)

    user = await db.get(User, me.user_id)
    level = target.level or (user.target_level if user else None)
    posting = JobPosting.model_validate(target.parsed_json) if target.parsed_json else None
    return PlanView(
        job=await _job_target_out(db, target),
        resume=_resume_out(resume),
        company_mode="generic" if profile.generic else "curated",
        company_name=profile.company_name or (posting.company_name if posting else None),
        values_framework=profile.values_framework.name if profile.values_framework else None,
        interview_date=target.interview_date,
        days_left=service.days_left(target.interview_date),
        tested=service.tested(profile, target),
        gap=gap,
        reports=reports,
        next_session=progress.next_session,
        next_custom_session=progress.next_custom_session,
        setup=service.setup_defaults(
            generic=profile.generic,
            analysis=analysis,
            next_session=progress.next_session,
            level=level,
        ),
    )


@router.put(
    "/plan/{job_target_id}/interview-date",
    responses={
        404: {"description": "The job target does not exist or was deleted."},
        422: {"description": "The date is in the past."},
    },
)
async def set_interview_date(
    job_target_id: uuid.UUID, body: InterviewDateIn, db: Db, me: Me
) -> InterviewDateOut:
    """PP-2: set the real interview date, or clear it with null."""
    target = await _owned_job_target(db, me, job_target_id, live=True)
    left = service.days_left(body.interview_date)
    if left is not None and left < -PAST_DAYS_ALLOWED:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose today or a later date."
        )
    target.interview_date = body.interview_date
    await db.commit()
    return InterviewDateOut(interview_date=target.interview_date, days_left=left)
