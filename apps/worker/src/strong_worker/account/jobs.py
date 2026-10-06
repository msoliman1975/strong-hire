"""Arq jobs for account self-service (AC-1). The API enqueues them (strong_api.account).

- export_account: build the zip bundle and keep it in Redis for one download.
- delete_account_files: delete the original resume files of a deleted account. On a storage
  error it asks Arq to retry (up to DELETE_MAX_TRIES, about 7.5 hours in all, inside the 24-hour
  promise); the account rows are already gone.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import AuditLog
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


FUNCTIONS = (export_account, delete_account_files)
