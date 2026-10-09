"""GET /reports (R1): the signed-in user's gap reports and interview debriefs, newest first.

- Gap reports: gap analysis runs with status ready.
- Interview debriefs: sessions that started and ended (scoring, completed, or failed after
  they started). A session that never started has no debrief.

Reports of deleted job descriptions and CVs stay in the list with job_deleted or
resume_deleted set. Filters: job_target_id, resume_id (PR-3: one job and CV pair) and type.
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
    resume_id: uuid.UUID | None = None,
    type: ReportType | None = None,
) -> list[ReportItem]:
    """All gap reports and interview debriefs of the signed-in user, newest first (R1).

    With resume_id, only the reports made with that CV (PR-3). Debriefs of sessions from
    before the CV was recorded have no CV, so this filter leaves them out.
    """
    query = select(JobTarget).where(JobTarget.org_id == me.org_id, JobTarget.user_id == me.user_id)
    if job_target_id is not None:
        query = query.where(JobTarget.id == job_target_id)
    targets = {t.id: t for t in await db.scalars(query)}
    if not targets:
        return []
    ids = list(targets)

    gaps: list[GapRow] = []
    if type in (None, "gap_report"):
        gap_query = select(GapRow).where(
            GapRow.job_target_id.in_(ids),
            GapRow.org_id == me.org_id,
            GapRow.status == GapStatus.READY,
        )
        if resume_id is not None:
            gap_query = gap_query.where(GapRow.resume_id == resume_id)
        gaps = list((await db.scalars(gap_query)).all())

    sessions: list[InterviewSession] = []
    if type in (None, "interview_debrief"):
        session_query = select(InterviewSession).where(
            InterviewSession.job_target_id.in_(ids),
            InterviewSession.org_id == me.org_id,
            InterviewSession.started_at.is_not(None),
            InterviewSession.status.in_(DEBRIEF_STATUSES),
        )
        if resume_id is not None:
            session_query = session_query.where(InterviewSession.resume_id == resume_id)
        sessions = list((await db.scalars(session_query)).all())

    resume_ids = {g.resume_id for g in gaps} | {s.resume_id for s in sessions if s.resume_id}
    resumes = (
        {r.id: r for r in await db.scalars(select(ResumeRow).where(ResumeRow.id.in_(resume_ids)))}
        if resume_ids
        else {}
    )

    def cv(rid: uuid.UUID | None) -> tuple[str | None, bool]:
        """The CV name and whether it was deleted. No CV: no name, not deleted."""
        if rid is None:
            return None, False
        row = resumes.get(rid)
        deleted = row is None or row.deleted_at is not None
        return (None if row is None or deleted else resume_label(row)), deleted

    items: list[ReportItem] = []
    for gap in gaps:
        target = targets[gap.job_target_id]
        resume_name, resume_deleted = cv(gap.resume_id)
        items.append(
            ReportItem(
                type="gap_report",
                id=gap.id,
                job_target_id=target.id,
                job_name=job_target_name(target),
                job_deleted=target.deleted_at is not None,
                resume_id=gap.resume_id,
                resume_name=resume_name,
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

    signals: dict[uuid.UUID, HireSignal] = {}
    if sessions:
        rows = await db.execute(
            select(ScorecardRow.session_id, ScorecardRow.hire_signal).where(
                ScorecardRow.session_id.in_([s.id for s in sessions])
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
        resume_name, resume_deleted = cv(session.resume_id)
        items.append(
            ReportItem(
                type="interview_debrief",
                id=session.id,
                job_target_id=target.id,
                job_name=job_target_name(target),
                job_deleted=target.deleted_at is not None,
                resume_id=session.resume_id,
                resume_name=resume_name,
                resume_deleted=resume_deleted,
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
