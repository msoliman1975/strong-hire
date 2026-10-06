"""Account endpoints: training-data consent (AC-2), export and delete (AC-1).

PUT    /account/consent                    change the consent; each change goes to AuditLog
POST   /account/export                     start an export (background job)
GET    /account/export/{id}                export status
GET    /account/export/{id}/download       the zip bundle; works once
DELETE /account                            delete the account and all its data
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from strong_api.account.deletion import (
    BACKUP_RETENTION_DAYS,
    DELETE_DEADLINE_HOURS,
    delete_org_rows,
    redact_audit_actor,
    resume_file_refs,
)
from strong_api.account.exports import ExportStore, export_job_id, export_key
from strong_api.account.schemas import (
    AccountDeletedOut,
    ConsentIn,
    ConsentOut,
    ExportOut,
    ExportStatus,
)
from strong_api.account.settings import AccountSettings
from strong_api.auth import CurrentUser
from strong_api.auth.deps import DbSession
from strong_api.auth.settings import AuthSettings
from strong_api.billing.entitlements import get_subscription
from strong_api.billing.router import Stripe
from strong_api.inputs.deps import Queue
from strong_core.db.models import AuditLog

log = logging.getLogger(__name__)

# Names of the Arq functions in strong_worker.account.jobs. A test checks they stay in sync.
EXPORT_ACCOUNT = "export_account"
DELETE_ACCOUNT_FILES = "delete_account_files"


def export_store(request: Request) -> ExportStore:
    store: ExportStore = request.app.state.export_store
    return store


def account_settings(request: Request) -> AccountSettings:
    settings: AccountSettings = request.app.state.account_settings
    return settings


Exports = Annotated[ExportStore, Depends(export_store)]
Settings = Annotated[AccountSettings, Depends(account_settings)]


def _actor(user_id: uuid.UUID) -> str:
    return f"user:{user_id}"


def build_router(auth_settings: AuthSettings) -> APIRouter:
    router = APIRouter(prefix="/account", tags=["account"])
    api_base = auth_settings.api_public_url.rstrip("/")

    @router.put("/consent")
    async def set_consent(db: DbSession, user: CurrentUser, body: ConsentIn) -> ConsentOut:
        """AC-2: training-data consent, off by default, changeable at any time."""
        if user.training_consent != body.training_consent:
            db.add(
                AuditLog(
                    org_id=user.org_id,
                    actor=_actor(user.id),
                    action="account.consent_changed",
                    entity=f"user:{user.id}",
                    details_json={
                        "training_consent_from": user.training_consent,
                        "training_consent_to": body.training_consent,
                    },
                )
            )
            user.training_consent = body.training_consent
            await db.commit()
        return ConsentOut(training_consent=user.training_consent)

    async def _export_request(db: DbSession, user: CurrentUser, export_id: str) -> AuditLog:
        try:
            uuid.UUID(export_id)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found") from None
        row = await db.scalar(
            select(AuditLog).where(
                AuditLog.org_id == user.org_id,
                AuditLog.action == "account.export_requested",
                AuditLog.entity == f"export:{export_id}",
            )
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found")
        return row

    async def _export_out(
        user: CurrentUser, export_id: str, requested_at: datetime, queue: Queue, store: Exports
    ) -> ExportOut:
        info = await queue.info(export_job_id(user.org_id, export_id))
        key = export_key(user.org_id, export_id)
        error: str | None = None
        state: ExportStatus
        if info.status in ("queued", "in_progress"):
            state = "preparing"
        elif info.status == "complete" and (info.result or {}).get("outcome") == "ready":
            if await store.exists(key):
                state = "ready"
            else:
                state = "downloaded" if await store.was_downloaded(key) else "expired"
        elif info.status == "complete" or info.status == "failed":
            state = "failed"
            error = str((info.result or {}).get("reason") or info.error or "The export failed.")
        else:
            state = "downloaded" if await store.was_downloaded(key) else "expired"
        return ExportOut(
            id=export_id,
            status=state,
            requested_at=requested_at,
            download_url=(
                f"{api_base}/account/export/{export_id}/download" if state == "ready" else None
            ),
            error=error,
        )

    @router.post("/export", status_code=status.HTTP_202_ACCEPTED)
    async def start_export(
        db: DbSession, user: CurrentUser, queue: Queue, store: Exports, settings: Settings
    ) -> ExportOut:
        """AC-1: prepare a zip of all the user's data and original resume files."""
        export_id = str(uuid.uuid4())
        entry = AuditLog(
            org_id=user.org_id,
            actor=_actor(user.id),
            action="account.export_requested",
            entity=f"export:{export_id}",
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        await queue.enqueue(
            EXPORT_ACCOUNT,
            export_job_id(user.org_id, export_id),
            org_id=str(user.org_id),
            user_id=str(user.id),
            export_id=export_id,
            ttl_s=settings.account_export_ttl_s,
            max_bytes=settings.account_export_max_mb * 1024 * 1024,
        )
        return await _export_out(user, export_id, entry.at, queue, store)

    @router.get("/export/{export_id}")
    async def get_export(
        export_id: str, db: DbSession, user: CurrentUser, queue: Queue, store: Exports
    ) -> ExportOut:
        entry = await _export_request(db, user, export_id)
        return await _export_out(user, export_id, entry.at, queue, store)

    @router.get(
        "/export/{export_id}/download",
        response_class=Response,
        responses={200: {"content": {"application/zip": {}}}, 410: {"description": "Gone"}},
    )
    async def download_export(
        export_id: str, db: DbSession, user: CurrentUser, store: Exports
    ) -> Response:
        """The export bundle. The first download deletes it from the server."""
        await _export_request(db, user, export_id)
        data = await store.take(export_key(user.org_id, export_id))
        if data is None:
            raise HTTPException(
                status.HTTP_410_GONE,
                {
                    "code": "export_gone",
                    "message": "This export was downloaded already or has expired.",
                },
            )
        key = export_key(user.org_id, export_id)
        await store.mark_downloaded(key)
        db.add(
            AuditLog(
                org_id=user.org_id,
                actor=_actor(user.id),
                action="account.export_downloaded",
                entity=f"export:{export_id}",
                details_json={"bytes": len(data)},
            )
        )
        await db.commit()
        day = datetime.now(UTC).strftime("%Y%m%d")
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="strong-hire-export-{day}.zip"',
                "Cache-Control": "no-store",
            },
        )

    @router.delete("", status_code=status.HTTP_202_ACCEPTED)
    async def delete_account(
        request: Request,
        db: DbSession,
        user: CurrentUser,
        queue: Queue,
        store: Exports,
        stripe: Stripe,
    ) -> AccountDeletedOut:
        """AC-1: delete the account and all its data. Rows go now, files within 24 hours."""
        org_id, user_id, email = user.org_id, user.id, user.email

        # Stop billing first. Deleting the Stripe customer cancels its subscription at once.
        sub = await get_subscription(db, org_id)
        if sub is not None and sub.stripe_customer_id:
            if stripe is None:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    {
                        "code": "billing_not_configured",
                        "message": "We cannot cancel your plan right now. Try again later.",
                    },
                )
            await stripe.delete_customer(sub.stripe_customer_id)

        # Files first: the job only needs the refs, and a file must not outlive its row.
        refs = await resume_file_refs(db, org_id)
        if refs:
            await queue.enqueue(
                DELETE_ACCOUNT_FILES,
                f"delete-files:{org_id}:{uuid.uuid4().hex[:12]}",
                org_id=str(org_id),
                refs=refs,
            )

        result = await delete_org_rows(db, org_id)
        await redact_audit_actor(db, org_id, email, _actor(user_id))
        db.add(
            AuditLog(
                org_id=org_id,
                actor=_actor(user_id),
                action="account.deleted",
                entity=f"user:{user_id}",
                details_json={
                    "rows": result.rows,
                    "files_pending": len(refs),
                    "files_deleted_within_hours": DELETE_DEADLINE_HOURS,
                    "backups_expire_within_days": BACKUP_RETENTION_DAYS,
                },
            )
        )
        await db.commit()
        await store.delete_org(org_id)
        request.session.clear()
        log.info("account %s deleted: %d rows, %d files", user_id, result.total_rows, len(refs))
        return AccountDeletedOut(
            status="deleted",
            rows_deleted=result.total_rows,
            files_pending=len(refs),
            files_deleted_within_hours=DELETE_DEADLINE_HOURS,
            backups_expire_within_days=BACKUP_RETENTION_DAYS,
        )

    return router
