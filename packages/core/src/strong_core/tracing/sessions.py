"""Which sessions are traced, and how (LT-3, LT-7, LT-14, D-1, D-6).

One rule for the api, the worker and the voice agent:

- tracing must be active (LLM_TRACING=on, a tracking URI, a real profile; LT-1). Otherwise this
  returns None at once, with no database read;
- a session of the sim org is traced with the settings the sim stored in sessions.trace_json
  (LT-14), redacted when they are missing or invalid;
- any other session is traced only with LLM_TRACING_DEV=on (a developer's machine; the servers
  force it off), always redacted, in the dev experiment;
- phase 2, a real user's session (LT-16 to LT-19): only with LLM_TRACING_PROD=on, the runtime
  setting llm_tracing_paused off, and the session inside LLM_TRACING_SAMPLE. Then metadata tags
  (no text, no hash, LT-17) in the prod experiment, with org_id (LT-18), and turn_content set
  when LLM_TRACING_PROD_CONTENT is on and the user consented (LT-20);
- everything else is not traced. Any error means not traced (LT-31).

    tags = await trace_tags_for(org_id=s.org_id, session_id=s.id, service="api", db=db)
    with maybe_trace(tags), usage_context(s.org_id, s.id):
        ...
"""

from __future__ import annotations

import hashlib
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
        return await _production_tags(db, org_id, session_id, common)
    except Exception:
        warn_once("tracing: could not decide whether a session is traced")
        return None


def in_sample(session_id: uuid.UUID, rate: float) -> bool:
    """LT-19: a stable choice per session, so a session is traced whole or not at all."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.sha256(str(session_id).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


async def _production_tags(
    db: AsyncSession | None,
    org_id: uuid.UUID,
    session_id: uuid.UUID | None,
    common: dict[str, Any],
) -> TraceTags | None:
    """Phase 2: a real user's session (LT-16 to LT-20). None unless every check passes."""
    from strong_core import runtime_settings as rs
    from strong_core.config import get_settings

    settings = get_settings()
    if not settings.llm_tracing_prod or session_id is None:
        return None
    if not in_sample(session_id, settings.llm_tracing_sample):
        return None
    async with _session(db) as s:
        if await rs.get(s, rs.SettingKey.LLM_TRACING_PAUSED):
            return None
        consent = await _consented(s, org_id) if settings.llm_tracing_prod_content else False
    return TraceTags(
        **common,
        content="metadata",
        experiment=settings.mlflow_prod_experiment,
        org_id=str(org_id),
        turn_content=consent,
    )


async def _consented(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Every user of the org has tracing consent on. No users means no."""
    from sqlalchemy import select

    from strong_core.db.models import User

    rows = (await db.execute(select(User.tracing_consent).where(User.org_id == org_id))).all()
    return bool(rows) and all(row[0] for row in rows)


async def turn_content_allowed(org_id: uuid.UUID, db: AsyncSession | None = None) -> bool:
    """Read now, before each turn's content is written, so turning consent off stops content
    from the next turn even mid-session (LT-24). Any error means no (LT-31)."""
    try:
        from strong_core.config import get_settings

        if not get_settings().llm_tracing_prod_content:
            return False
        async with _session(db) as s:
            return await _consented(s, org_id)
    except Exception:
        warn_once("tracing: could not read tracing consent")
        return False


def maybe_trace(tags: TraceTags | None) -> AbstractContextManager[Any]:
    """trace_context(tags), or a no-op when tags is None."""
    if tags is None:
        return nullcontext()
    return trace_context(tags)


__all__ = [
    "DEV_EXPERIMENT",
    "in_sample",
    "maybe_trace",
    "parse_trace_settings",
    "trace_tags_for",
    "turn_content_allowed",
]
