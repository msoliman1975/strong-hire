"""Sessions that failed with nothing to score, and the plain reason shown for them.

A session fails before it starts in two ways:
- The worker could not build the interviewer brief (for example the model provider failed).
  The worker marks it "failed" and leaves ended_at empty. If the worker job is lost, the API
  marks it failed once it has waited BRIEF_STALE_AFTER.
- The candidate ended it before joining. `POST /sessions/{id}/end` marks it "failed" and sets
  ended_at.

A session can also start and end with no answer from the candidate (BL-3): the interviewer
greeted, but no candidate turn was saved (they left, or the microphone or speech-to-text never
delivered a word). The session end marks it "failed" without billing it or starting scoring,
because the scorer refuses a transcript without answers.

None of these is billed, and none uses a free interview (`count_free_interviews_used` counts only
sessions that started and did not fail). The reasons are built from the row and its turns, so no
column is needed. Sessions from before BL-3 that were billed keep their minutes; their reason
leaves out "nothing was billed".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import InterviewSession, Turn
from strong_core.schemas import SessionStatus, Speaker

# Longer than the brief job's two tries (600-second Arq timeout each, plus the retry wait).
BRIEF_STALE_AFTER = timedelta(minutes=25)

BRIEF_FAILED = (
    "We could not prepare your interviewer. Nothing was counted or billed. "
    "Start a new interview to try again."
)
ENDED_BEFORE_START = "This interview was ended before it started. Nothing was counted or billed."
NO_ANSWERS = (
    "This interview ended before we got any answer from you, so there is nothing to score. "
    "If you spoke, check that your microphone works, then start a new interview."
)
NOT_BILLED = "Nothing was counted or billed."


def failed_before_start(session: InterviewSession) -> bool:
    return session.status == SessionStatus.FAILED and session.started_at is None


def failed_without_answers(session: InterviewSession, answered: bool) -> bool:
    """BL-3: started, failed, and the candidate never answered."""
    return (
        session.status == SessionStatus.FAILED and session.started_at is not None and not answered
    )


def failure_reason(session: InterviewSession, *, answered: bool = True) -> str | None:
    """The plain reason for a session that failed with nothing to score, else None.

    `answered` says whether the session has a candidate turn (`answered_session_ids`). Callers
    that pass nothing get the reasons for sessions that never started only."""
    if failed_without_answers(session, answered):
        return NO_ANSWERS if session.minutes_billed else f"{NO_ANSWERS} {NOT_BILLED}"
    if not failed_before_start(session):
        return None
    return BRIEF_FAILED if session.ended_at is None else ENDED_BEFORE_START


def has_answers_clause() -> ColumnElement[bool]:
    """SQL: the session row has at least one candidate turn."""
    return (
        select(Turn.id)
        .where(Turn.session_id == InterviewSession.id, Turn.speaker == Speaker.CANDIDATE)
        .exists()
    )


async def answered_session_ids(
    db: AsyncSession, session_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """The sessions among `session_ids` that have at least one candidate turn."""
    ids = list(session_ids)
    if not ids:
        return set()
    rows = await db.scalars(
        select(Turn.session_id)
        .where(Turn.session_id.in_(ids), Turn.speaker == Speaker.CANDIDATE)
        .distinct()
    )
    return set(rows)


async def has_answers(db: AsyncSession, session_id: uuid.UUID) -> bool:
    return session_id in await answered_session_ids(db, [session_id])


async def answered_unless_failed(db: AsyncSession, session: InterviewSession) -> bool:
    """Whether the session counts as answered for `failure_reason`. Only a failed session that
    started needs the query; every other session is treated as answered."""
    if session.status != SessionStatus.FAILED or session.started_at is None:
        return True
    return await has_answers(db, session.id)


def brief_is_stale(session: InterviewSession, now: datetime | None = None) -> bool:
    """True when the brief has not come after BRIEF_STALE_AFTER: the worker job was lost."""
    if session.status != SessionStatus.CREATED or session.brief_json is not None:
        return False
    if session.started_at is not None or session.created_at is None:
        return False
    created = session.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - created > BRIEF_STALE_AFTER
