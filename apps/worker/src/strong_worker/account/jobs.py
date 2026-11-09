"""Arq jobs for account self-service (AC-1). The API enqueues them (strong_api.account).

- export_account: build the zip bundle and keep it in Redis for one download.
- delete_account_files: delete the original resume files of a deleted account. On a storage
  error it asks Arq to retry (up to DELETE_MAX_TRIES, about 7.5 hours in all, inside the 24-hour
  promise); the account rows are already gone.
- delete_traces: delete an org's production LLM traces from MLflow (LT-24 to LT-26): scope
  "content" when tracing consent is withdrawn, "all" when the account is deleted. Same retries.
  The API writes `tracing.delete_requested` when it queues the job; this job writes
  `tracing.traces_deleted` with the same request id. A request still without its success after
  12 hours raises the "Trace deletion overdue" alert (strong_worker.alerts.readings).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import AuditLog
from strong_core.tracing.prod import Scope, delete_org_traces
from strong_worker.account.bundle import ExportTooLargeError, build_bundle
from strong_worker.inputs.settings import get_inputs_settings
from strong_worker.inputs.storage import FileStore, build_file_store

log = logging.getLogger(__name__)

CTX_KEY = "account"
RESULT_TTL_S = 24 * 3600
DELETE_MAX_TRIES = 10
RETRY_DELAY_S = 600


def export_key(org_id: uuid.UUID | str, export_id: uuid.UUID | str) -> str:
    """Must match strong_api.account.exports.export_key (a test checks this)."""
    return f"account:export:{org_id}:{export_id}"


class ExportWriter(Protocol):
    async def put(self, key: str, data: bytes, ttl_s: int) -> None: ...


class RedisExportWriter:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def put(self, key: str, data: bytes, ttl_s: int) -> None:
        await self._redis.set(key, data, ex=ttl_s)


@dataclass
class AccountContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    store: FileStore
    exports: ExportWriter


async def startup(ctx: dict[str, Any]) -> None:
    ctx[CTX_KEY] = AccountContext(
        sessionmaker=get_sessionmaker(),
        store=build_file_store(get_inputs_settings()),
        exports=RedisExportWriter(ctx["redis"]),
    )


def _account(ctx: dict[str, Any]) -> AccountContext:
    account = ctx[CTX_KEY]
    assert isinstance(account, AccountContext)
    return account


async def export_account(
    ctx: dict[str, Any],
    org_id: str,
    user_id: str,
    export_id: str,
    ttl_s: int,
    max_bytes: int,
) -> dict[str, Any]:
    account = _account(ctx)
    async with account.sessionmaker() as db:
        try:
            bundle, summary = await build_bundle(
                db, account.store, uuid.UUID(org_id), uuid.UUID(user_id), max_bytes
            )
        except ExportTooLargeError as exc:
            return {"outcome": "failed", "reason": str(exc)}
    await account.exports.put(export_key(org_id, export_id), bundle, ttl_s)
    return {"outcome": "ready", **summary}


async def delete_account_files(ctx: dict[str, Any], org_id: str, refs: list[str]) -> dict[str, Any]:
    account = _account(ctx)
    try:
        for ref in refs:
            await account.store.delete(ref)  # a missing file is not an error
    except Exception as exc:
        job_try = int(ctx.get("job_try", 1))
        log.warning("file delete for org %s failed (try %d): %s", org_id, job_try, exc)
        if job_try < DELETE_MAX_TRIES:
            raise Retry(defer=RETRY_DELAY_S * job_try) from exc
        raise
    async with account.sessionmaker() as db:
        db.add(
            AuditLog(
                org_id=uuid.UUID(org_id),
                actor="system",
                action="account.files_deleted",
                entity=f"org:{org_id}",
                details_json={"files": len(refs)},
            )
        )
        await db.commit()
    log.info("deleted %d files of org %s", len(refs), org_id)
    return {"outcome": "deleted", "files": len(refs)}


TRACES_REQUESTED = "tracing.delete_requested"
TRACES_DELETED = "tracing.traces_deleted"
TRACE_SCOPES: tuple[Scope, ...] = ("all", "content")


async def delete_traces(
    ctx: dict[str, Any], org_id: str, scope: str, request_id: str
) -> dict[str, Any]:
    """Delete the org's production traces (LT-24, LT-25), retried on any MLflow error (LT-26)."""
    if scope not in TRACE_SCOPES:
        raise ValueError(f"unknown trace scope {scope!r}")
    checked: Scope = "all" if scope == "all" else "content"
    account = _account(ctx)
    try:
        count = await asyncio.to_thread(delete_org_traces, uuid.UUID(org_id), checked)
    except Exception as exc:
        job_try = int(ctx.get("job_try", 1))
        log.warning("trace delete for org %s failed (try %d): %s", org_id, job_try, exc)
        if job_try < DELETE_MAX_TRIES:
            raise Retry(defer=RETRY_DELAY_S * job_try) from exc
        raise
    async with account.sessionmaker() as db:
        db.add(
            AuditLog(
                org_id=uuid.UUID(org_id),
                actor="system",
                action=TRACES_DELETED,
                entity=f"org:{org_id}",
                details_json={"scope": scope, "request_id": request_id, "traces": count},
            )
        )
        await db.commit()
    log.info("deleted %d %s traces of org %s", count, scope, org_id)
    return {"outcome": "deleted", "scope": scope, "traces": count}


FUNCTIONS = (export_account, delete_account_files, delete_traces)
