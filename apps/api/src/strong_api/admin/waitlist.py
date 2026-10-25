"""Admin Waitlist (L04): who is waiting for sign-ups to open.

    GET /admin/waitlist        counts and every entry, newest first
    GET /admin/waitlist.csv    the same entries as a CSV file, for invites and email tools

Read-only. Invites go out by hand until sign-ups open.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select

from strong_api.admin.deps import Admin
from strong_api.auth.deps import DbSession
from strong_core.db.models import WaitlistEntry
from strong_core.schemas.enums import InterviewWithin, RoleFamily

router = APIRouter(prefix="/admin", tags=["admin"])

CSV_COLUMNS = (
    "email",
    "interview_within",
    "role_family",
    "marketing_consent",
    "source",
    "confirmed_at",
    "invited_at",
    "created_at",
)


class AdminWaitlistEntry(BaseModel):
    id: uuid.UUID
    email: str
    interview_within: InterviewWithin
    role_family: RoleFamily | None
    marketing_consent: bool
    source: str | None
    confirmed_at: datetime | None
    invited_at: datetime | None
    created_at: datetime


class AdminWaitlist(BaseModel):
    total: int
    confirmed: int
    marketing_consent: int
    entries: list[AdminWaitlistEntry]


async def _entries(db: DbSession) -> list[WaitlistEntry]:
    rows = await db.scalars(select(WaitlistEntry).order_by(WaitlistEntry.created_at.desc()))
    return list(rows)


@router.get("/waitlist", response_model=AdminWaitlist)
async def list_waitlist(_admin: Admin, db: DbSession) -> AdminWaitlist:
    rows = await _entries(db)
    return AdminWaitlist(
        total=len(rows),
        confirmed=sum(1 for r in rows if r.confirmed_at is not None),
        marketing_consent=sum(1 for r in rows if r.marketing_consent),
        entries=[AdminWaitlistEntry.model_validate(r, from_attributes=True) for r in rows],
    )


@router.get("/waitlist.csv", response_class=Response)
async def export_waitlist(_admin: Admin, db: DbSession) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for r in await _entries(db):
        writer.writerow(
            [
                r.email,
                r.interview_within.value,
                r.role_family.value if r.role_family else "",
                "yes" if r.marketing_consent else "no",
                r.source or "",
                r.confirmed_at.isoformat() if r.confirmed_at else "",
                r.invited_at.isoformat() if r.invited_at else "",
                r.created_at.isoformat(),
            ]
        )
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="waitlist.csv"'},
    )
