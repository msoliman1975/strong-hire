"""Settings > Admins (AA-1, AA-8): who may use the admin app.

    GET    /admin/admins          every admin, active and removed, with live session counts
    POST   /admin/admins          add an admin by email (or turn a removed one back on)
    DELETE /admin/admins/{id}     remove an admin: they cannot sign in, their sessions end

Writes follow AA-5/AA-6 (AdminWrite, a reason, an audit row). An admin cannot remove themselves,
so the app always keeps at least the admin who is using it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin, admin_auth
from strong_api.admin.identity import add_admin, as_utc, disable_admin, session_live
from strong_api.auth.deps import DbSession
from strong_core.db.models import AdminSession as AdminSessionRow
from strong_core.db.models import AdminUser as AdminUserRow

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminAccount(BaseModel):
    id: uuid.UUID
    email: str
    added_by: str | None
    added_at: datetime
    disabled_at: datetime | None
    live_sessions: int


class AddAdminIn(ActionIn):
    email: EmailStr


class RemoveAdminIn(ActionIn):
    pass


def _account(row: AdminUserRow, live: int) -> AdminAccount:
    return AdminAccount(
        id=row.id,
        email=row.email,
        added_by=row.added_by,
        added_at=as_utc(row.added_at),
        disabled_at=as_utc(row.disabled_at) if row.disabled_at else None,
        live_sessions=live,
    )


@router.get("/admins")
async def list_admins(admin: Admin, db: DbSession, request: Request) -> list[AdminAccount]:
    now = admin_auth(request).clock()
    rows = list(await db.scalars(select(AdminUserRow).order_by(AdminUserRow.email)))
    sessions = await db.scalars(select(AdminSessionRow).where(AdminSessionRow.revoked_at.is_(None)))
    live: dict[uuid.UUID, int] = {}
    for s in sessions:
        if session_live(s, now):
            live[s.admin_user_id] = live.get(s.admin_user_id, 0) + 1
    active = [r for r in rows if r.disabled_at is None]
    removed = [r for r in rows if r.disabled_at is not None]
    return [_account(r, live.get(r.id, 0)) for r in (*active, *removed)]


@router.post("/admins", status_code=status.HTTP_201_CREATED)
async def create_admin(body: AddAdminIn, admin: AdminWrite, db: DbSession) -> AdminAccount:
    row, changed = await add_admin(db, str(body.email), added_by=admin.email)
    if not changed:
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already an admin.")
    audit_action(
        db,
        admin,
        "admin.admin_added",
        f"admin_user:{row.id}",
        reason=body.reason,
        before=None,
        after={"email": row.email, "active": True},
    )
    await db.commit()
    return _account(row, 0)


@router.delete("/admins/{admin_id}")
async def remove_admin(
    admin_id: uuid.UUID, body: RemoveAdminIn, admin: AdminWrite, db: DbSession, request: Request
) -> AdminAccount:
    row = await db.get(AdminUserRow, admin_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such admin")
    if row.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove yourself.")
    if row.disabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That admin was already removed.")
    revoked = await disable_admin(db, row, admin_auth(request).clock())
    audit_action(
        db,
        admin,
        "admin.admin_removed",
        f"admin_user:{row.id}",
        reason=body.reason,
        before={"email": row.email, "active": True},
        after={"email": row.email, "active": False},
        details={"sessions_revoked": revoked},
    )
    await db.commit()
    return _account(row, 0)
