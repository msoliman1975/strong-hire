"""Debrief and progress endpoints (FB-1 to FB-3, PR-1, PR-2), and the scoring trigger.

- GET  /sessions/{id}/debrief      status "scoring", "ready" or "failed"; the scorecard when ready
- GET  /job-targets/{id}/progress  Realistic-session snapshots, trends and the next session
- POST /sessions/{id}/scoring      start (or restart) scoring for an ended session

When a session ends, the session code (P7) calls `start_scoring`. The worker job
`score_session` (strong_worker.scoring.jobs) does the work; the web app polls the debrief.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.inputs.deps import Db, Me, Queue
from strong_api.inputs.queue import JobQueue
from strong_api.scoring.progress import (
    competency_trends,
    latest_scores,
    recommend_next_session,
)
from strong_api.scoring.schemas import (
    Debrief,
    DebriefSession,
    DebriefStatus,
    JobProgress,
    ScoringAccepted,
)
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import ProgressSnapshot as SnapshotRow
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.profiles import ProfileError, profile_for_session
from strong_core.schemas import (
    Competency,
    GapAnalysis,
    InterviewerBrief,
    InterviewType,
    Level,
    Mode,
    PlannedSession,
    ProgressSnapshot,
    Scorecard,
    SessionConfig,
    SessionStatus,
)

# Name of the Arq function in strong_worker.scoring.jobs. A test checks they stay in sync.
SCORE_SESSION = "score_session"

router = APIRouter(tags=["scoring"])

ENDED = {SessionStatus.SCORING, SessionStatus.FAILED, SessionStatus.INTERRUPTED}


async def start_scoring(db: AsyncSession, queue: JobQueue, session: InterviewSession) -> str:
    """Mark the session as scoring and enqueue the scorer job. The caller has ended the session.

    Returns the Arq job id. FB-3 is measured from `ended_at`, so it is set here if missing.
    """
    if session.ended_at is None:
        session.ended_at = datetime.now(UTC)
    session.status = SessionStatus.SCORING
    await db.commit()
    job_id = f"score:{session.id}:{uuid.uuid4().hex[:12]}"
    await queue.enqueue(
        SCORE_SESSION, job_id, session_id=str(session.id), org_id=str(session.org_id)
    )
    return job_id


def scorecard_contract(row: ScorecardRow) -> Scorecard:
    return Scorecard.model_validate(
        {
            "hire_signal": row.hire_signal,
            "rationale": row.rationale,
            "competency_scores": row.competency_scores_json,
            "value_scores": row.value_scores_json or [],
            "per_question": row.per_question_json,
            "scorer_model": row.scorer_model,
            "rubric_version": row.rubric_version,
        }
    )


def snapshot_contract(row: SnapshotRow) -> ProgressSnapshot:
    return ProgressSnapshot(
        job_target_id=row.job_target_id,
        session_id=row.session_id,
        competency=row.competency,
        score=float(row.score),
        at=row.at,
    )


def _brief(session: InterviewSession) -> InterviewerBrief | None:
    if session.brief_json is None:
        return None
    try:
        return InterviewerBrief.model_validate(session.brief_json)
    except ValidationError:
        return None


def _config(session: InterviewSession, target: JobTarget | None) -> SessionConfig:
    brief = _brief(session)
    if brief is not None:
        return brief.session
    return SessionConfig(
        interview_type=session.type,
        difficulty=session.difficulty,
        mode=session.mode,
        duration_min=45 if session.duration_min == 45 else 30,
        level=(target.level if target and target.level else Level.MID),
    )


async def _owned_session(db: Db, me: Me, session_id: uuid.UUID) -> InterviewSession:
    session = await db.scalar(
        select(InterviewSession).where(
            InterviewSession.id == session_id, InterviewSession.org_id == me.org_id
        )
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return session


async def _owned_target(db: Db, me: Me, job_target_id: uuid.UUID) -> JobTarget:
    target = await db.scalar(
        select(JobTarget).where(JobTarget.id == job_target_id, JobTarget.org_id == me.org_id)
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job target not found")
    return target


async def _plan(db: AsyncSession, job_target_id: uuid.UUID) -> list[PlannedSession]:
    row = await db.scalar(
        select(GapRow)
        .where(GapRow.job_target_id == job_target_id)
        .order_by(GapRow.created_at.desc())
        .limit(1)
    )
    if row is None:
        return []
    try:
        return GapAnalysis.model_validate(row.breakdown_json).session_plan
    except ValidationError:
        return [PlannedSession.model_validate(p) for p in row.session_plan_json]


async def _practiced(db: AsyncSession, job_target_id: uuid.UUID) -> list[InterviewType]:
    rows = await db.scalars(
        select(InterviewSession.type).where(
            InterviewSession.job_target_id == job_target_id,
            InterviewSession.status == SessionStatus.COMPLETED,
        )
    )
    return list(rows)


async def _snapshots(db: AsyncSession, job_target_id: uuid.UUID) -> list[ProgressSnapshot]:
    rows = await db.scalars(
        select(SnapshotRow)
        .where(SnapshotRow.job_target_id == job_target_id)
        .order_by(SnapshotRow.at, SnapshotRow.competency)
    )
    return [snapshot_contract(r) for r in rows]


async def next_session_for(
    db: AsyncSession, job_target_id: uuid.UUID, extra: dict[Competency, float] | None = None
) -> PlannedSession | None:
    """PR-2. `extra` adds the scores of the session being debriefed (a Coach session has no
    snapshots, but its debrief still advises from its own scores)."""
    scores = latest_scores(await _snapshots(db, job_target_id))
    scores.update(extra or {})
    return recommend_next_session(
        scores, await _plan(db, job_target_id), await _practiced(db, job_target_id)
    )


@router.get("/sessions/{session_id}/debrief")
async def get_debrief(session_id: uuid.UUID, db: Db, me: Me) -> Debrief:
    """FB-1, FB-2, PR-2. Poll while status is "scoring" (FB-3: ready within 60 seconds)."""
    session = await _owned_session(db, me, session_id)
    target = await db.get(JobTarget, session.job_target_id)
    row = await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
    card = scorecard_contract(row) if row is not None else None
    state: DebriefStatus
    if card is not None:
        state = "ready"
    elif session.status == SessionStatus.FAILED:
        state = "failed"
    else:
        state = "scoring"

    try:
        profile = await profile_for_session(db, session)
        generic, company = profile.generic, profile.company_name
        framework = profile.values_framework.name if profile.values_framework else None
    except ProfileError:
        generic, company, framework = session.profile_version is None, None, None

    next_session = None
    if card is not None:
        # Realistic sessions already have snapshots with exact averages. Coach sessions do not.
        own = (
            {c.competency: float(c.score) for c in card.competency_scores}
            if session.mode == Mode.COACH
            else None
        )
        next_session = await next_session_for(db, session.job_target_id, own)
    return Debrief(
        session=DebriefSession(
            id=session.id,
            job_target_id=session.job_target_id,
            config=_config(session, target),
            status=session.status,
            started_at=session.started_at,
            ended_at=session.ended_at,
            minutes_billed=session.minutes_billed,
        ),
        status=state,
        scorecard=card,
        next_session=next_session,
        generic_mode=generic,
        company_name=company,
        values_framework=framework,
    )


@router.get("/job-targets/{job_target_id}/progress")
async def get_progress(job_target_id: uuid.UUID, db: Db, me: Me) -> JobProgress:
    """PR-1 (Realistic sessions only) and PR-2."""
    target = await _owned_target(db, me, job_target_id)
    snapshots = await _snapshots(db, target.id)
    return JobProgress(
        job_target_id=target.id,
        snapshots=snapshots,
        trends=competency_trends(snapshots),
        next_session=await next_session_for(db, target.id),
    )


@router.post("/sessions/{session_id}/scoring", status_code=status.HTTP_202_ACCEPTED)
async def score_session(session_id: uuid.UUID, db: Db, me: Me, queue: Queue) -> ScoringAccepted:
    """Start scoring an ended session, or retry after a failure."""
    session = await _owned_session(db, me, session_id)
    if await db.scalar(select(ScorecardRow.id).where(ScorecardRow.session_id == session.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This session is already scored")
    if session.status not in ENDED and session.ended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "End the session before scoring it")
    job_id = await start_scoring(db, queue, session)
    return ScoringAccepted(session_id=session.id, job_id=job_id, status=session.status)
