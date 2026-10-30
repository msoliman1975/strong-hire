"""Debrief and progress endpoints (FB-1 to FB-3, PR-1, PR-2), and the scoring trigger.

- GET  /sessions/{id}/debrief      status "not_ended", "not_started", "scoring", "ready" or
                                   "failed";
                                   the scorecard when ready
- GET  /job-targets/{id}/progress  Realistic-session snapshots, trends and the next session
                                   (and a Custom one when the gaps span types, CU-10);
                                   `?exclude_own_questions=true` leaves out the scores of a
                                   Custom session's own questions (CU-7)

A 10-minute mini interview gets its own debrief, but it is left out of the progress snapshots,
the trends and the "practiced" list used for the next-session advice.
- POST /sessions/{id}/scoring      start (or restart) scoring for an ended session

Custom sessions (CU-6, CU-7): the debrief lists the planned questions with their source
(planner or candidate) and category, so the web app can group the breakdown and mark "Your
question". Realistic Custom sessions count toward PR-1 like the others; the progress marks the
snapshots that use scores of own questions.

When a session ends, the session code (P7) calls `start_scoring`. The worker job
`score_session` (strong_worker.scoring.jobs) does the work; the web app polls the debrief.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.custom.access import custom_advice_scope
from strong_api.inputs.deps import Db, Me, Queue
from strong_api.inputs.queue import JobQueue
from strong_api.scoring.progress import (
    QuestionSplit,
    competency_trends,
    latest_scores,
    own_question_points,
    recommend_custom_session,
    recommend_next_session,
    split_question_scores,
    without_own_questions,
)
from strong_api.scoring.schemas import (
    AnswersAtBar,
    CustomRecommendation,
    Debrief,
    DebriefQuestion,
    DebriefSession,
    DebriefStatus,
    JobProgress,
    PreviousSignal,
    ScoringAccepted,
)
from strong_api.sessions.failure import failed_before_start, failure_reason
from strong_api.suggestions.router import debrief_suggestions
from strong_core.db.models import Company, InterviewSession, JobTarget
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import ProgressSnapshot as SnapshotRow
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.profiles import ProfileError, profile_for_session
from strong_core.schemas import (
    MINI_DURATION_MIN,
    Competency,
    CustomSessionSpec,
    GapAnalysis,
    HireSignal,
    InterviewerBrief,
    InterviewType,
    Level,
    Mode,
    PlannedSession,
    ProgressSnapshot,
    QuestionScore,
    Scorecard,
    SessionConfig,
    SessionStatus,
    session_duration,
)

# Name of the Arq function in strong_worker.scoring.jobs. A test checks they stay in sync.
SCORE_SESSION = "score_session"

router = APIRouter(tags=["scoring"])

# Sessions that can still start or continue. Their debrief has nothing to score yet.
NOT_ENDED = {SessionStatus.CREATED, SessionStatus.IN_PROGRESS, SessionStatus.INTERRUPTED}

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


def _custom(session: InterviewSession) -> CustomSessionSpec | None:
    if session.custom_json is None:
        return None
    try:
        return CustomSessionSpec.model_validate(session.custom_json)
    except ValidationError:
        return None


def _config(session: InterviewSession, target: JobTarget | None) -> SessionConfig:
    brief = _brief(session)
    if brief is not None:
        return brief.session
    values: dict[str, Any] = {
        "interview_type": session.type,
        "difficulty": session.difficulty,
        "mode": session.mode,
        "duration_min": session_duration(session.duration_min),
        "level": (target.level if target and target.level else Level.MID),
        "custom": _custom(session),  # CU-1: a Custom session's setup
        "tone": session.tone,  # TN-1
    }
    try:
        return SessionConfig.model_validate(values)
    except ValidationError:
        # A stored row that breaks today's rules (never expected) is still shown, unchecked.
        return SessionConfig.model_construct(**values)


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
    """The session plan of the newest ready gap analysis (P6), or [] when there is none."""
    row = await db.scalar(
        select(GapRow)
        .where(GapRow.job_target_id == job_target_id, GapRow.breakdown_json.is_not(None))
        .order_by(GapRow.created_at.desc())
        .limit(1)
    )
    if row is None or row.breakdown_json is None:
        return []
    try:
        return GapAnalysis.model_validate(row.breakdown_json).session_plan
    except ValidationError:
        return [PlannedSession.model_validate(p) for p in row.session_plan_json or []]


async def _practiced(db: AsyncSession, job_target_id: uuid.UUID) -> list[InterviewType]:
    """Types with a completed full session. A Custom session also practices each of its
    categories (CU-10), so the standard advice does not call them untried."""
    rows = await db.execute(
        select(InterviewSession.type, InterviewSession.custom_json).where(
            InterviewSession.job_target_id == job_target_id,
            InterviewSession.status == SessionStatus.COMPLETED,
            InterviewSession.duration_min != MINI_DURATION_MIN,
        )
    )
    out: list[InterviewType] = []
    for itype, custom in rows:
        out.append(itype)
        if itype == InterviewType.CUSTOM and custom:
            try:
                spec = CustomSessionSpec.model_validate(custom)
            except ValidationError:
                continue
            out.extend(c.category for c in spec.categories)
    return out


async def _snapshots(db: AsyncSession, job_target_id: uuid.UUID) -> list[ProgressSnapshot]:
    rows = await db.scalars(
        select(SnapshotRow)
        .join(InterviewSession, InterviewSession.id == SnapshotRow.session_id)
        .where(
            SnapshotRow.job_target_id == job_target_id,
            InterviewSession.duration_min != MINI_DURATION_MIN,  # minis never count (PR-1)
        )
        .order_by(SnapshotRow.at, SnapshotRow.competency)
    )
    return [snapshot_contract(r) for r in rows]


async def _next_sessions(
    db: AsyncSession,
    job_target_id: uuid.UUID,
    extra: dict[Competency, float] | None = None,
    custom_scope: tuple[bool, bool] = (False, False),
) -> tuple[PlannedSession | None, CustomRecommendation | None]:
    """PR-2 and CU-10: the standard next session, and a Custom one when `custom_scope` (from
    `custom_advice_scope`: allowed, 45 minutes allowed) lets it and the gaps call for it.
    `extra` adds the scores of the session being debriefed (a Coach session has no snapshots,
    but its debrief still advises from its own scores)."""
    scores = latest_scores(await _snapshots(db, job_target_id))
    scores.update(extra or {})
    plan = await _plan(db, job_target_id)
    practiced = await _practiced(db, job_target_id)
    standard = recommend_next_session(scores, plan, practiced)
    allowed, long_allowed = custom_scope
    custom = (
        recommend_custom_session(scores, plan, practiced, long_allowed=long_allowed)
        if allowed
        else None
    )
    return standard, custom


def _debrief_questions(brief: InterviewerBrief | None) -> list[DebriefQuestion]:
    if brief is None:
        return []
    return [
        DebriefQuestion(
            question_ref=q.id,
            text=q.text,
            source=q.source,
            category=q.category,
            competencies=list(q.competencies),
            must_ask=q.must_ask,
            verbatim=q.verbatim,
        )
        for q in sorted(brief.questions, key=lambda q: q.priority)
    ]


async def _own_question_splits(
    db: AsyncSession, job_target_id: uuid.UUID
) -> dict[uuid.UUID, dict[Competency, QuestionSplit]]:
    """CU-7: for each scored Custom session of the job, its per-question scores split by who
    wrote the question."""
    rows = await db.execute(
        select(InterviewSession.id, InterviewSession.brief_json, ScorecardRow.per_question_json)
        .join(ScorecardRow, ScorecardRow.session_id == InterviewSession.id)
        .where(
            InterviewSession.job_target_id == job_target_id,
            InterviewSession.type == InterviewType.CUSTOM,
        )
    )
    out: dict[uuid.UUID, dict[Competency, QuestionSplit]] = {}
    for session_id, brief_json, per_question in rows:
        try:
            brief = InterviewerBrief.model_validate(brief_json) if brief_json else None
            scores = [QuestionScore.model_validate(q) for q in per_question or []]
        except ValidationError:
            continue
        if brief is None:
            continue
        sources = {q.id: q.source for q in brief.questions}
        out[session_id] = split_question_scores(sources, scores)
    return out


@router.get("/sessions/{session_id}/debrief")
async def get_debrief(session_id: uuid.UUID, db: Db, me: Me) -> Debrief:
    """FB-1, FB-2, PR-2, DB-1, DB-2. Poll while status is "scoring" (FB-3: ready within 60
    seconds)."""
    session = await _owned_session(db, me, session_id)
    target = await db.get(JobTarget, session.job_target_id)
    row = await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
    card = scorecard_contract(row) if row is not None else None
    state: DebriefStatus
    if card is not None:
        state = "ready"
    elif failed_before_start(session):
        state = "not_started"
    elif session.status == SessionStatus.FAILED:
        state = "failed"
    elif session.status in NOT_ENDED:
        state = "not_ended"
    else:
        state = "scoring"

    try:
        profile = await profile_for_session(db, session)
        generic, company = profile.generic, profile.company_name
        # QB-4: the Questions page filters by the companies row slug.
        company_row = (
            None if profile.company_id is None else await db.get(Company, profile.company_id)
        )
        slug = None if profile.generic or company_row is None else company_row.slug
        framework = profile.values_framework.name if profile.values_framework else None
    except ProfileError:
        generic, company, slug, framework = session.profile_version is None, None, None, None

    next_session = None
    next_custom = None
    if card is not None:
        # Realistic sessions already have snapshots with exact averages. Coach sessions and
        # mini interviews do not.
        no_snapshots = session.mode == Mode.COACH or session.duration_min == MINI_DURATION_MIN
        own = (
            {c.competency: float(c.score) for c in card.competency_scores} if no_snapshots else None
        )
        next_session, next_custom = await _next_sessions(
            db, session.job_target_id, own, await custom_advice_scope(db, me)
        )
    return Debrief(
        session=DebriefSession(
            id=session.id,
            job_target_id=session.job_target_id,
            config=_config(session, target),
            status=session.status,
            started_at=session.started_at,
            ended_at=session.ended_at,
            minutes_billed=session.minutes_billed,
            failure_reason=failure_reason(session),
        ),
        status=state,
        scorecard=card,
        next_session=next_session,
        next_custom_session=next_custom,
        generic_mode=generic,
        company_name=company,
        company_slug=slug,
        values_framework=framework,
        questions=_debrief_questions(_brief(session)),
        previous_signal=None if card is None else await _previous_signal(db, session, card),
        answers_at_bar=None if card is None else answers_at_bar(card),
        suggestions=await debrief_suggestions(db, me.org_id, me.user_id, session.id),
    )


# DB-2: an answer meets the bar when its average rubric score is 3 or more.
BAR_SCORE = 3


def answers_at_bar(card: Scorecard) -> AnswersAtBar:
    """DB-2: how many scored answers met the bar."""
    averages = [sum(s.score for s in q.scores) / len(q.scores) for q in card.per_question]
    return AnswersAtBar(met=sum(1 for a in averages if a >= BAR_SCORE), scored=len(averages))


async def _previous_signal(
    db: AsyncSession, session: InterviewSession, card: Scorecard
) -> PreviousSignal | None:
    """DB-1: the latest scored session of the same job target that started before this one."""
    if session.started_at is None:
        return None
    row = (
        await db.execute(
            select(InterviewSession.id, InterviewSession.ended_at, ScorecardRow.hire_signal)
            .join(ScorecardRow, ScorecardRow.session_id == InterviewSession.id)
            .where(
                InterviewSession.job_target_id == session.job_target_id,
                InterviewSession.id != session.id,
                InterviewSession.started_at < session.started_at,
            )
            .order_by(InterviewSession.started_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    previous_id, ended_at, raw = row
    signal = HireSignal(raw)
    # HireSignal.rank is 0 for Strong Hire, so a drop in rank is a step up.
    return PreviousSignal(
        session_id=previous_id,
        hire_signal=signal,
        ended_at=ended_at,
        change=signal.rank - card.hire_signal.rank,
    )


@router.get("/job-targets/{job_target_id}/progress")
async def get_progress(
    job_target_id: uuid.UUID,
    db: Db,
    me: Me,
    exclude_own_questions: Annotated[
        bool,
        Query(description="CU-7: leave out the scores of Custom sessions' own questions."),
    ] = False,
) -> JobProgress:
    """PR-1 (Realistic sessions only, Custom ones included), PR-2 and CU-7."""
    target = await _owned_target(db, me, job_target_id)
    snapshots = await _snapshots(db, target.id)
    splits = await _own_question_splits(db, target.id)
    marked = own_question_points(snapshots, splits)
    if exclude_own_questions:
        snapshots = without_own_questions(snapshots, splits)
        marked = []
    next_session, next_custom = await _next_sessions(
        db, target.id, custom_scope=await custom_advice_scope(db, me)
    )
    return JobProgress(
        job_target_id=target.id,
        snapshots=snapshots,
        trends=competency_trends(snapshots),
        next_session=next_session,
        next_custom_session=next_custom,
        own_question_points=marked,
        own_questions_excluded=exclude_own_questions,
    )


@router.post("/sessions/{session_id}/scoring", status_code=status.HTTP_202_ACCEPTED)
async def score_session(session_id: uuid.UUID, db: Db, me: Me, queue: Queue) -> ScoringAccepted:
    """Start scoring an ended session, or retry after a failure."""
    session = await _owned_session(db, me, session_id)
    if await db.scalar(select(ScorecardRow.id).where(ScorecardRow.session_id == session.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This session is already scored")
    if session.status not in ENDED and session.ended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "End the session before scoring it")
    if failed_before_start(session):
        raise HTTPException(status.HTTP_409_CONFLICT, "This interview never started")
    job_id = await start_scoring(db, queue, session)
    return ScoringAccepted(session_id=session.id, job_id=job_id, status=session.status)
