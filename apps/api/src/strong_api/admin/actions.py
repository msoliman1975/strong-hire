"""Admin write actions (AA-5, AA-6).

Every route that changes something:

- depends on `AdminWrite`, which is `Admin` plus the `X-Admin-Request: 1` header (CSRF defense on
  top of SameSite cookies; 403 without it),
- takes a body that extends `ActionIn`, so it carries a required free-text `reason`,
- calls `audit_action(...)` in the same transaction as the change, with the state before and after.

    @router.post("/users/{user_id}/suspend")
    async def suspend(user_id: uuid.UUID, body: SuspendIn, admin: AdminWrite, db: DbSession):
        ...
        audit_action(db, admin, "user.suspend", f"user:{user.id}", org_id=user.org_id,
                     reason=body.reason, before={...}, after={...})
        await db.commit()
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin.deps import require_admin
from strong_core.db.models import AuditLog, User

ADMIN_REQUEST_HEADER = "X-Admin-Request"


async def require_admin_write(
    admin: Annotated[User, Depends(require_admin)],
    x_admin_request: Annotated[str | None, Header(alias=ADMIN_REQUEST_HEADER)] = None,
) -> User:
    """The admin, for a write. The admin check runs first, so non-admins still get 404."""
    if x_admin_request != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{ADMIN_REQUEST_HEADER}: 1 is required")
    return admin


AdminWrite = Annotated[User, Depends(require_admin_write)]


class ActionIn(BaseModel):
    """Base for admin write bodies: the reason is required and saved in the audit log."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500, description="Why, for the audit log")


def audit_action(
    db: AsyncSession,
    admin: User,
    action: str,
    entity: str,
    *,
    reason: str,
    org_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add the audit row for an admin action. The caller commits it with the change."""
    row = AuditLog(
        org_id=org_id,
        actor=admin.email,
        action=action,
        entity=entity,
        details_json={
            "reason": reason,
            "before": before,
            "after": after,
            **(details or {}),
        },
    )
    db.add(row)
    return row
