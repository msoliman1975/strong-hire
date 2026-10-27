"""Admin Waitlist (L04): who is waiting for sign-ups to open.

    GET  /admin/waitlist          counts and every entry, newest first
    GET  /admin/waitlist.csv      the same entries as a CSV file, for email tools
    POST /admin/waitlist/invite   email the chosen entries that they can sign up now

An invite goes only to confirmed entries (double opt-in) and only while sign-ups are open (OC-1).
Each person gets their own email, and `invited_at` records the last invite sent. The write follows
AA-5/AA-6: AdminWrite, a reason and one audit row for the batch.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin
from strong_api.auth.deps import DbSession
from strong_api.controls import signups_paused
from strong_api.public import Waitlist
from strong_core.db.models import WaitlistEntry
from strong_core.schemas.enums import InterviewWithin, RoleFamily

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_INVITES = 500
PARALLEL_SENDS = 5

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


class InviteIn(ActionIn):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_INVITES)


class InviteOut(BaseModel):
    sent: list[str] = Field(description="Emails that got the invite")
    skipped: list[str] = Field(description="Not confirmed yet, so not invited")
    failed: list[str] = Field(description="The email could not be sent; try again later")


def _invite(signin_url: str) -> tuple[str, str]:
    return "Strong Hire is ready for you", (
        "You joined the Strong Hire waitlist, and your place has come up: you can create your "
        f"account now.\n\n{signin_url}\n\n"
        "Sign in with the email this message was sent to. You get this email because you asked "
        "to hear when Strong Hire opens."
    )


@router.post("/waitlist/invite", response_model=InviteOut)
async def invite_waitlist(
    body: InviteIn, admin: AdminWrite, db: DbSession, request: Request
) -> InviteOut:
    if await signups_paused(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Sign-ups are paused. Open them on Controls first."
        )
    rows = list(await db.scalars(select(WaitlistEntry).where(WaitlistEntry.id.in_(body.ids))))
    ready = [r for r in rows if r.confirmed_at is not None]
    skipped = sorted(r.email for r in rows if r.confirmed_at is None)

    waitlist: Waitlist = request.app.state.waitlist
    subject, text = _invite(f"{waitlist.web_base_url.rstrip('/')}/signin?utm_source=waitlist")
    gate = asyncio.Semaphore(PARALLEL_SENDS)

    async def send(email: str) -> None:
        async with gate:
            await waitlist.email_sender.send(email, subject, text)

    results = await asyncio.gather(*(send(r.email) for r in ready), return_exceptions=True)
    now = datetime.now(UTC)
    sent: list[str] = []
    failed: list[str] = []
    for row, result in zip(ready, results, strict=True):
        if isinstance(result, BaseException):
            log.error("waitlist invite to %s failed: %s", row.email, result)
            failed.append(row.email)
        else:
            row.invited_at = now
            sent.append(row.email)
    out = InviteOut(sent=sorted(sent), skipped=skipped, failed=sorted(failed))

    audit_action(
        db, admin, "waitlist.invite", "waitlist", reason=body.reason, details=out.model_dump()
    )
    await db.commit()
    return out
