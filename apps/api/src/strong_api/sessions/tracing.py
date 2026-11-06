"""LLM tracing for interview sessions (LT-3, LT-6, LT-14, docs/llm-tracing/spec.md).

The sim marks the sessions it creates with three headers:

    X-Sim-Run: <the sim run id>           groups the run's sessions into one MLflow run
    X-Sim-Scenario: <the scenario id>
    X-Sim-Trace-Content: full | redacted  full only for a fixture persona (D-6)

They are stored in sessions.trace_json only when the session belongs to the sim org; for anyone
else they are ignored. An invalid value stores the safe default (redacted, no run).

Each text turn runs inside the session's trace context as one `turn` span. Whether there is a trace
at all is strong_core.tracing.sessions.trace_tags_for()'s rule: sim sessions only, and only with
tracing on.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import InterviewSession
from strong_core.schemas import SessionTraceSettings
from strong_core.sim import is_sim_org
from strong_core.tracing import SpanHandle, turn_span
from strong_core.tracing.sessions import maybe_trace, trace_tags_for

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


@asynccontextmanager
async def traced_text_turn(
    db: AsyncSession, session: InterviewSession, index: int
) -> AsyncIterator[SpanHandle]:
    """One text turn as a `turn` span in the session's trace context (LT-6), when traced."""
    tags = await trace_tags_for(org_id=session.org_id, session_id=session.id, service="api", db=db)
    with maybe_trace(tags), turn_span("text", index) as handle:
        yield handle
