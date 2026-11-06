"""Which sessions are traced, and how (LT-3, LT-7, LT-14, D-1, D-6).

One rule for the api, the worker and the voice agent:

- tracing must be active (LLM_TRACING=on, a tracking URI, a real profile; LT-1). Otherwise this
  returns None at once, with no database read;
- a session of the sim org is traced with the settings the sim stored in sessions.trace_json
  (LT-14), redacted when they are missing or invalid;
- any other session is traced only with LLM_TRACING_DEV=on (a developer's machine; the servers
  force it off), always redacted, in the dev experiment;
- everything else is not traced. A real user's session is never traced in phase 1.

    tags = await trace_tags_for(org_id=s.org_id, session_id=s.id, service="api", db=db)
    with maybe_trace(tags), usage_context(s.org_id, s.id):
        ...
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.schemas.tracing import SessionTraceSettings
from strong_core.tracing import TraceTags, is_active, trace_context, warn_once

DEV_EXPERIMENT = "dev"


def parse_trace_settings(value: Any) -> SessionTraceSettings:
    """sessions.trace_json as a contract; anything missing or invalid means redacted (D-6)."""
    if not isinstance(value, dict):
        return SessionTraceSettings()
    try:
        return SessionTraceSettings.model_validate(value)
    except ValidationError:
        return SessionTraceSettings()


@asynccontextmanager
async def _session(db: AsyncSession | None) -> AsyncIterator[AsyncSession]:
    if db is not None:
        yield db
        return
    from strong_core.db.engine import get_sessionmaker

    async with get_sessionmaker()() as own:
        yield own


async def trace_tags_for(
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID | None,
    service: str,
    db: AsyncSession | None = None,
) -> TraceTags | None:
    """The trace tags for work on this org's session, or None when it must not be traced.

    Never raises: a failed lookup means no tracing.
    """
    if not is_active():
        return None
    try:
        from strong_core.config import get_settings
        from strong_core.db.models import InterviewSession
        from strong_core.ops.heartbeat import release
        from strong_core.sim import is_sim_org

        settings = get_settings()
        async with _session(db) as s:
            sim = await is_sim_org(s, org_id)
            stored: Any = None
            if sim and session_id is not None:
                row = await s.get(InterviewSession, session_id)
                if row is not None and row.org_id == org_id:
                    stored = row.trace_json
        common: dict[str, Any] = {
            "session_id": str(session_id) if session_id is not None else None,
            "service": service,
            "release": release(),
            "model_profile": settings.model_profile.value,
        }
        if sim:
            ts = parse_trace_settings(stored)
            return TraceTags(
                **common, sim_run_id=ts.sim_run_id, scenario=ts.scenario, content=ts.content
            )
        if settings.llm_tracing_dev:
            return TraceTags(**common, content="redacted", experiment=DEV_EXPERIMENT)
        return None
    except Exception:
        warn_once("tracing: could not decide whether a session is traced")
        return None


def maybe_trace(tags: TraceTags | None) -> AbstractContextManager[Any]:
    """trace_context(tags), or a no-op when tags is None."""
    if tags is None:
        return nullcontext()
    return trace_context(tags)


__all__ = ["DEV_EXPERIMENT", "maybe_trace", "parse_trace_settings", "trace_tags_for"]
