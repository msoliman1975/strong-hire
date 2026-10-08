"""Arq job that scores a session when it ends (FB-1 to FB-3, PR-1).

The API (strong_api.scoring.start_scoring) sets the session to SCORING and enqueues
`score_session`. The job:
- reads the transcript (turns), the brief and the exact profile version the session used;
- runs the scorer and stores one Scorecard row;
- writes one ProgressSnapshot per competency, for Realistic sessions only (PR-1). A 10-minute
  mini interview gets a debrief but no snapshots: 3 questions are a practice signal, not a trend;
- sets the session to COMPLETED, or FAILED with a reason when scoring is not possible.

FB-3 asks for the debrief within 60 seconds of the session end. The job measures the time from
`sessions.ended_at` to the stored scorecard, returns it as `ready_after_s`, and logs a warning
when it is over the budget.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import InterviewSession
from strong_core.db.models import ProgressSnapshot as SnapshotRow
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import TURN_ORDER
from strong_core.gateway import ModelGateway, get_gateway
from strong_core.profiles import ProfileError, profile_for_session
from strong_core.schemas import MINI_DURATION_MIN, InterviewerBrief, Mode, SessionStatus, Turn
from strong_worker.scoring.scorer import ScoringError, ScoringOutcome, SessionScorer

log = logging.getLogger(__name__)

CTX_KEY = "scoring"
DEBRIEF_BUDGET_S = 60.0
JOB_TIMEOUT_S = 300
RESULT_TTL_S = 24 * 3600


@dataclass
class ScoringContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    gateway: ModelGateway


async def startup(ctx: dict[str, Any]) -> None:
    ctx[CTX_KEY] = ScoringContext(sessionmaker=get_sessionmaker(), gateway=get_gateway())


def _ctx(ctx: dict[str, Any]) -> ScoringContext:
    value = ctx[CTX_KEY]
    assert isinstance(value, ScoringContext)
    return value


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


async def load_turns(db: AsyncSession, session_id: uuid.UUID) -> list[Turn]:
    rows = await db.scalars(
        select(TurnRow).where(TurnRow.session_id == session_id).order_by(*TURN_ORDER)
    )
    return [
        Turn(
            speaker=r.speaker,
            phase=r.phase,
            text=r.text,
            start_ms=r.start_ms,
            end_ms=r.end_ms,
            question_ref=r.question_ref,
        )
        for r in rows
    ]


async def score_session(ctx: dict[str, Any], session_id: str, org_id: str) -> dict[str, Any]:
    scoring = _ctx(ctx)
    async with scoring.sessionmaker() as db:
        session = await db.scalar(
            select(InterviewSession).where(
                InterviewSession.id == uuid.UUID(session_id),
                InterviewSession.org_id == uuid.UUID(org_id),
            )
        )
        if session is None:
            return {"outcome": "failed", "reason": "session not found"}
        existing = await db.scalar(
            select(ScorecardRow.id).where(ScorecardRow.session_id == session.id)
        )
        if existing is not None:
            return {"outcome": "exists", "scorecard_id": str(existing)}

        try:
            outcome = await _score(db, scoring.gateway, session)
        except (ScoringError, ProfileError) as exc:
            return await _fail(db, session, str(exc))
        except Exception as exc:  # a model or gateway failure: the user sees a failed debrief
            log.exception("scoring failed for session %s", session.id)
            return await _fail(db, session, f"Scoring failed: {type(exc).__name__}")

        card = outcome.scorecard
        row = ScorecardRow(
            org_id=session.org_id,
            session_id=session.id,
            hire_signal=card.hire_signal,
            rationale=card.rationale,
            competency_scores_json=[c.model_dump(mode="json") for c in card.competency_scores],
            value_scores_json=[v.model_dump(mode="json") for v in card.value_scores],
            per_question_json=[q.model_dump(mode="json") for q in card.per_question],
            scorer_model=card.scorer_model,
            rubric_version=card.rubric_version,
        )
        db.add(row)
        now = datetime.now(UTC)
        ended = _aware(session.ended_at) if session.ended_at else now
        snapshots = 0
        if session.mode == Mode.REALISTIC and session.duration_min != MINI_DURATION_MIN:
            for competency, average in outcome.competency_averages.items():
                db.add(
                    SnapshotRow(
                        org_id=session.org_id,
                        job_target_id=session.job_target_id,
                        session_id=session.id,
                        competency=competency,
                        score=Decimal(f"{average:.2f}"),
                        at=ended,
                    )
                )
                snapshots += 1
        session.status = SessionStatus.COMPLETED
        if session.ended_at is None:
            session.ended_at = now
        await db.commit()

    ready_after = (datetime.now(UTC) - ended).total_seconds()
    if ready_after > DEBRIEF_BUDGET_S:
        log.warning(
            "FB-3: debrief for session %s was ready %.1f s after the end (budget %.0f s)",
            session_id,
            ready_after,
            DEBRIEF_BUDGET_S,
        )
    return {
        "outcome": "scored",
        "hire_signal": card.hire_signal.value,
        "average": outcome.signal.average,
        "snapshots": snapshots,
        "dropped_quotes": len(outcome.dropped_quotes),
        "dropped_scores": len(outcome.dropped_scores),
        "reasked": outcome.reasked,
        "rationale_source": outcome.rationale_source,
        "model_calls": outcome.model_calls,
        "scoring_s": outcome.seconds,
        "ready_after_s": round(ready_after, 3),
        "within_budget": ready_after <= DEBRIEF_BUDGET_S,
    }


async def _score(
    db: AsyncSession, gateway: ModelGateway, session: InterviewSession
) -> ScoringOutcome:
    if session.brief_json is None:
        raise ScoringError("The session has no interviewer brief.")
    brief = InterviewerBrief.model_validate(session.brief_json)
    turns = await load_turns(db, session.id)
    profile = await profile_for_session(db, session)
    return await SessionScorer(gateway).score(brief, turns, profile)


async def _fail(db: AsyncSession, session: InterviewSession, reason: str) -> dict[str, Any]:
    session.status = SessionStatus.FAILED
    await db.commit()
    log.warning("session %s not scored: %s", session.id, reason)
    return {"outcome": "failed", "reason": reason}


FUNCTIONS = [score_session]
