"""Resume comparison endpoints (RC-1 to RC-8).

    POST /roles/{job_target_id}/resume-comparison               start, or compare again (202)
    GET  /roles/{job_target_id}/resume-comparison               the latest; poll while running
    POST /resume-comparisons/{comparison_id}/use                RC-6: the role uses this resume
    POST /resume-comparisons/{comparison_id}/hints/{key}/add    RC-4: copy the covering line
    POST /resume-comparisons/{comparison_id}/hints/{key}/dismiss  RC-4: hide the hint

Comparing is free like gap analysis (GA-4). A comparison that needs any new analysis counts as
one run against the gap analysis rate limit (RC-7); over the limit the API answers 429 with code
"rate_limited" and a Retry-After header. Error details for 409 are {"code", "message"}.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from strong_api.compare import ranking, service
from strong_api.compare.schemas import ResumeComparisonOut, UseResumeIn
from strong_api.gap import service as gap_service
from strong_api.gap.settings import GapSettings, get_gap_settings
from strong_api.inputs.deps import Db, Me, Queue
from strong_api.inputs.queue import STORY_IDEA_SKILLS
from strong_api.inputs.router import _owned_job_target
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import ResumeComparison
from strong_core.schemas import GapStatus, Resume

router = APIRouter(tags=["resume comparison"])

Settings = Annotated[GapSettings, Depends(get_gap_settings)]

TOO_FEW_RESUMES = "too_few_resumes"
NOT_READY = "not_ready"
CHANGED = "changed"

_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"description": "The role, the comparison, the resume or the hint does not exist."},
    409: {"description": "detail.code: too_few_resumes, not_ready or changed."},
    429: {"description": "Rate limited. detail.code is 'rate_limited'; see Retry-After."},
}


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"code": code, "message": message})


async def _owned(db: Db, me: Me, comparison_id: uuid.UUID) -> ResumeComparison:
    row = await db.scalar(
        select(ResumeComparison).where(
            ResumeComparison.id == comparison_id,
            ResumeComparison.org_id == me.org_id,
            ResumeComparison.user_id == me.user_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comparison not found")
    return row


@router.post(
    "/roles/{job_target_id}/resume-comparison",
    status_code=status.HTTP_202_ACCEPTED,
    responses=_RESPONSES,
)
async def start_comparison(
    job_target_id: uuid.UUID, db: Db, me: Me, queue: Queue, settings: Settings
) -> ResumeComparisonOut:
    """RC-1, RC-2: compare the user's resumes for this role. Reuses unchanged analyses."""
    target = await _owned_job_target(db, me, job_target_id, live=True)
    if target.parsed_json is None:
        raise _conflict(NOT_READY, "The job posting is still being read.")
    try:
        comparison = await service.start(db, queue, me=me, target=target, settings=settings)
    except service.TooFewResumesError:
        raise _conflict(TOO_FEW_RESUMES, "Add another resume to compare them.") from None
    except gap_service.RateLimitedError as exc:
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
    return await service.to_out(db, me, comparison, target, settings)


@router.get("/roles/{job_target_id}/resume-comparison", responses=_RESPONSES)
async def get_comparison(
    job_target_id: uuid.UUID, db: Db, me: Me, settings: Settings
) -> ResumeComparisonOut:
    """RC-8: the role's latest comparison. 404 when none was started."""
    target = await _owned_job_target(db, me, job_target_id)
    comparison = await service.latest(db, target.id)
    if comparison is None or comparison.user_id != me.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comparison not found")
    return await service.to_out(db, me, comparison, target, settings)


