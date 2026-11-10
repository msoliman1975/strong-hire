"""Ask the worker to delete an org's production LLM traces (LT-24, LT-25, D-18).

Account deletion asks for scope "all"; turning tracing consent off asks for scope "content". The
request is an audit row (`tracing.delete_requested`, with the request id) next to the queued job,
so the "Trace deletion overdue" alert can find a request that never finished (LT-26). Audit rows
outlive the account.

Nothing is queued while tracing is not set up (LLM_TRACING off or no tracking URI): there is no
MLflow to reach, and a job would only fail and raise the alert. Turn tracing off only after its
traces are gone (docs/hosting.md, "LLM tracing (MLflow)").
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.inputs.queue import JobQueue
from strong_core.config import get_settings
from strong_core.db.models import AuditLog

# Names in strong_worker.account.jobs; a test checks they stay in sync.
DELETE_TRACES = "delete_traces"
TRACES_REQUESTED = "tracing.delete_requested"

Scope = Literal["all", "content"]


def tracing_configured() -> bool:
    settings = get_settings()
    return bool(settings.llm_tracing and settings.mlflow_tracking_uri)


async def request_trace_deletion(
    db: AsyncSession, queue: JobQueue, org_id: uuid.UUID, scope: Scope, actor: str
) -> str | None:
    """Queue the deletion and record the request. Returns the request id, or None when tracing is
    not set up. The caller commits."""
    if not tracing_configured():
        return None
    request_id = f"delete-traces:{scope}:{org_id}:{uuid.uuid4().hex[:12]}"
    db.add(
        AuditLog(
            org_id=org_id,
            actor=actor,
            action=TRACES_REQUESTED,
            entity=f"org:{org_id}",
            details_json={"scope": scope, "request_id": request_id},
        )
    )
    await queue.enqueue(
        DELETE_TRACES, request_id, org_id=str(org_id), scope=scope, request_id=request_id
    )
    return request_id
