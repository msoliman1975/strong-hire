"""Job context: whose model calls a job makes, and the ids on its log lines (OB-2, OB-7).

    @job_context(session_arg="session_id")
    async def score_session(ctx, session_id: str, org_id: str) -> dict: ...

Inside the job every gateway call writes a usage_events row for `org_id` (and the session,
when the job has one), and log lines carry the Arq job id as request_id and the session id.

A job with a session is also one LLM trace named after the job (LT-7), but only when tracing is on
and the session is the sim user's (or a local dev session with LLM_TRACING_DEV=on; LT-3).
"""

from __future__ import annotations

import functools
import inspect
import uuid
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from typing import Any, TypeVar

from strong_core.gateway import usage_context
from strong_core.ops.logs import log_context
from strong_core.tracing import span
from strong_core.tracing.sessions import maybe_trace, trace_tags_for

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


def job_context(*, org_arg: str = "org_id", session_arg: str | None = None) -> Callable[[F], F]:
    def decorate(fn: F) -> F:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                bound = signature.bind_partial(*args, **kwargs).arguments
            except TypeError:
                return await fn(*args, **kwargs)  # let the call fail as it would
            ctx = args[0] if args else bound.get("ctx")
            org_id = _uuid(bound.get(org_arg))
            session_id = _uuid(bound.get(session_arg)) if session_arg else None
            job_id = ctx.get("job_id") if isinstance(ctx, dict) else None
            tags = None
            if org_id is not None and session_id is not None:  # LT-3, LT-7
                tags = await trace_tags_for(org_id=org_id, session_id=session_id, service="worker")
            with ExitStack() as stack:
                stack.enter_context(
                    log_context(request_id=str(job_id) if job_id else None, session_id=session_id)
                )
                if org_id is not None:
                    stack.enter_context(usage_context(org_id, session_id=session_id))
                stack.enter_context(maybe_trace(tags))
                stack.enter_context(span(fn.__name__, "TASK", {"job_id": job_id}))
                return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate
