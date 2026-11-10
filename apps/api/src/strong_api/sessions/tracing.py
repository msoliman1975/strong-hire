"""LLM tracing for interview sessions (LT-3, LT-6, LT-14, docs/llm-tracing/spec.md).

The sim marks the sessions it creates with three headers:

    X-Sim-Run: <the sim run id>           groups the run's sessions into one MLflow run
    X-Sim-Scenario: <the scenario id>
    X-Sim-Trace-Content: full | redacted  full only for a fixture persona (D-6)

They are stored in sessions.trace_json only when the session belongs to the sim org; for anyone
else they are ignored. An invalid value stores the safe default (redacted, no run).

Each text turn runs inside the session's trace context as one `turn` span. Whether there is a
trace at all is strong_core.tracing.sessions.trace_tags_for()'s rule: sim sessions, and real
users' sessions once production tracing is on (metadata only, LT-17).

For a real user who gave tracing consent (LT-21), the turn's text also goes into its own
`turn.content` trace when the turn ends: the candidate's answer and the interviewer's reply, from
the turns (never the prompt messages), scrubbed of the user's name, companies, emails and phones.
Consent is read again at that moment, so turning it off stops content from the next turn (LT-24).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import InterviewSession
from strong_core.schemas import SessionTraceSettings, Speaker, Turn
from strong_core.sim import is_sim_org
from strong_core.tracing import SpanHandle, TraceTags, record_turn_content, turn_span
from strong_core.tracing.scrub import Scrubber
from strong_core.tracing.sessions import maybe_trace, trace_tags_for, turn_content_allowed

log = logging.getLogger(__name__)

SIM_RUN_HEADER = "x-sim-run"
SIM_SCENARIO_HEADER = "x-sim-scenario"
SIM_CONTENT_HEADER = "x-sim-trace-content"


async def sim_trace_settings(
    request: Request, db: AsyncSession, org_id: uuid.UUID
) -> dict[str, Any] | None:
    """The trace settings to store on a new session (LT-14), or None for everyone but the sim."""
    run = request.headers.get(SIM_RUN_HEADER, "").strip()
    scenario = request.headers.get(SIM_SCENARIO_HEADER, "").strip()
    content = request.headers.get(SIM_CONTENT_HEADER, "").strip().lower()
    if not (run or scenario or content):
        return None
    if not await is_sim_org(db, org_id):
        return None
    try:
        settings = SessionTraceSettings(
            sim_run_id=run or None,
            scenario=scenario or None,
            content=content or "redacted",  # validated by the contract
        )
    except ValidationError:
        settings = SessionTraceSettings()
    return settings.model_dump(mode="json")


def _turn_counts(request: Request) -> dict[uuid.UUID, int]:
    counts: dict[uuid.UUID, int] | None = getattr(request.app.state, "text_turn_index", None)
    if counts is None:
        counts = {}
        request.app.state.text_turn_index = counts
    return counts


def next_turn_index(request: Request, session_id: uuid.UUID) -> int:
    """0 for the greeting, then 1, 2, ... for each text turn of this process's runner."""
    counts = _turn_counts(request)
    index = counts.get(session_id, -1) + 1
    counts[session_id] = index
    return index


def forget_turns(request: Request, session_id: uuid.UUID) -> None:
    _turn_counts(request).pop(session_id, None)


@dataclass
class TextTurn:
    """What one text turn said, for its content trace (LT-21). The router sets `interviewer`."""

    handle: SpanHandle
    candidate: str = ""
    interviewer: str = ""
    tags: TraceTags | None = field(default=None, repr=False)

    def replies(self, turns: Iterable[Turn]) -> None:
        self.interviewer = " ".join(t.text for t in turns if t.speaker == Speaker.INTERVIEWER)


@asynccontextmanager
async def traced_text_turn(
    db: AsyncSession, session: InterviewSession, index: int, candidate: str = ""
) -> AsyncIterator[TextTurn]:
    """One text turn as a `turn` span in the session's trace context (LT-6), when traced, and its
    scrubbed text as a `turn.content` trace when the user consented (LT-21)."""
    tags = await trace_tags_for(org_id=session.org_id, session_id=session.id, service="api", db=db)
    with maybe_trace(tags), turn_span("text", index) as handle:
        turn = TextTurn(handle=handle, candidate=candidate, tags=tags)
        yield turn
    await _record_content(db, session, index, turn)


async def _record_content(
    db: AsyncSession, session: InterviewSession, index: int, turn: TextTurn
) -> None:
    """Never raises, never blocks the reply on a failure (LT-31)."""
    tags = turn.tags
    if tags is None or not tags.turn_content or not (turn.interviewer or turn.candidate):
        return
    try:
        if not await turn_content_allowed(session.org_id, db):
            return
        scrubber = await Scrubber.for_org(db, session.org_id)
        record_turn_content(tags, index, "text", turn.interviewer, turn.candidate, scrubber.scrub)
    except Exception:
        log.warning("could not keep the content of turn %d of %s", index, session.id)
