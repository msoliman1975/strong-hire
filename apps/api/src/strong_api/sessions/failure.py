"""Sessions that failed before they started, and the plain reason shown for them.

A session fails before it starts in two ways:
- The worker could not build the interviewer brief (for example the model provider failed).
  The worker marks it "failed" and leaves ended_at empty. If the worker job is lost, the API
  marks it failed once it has waited BRIEF_STALE_AFTER.
- The candidate ended it before joining. `POST /sessions/{id}/end` marks it "failed" and sets
  ended_at.

Neither is billed, and neither uses a free interview (`count_free_interviews_used` counts only
sessions that started and did not fail). The reason is built from the row, so no column is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from strong_core.db.models import InterviewSession
from strong_core.schemas import SessionStatus

# Longer than the brief job's two tries (600-second Arq timeout each, plus the retry wait).
BRIEF_STALE_AFTER = timedelta(minutes=25)

BRIEF_FAILED = (
    "We could not prepare your interviewer. Nothing was counted or billed. "
    "Start a new interview to try again."
)
ENDED_BEFORE_START = "This interview was ended before it started. Nothing was counted or billed."


def failed_before_start(session: InterviewSession) -> bool:
    return session.status == SessionStatus.FAILED and session.started_at is None


def failure_reason(session: InterviewSession) -> str | None:
    """The plain reason for a session that failed before it started, else None."""
    if not failed_before_start(session):
        return None
    return BRIEF_FAILED if session.ended_at is None else ENDED_BEFORE_START


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
