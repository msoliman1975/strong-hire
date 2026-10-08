"""GET /reports (R1): the signed-in user's gap reports and interview debriefs, newest first.

- Gap reports: gap analysis runs with status ready.
- Interview debriefs: sessions that started and ended (scoring, completed, or failed after
  they started). A session that never started has no debrief.

Reports of deleted job descriptions and CVs stay in the list with job_deleted or
resume_deleted set. Filters: job_target_id and type.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from strong_api.gap.service import resume_label, utc
from strong_api.inputs.deps import Db, Me
from strong_api.inputs.router import job_target_name
from strong_api.reports.schemas import ReportItem, ReportStatus, ReportType
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.schemas import GapStatus, HireSignal, SessionStatus

router = APIRouter(tags=["reports"])

DEBRIEF_STATUSES = (SessionStatus.SCORING, SessionStatus.COMPLETED, SessionStatus.FAILED)


@router.get("/reports")
async def list_reports(
    db: Db,
    me: Me,
    job_target_id: uuid.UUID | None = None,
    type: ReportType | None = None,
) -> list[ReportItem]:
    """All gap reports and interview debriefs of the signed-in user, newest first (R1)."""
    query = select(JobTarget).where(JobTarget.org_id == me.org_id, JobTarget.user_id == me.user_id)
    if job_target_id is not None:
        query = query.where(JobTarget.id == job_target_id)
    targets = {t.id: t for t in await db.scalars(query)}
    if not targets:
        return []
    ids = list(targets)
    items: list[ReportItem] = []

    if type in (None, "gap_report"):
        gaps = (
            await db.scalars(
                select(GapRow).where(
                    GapRow.job_target_id.in_(ids),
                    GapRow.org_id == me.org_id,
                    GapRow.status == GapStatus.READY,
                )
            )
        ).all()
        resume_ids = {g.resume_id for g in gaps}
        resumes = (
            {
                r.id: r
                for r in await db.scalars(select(ResumeRow).where(ResumeRow.id.in_(resume_ids)))
            }
            if resume_ids
            else {}
        )
        for gap in gaps:
            target = targets[gap.job_target_id]
            resume = resumes.get(gap.resume_id)
            resume_deleted = resume is None or resume.deleted_at is not None
            items.append(
                ReportItem(
                    type="gap_report",
                    id=gap.id,
                    job_target_id=target.id,
                    job_name=job_target_name(target),
                    job_deleted=target.deleted_at is not None,
                    resume_id=gap.resume_id,
                    resume_name=None if resume is None or resume_deleted else resume_label(resume),
                    resume_deleted=resume_deleted,
                    status="ready",
                    at=utc(gap.updated_at or gap.created_at),
                    match_score=gap.match_score,
                    hire_signal=None,
                    interview_type=None,
                    mode=None,
                    duration_min=None,
                )
            )

    if type in (None, "interview_debrief"):
        sessions = (
            await db.scalars(
                select(InterviewSession).where(
                    InterviewSession.job_target_id.in_(ids),
                    InterviewSession.org_id == me.org_id,
                    InterviewSession.started_at.is_not(None),
                    InterviewSession.status.in_(DEBRIEF_STATUSES),
                )
            )
        ).all()
        session_ids = [s.id for s in sessions]
        signals: dict[uuid.UUID, HireSignal] = {}
        if session_ids:
            rows = await db.execute(
                select(ScorecardRow.session_id, ScorecardRow.hire_signal).where(
                    ScorecardRow.session_id.in_(session_ids)
                )
            )
            signals = {session_id: signal for session_id, signal in rows}
        for session in sessions:
            target = targets[session.job_target_id]
            signal = signals.get(session.id)
            state: ReportStatus
            if signal is not None:
                state = "ready"
            elif session.status == SessionStatus.FAILED:
                state = "failed"
            else:
                state = "scoring"
            when: datetime = session.ended_at or session.started_at or session.created_at
            items.append(
                ReportItem(
                    type="interview_debrief",
                    id=session.id,
                    job_target_id=target.id,
                    job_name=job_target_name(target),
                    job_deleted=target.deleted_at is not None,
                    resume_id=None,
                    resume_name=None,
                    resume_deleted=False,
                    status=state,
                    at=utc(when),
                    match_score=None,
                    hire_signal=signal,
                    interview_type=session.type,
                    mode=session.mode,
                    duration_min=session.duration_min,
                )
            )

    items.sort(key=lambda item: (item.at, str(item.id)), reverse=True)
    return items