@router.post("/resume-comparisons/{comparison_id}/use", responses=_RESPONSES)
async def use_resume(
    comparison_id: uuid.UUID, body: UseResumeIn, db: Db, me: Me, settings: Settings
) -> ResumeComparisonOut:
    """RC-6: the role uses this resume from now on. Nothing switches without this call."""
    comparison = await _owned(db, me, comparison_id)
    target = await _owned_job_target(db, me, comparison.job_target_id, live=True)
    entry = next((e for e in service.entries_of(comparison) if e.resume_id == body.resume_id), None)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That resume is not in this comparison")
    resume = await db.scalar(
        select(ResumeRow).where(
            ResumeRow.id == body.resume_id,
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
        )
    )
    if resume is None:
        raise _conflict(CHANGED, "That resume was deleted. Compare again.")
    row = await db.get(GapRow, entry.gap_analysis_id)
    if row is None or row.status != GapStatus.READY or row.breakdown_json is None:
        raise _conflict(NOT_READY, "That resume's analysis is not ready yet.")
    await service.use_resume(db, me, comparison, target, resume, row)
    await db.commit()
    await db.refresh(comparison)
    return await service.to_out(db, me, comparison, target, settings)


async def _hint(
    db: Db, me: Me, comparison: ResumeComparison, key: str, settings: GapSettings
) -> tuple[ranking.Hint, ranking.Candidate]:
    target = await _owned_job_target(db, me, comparison.job_target_id)
    loaded = await service.load(db, comparison, target, settings)
    _, focus, hints = service.focus_and_hints(comparison, loaded)
    hint = next((h for h in hints if h.key == key), None)
    if hint is None or focus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hint not found")
    return hint, focus


@router.post("/resume-comparisons/{comparison_id}/hints/{key}/add", responses=_RESPONSES)
async def add_hint_line(
    comparison_id: uuid.UUID, key: str, db: Db, me: Me, queue: Queue, settings: Settings
) -> ResumeComparisonOut:
    """RC-4: copy the other resume's line into the focus resume, unchanged. No model call; the
    resume check runs again on its next read."""
    comparison = await _owned(db, me, comparison_id)
    hint, focus = await _hint(db, me, comparison, key, settings)
    if key in (comparison.applied_json or []):
        raise _conflict(CHANGED, "This line was already added.")
    if hint.source is None or not hint.source.can_add:
        raise _conflict(CHANGED, "This line can't be added to the resume. Edit the resume instead.")
    resume_row = await db.scalar(
        select(ResumeRow).where(
            ResumeRow.id == focus.resume_id,
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
        )
    )
    if resume_row is None or resume_row.parsed_json is None:
        raise _conflict(CHANGED, "That resume was deleted. Compare again.")
    current = Resume.model_validate(resume_row.parsed_json)
    if not ranking.can_add(current, hint.source.line, hint.source.place, hint.source.company):
        raise _conflict(CHANGED, "The resume changed. Compare again.")
    resume_row.parsed_json = ranking.add_line(current, hint.source).model_dump(mode="json")
    comparison.applied_json = [*(comparison.applied_json or []), key]
    await db.commit()
    if hint.source.place == "achievement":
        # RM-4: the story ideas follow the resume's achievements, as for any resume edit.
        await queue.enqueue(
            STORY_IDEA_SKILLS,
            f"story_idea_skills:{resume_row.id}:{uuid.uuid4().hex[:8]}",
            resume_id=str(resume_row.id),
            org_id=str(me.org_id),
        )
    await db.refresh(comparison)
    target = await _owned_job_target(db, me, comparison.job_target_id)
    return await service.to_out(db, me, comparison, target, settings)


@router.post("/resume-comparisons/{comparison_id}/hints/{key}/dismiss", responses=_RESPONSES)
async def dismiss_hint(
    comparison_id: uuid.UUID, key: str, db: Db, me: Me, settings: Settings
) -> ResumeComparisonOut:
    """RC-4: hide the hint. It stays hidden for this comparison."""
    comparison = await _owned(db, me, comparison_id)
    await _hint(db, me, comparison, key, settings)
    if key not in (comparison.dismissed_json or []):
        comparison.dismissed_json = [*(comparison.dismissed_json or []), key]
        await db.commit()
        await db.refresh(comparison)
    target = await _owned_job_target(db, me, comparison.job_target_id)
    return await service.to_out(db, me, comparison, target, settings)
