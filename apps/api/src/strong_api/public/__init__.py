"""Public routes that need no account (L04). Today: the waitlist.

    POST /public/waitlist           join, or update an entry; always answers 202 "check_email"
    POST /public/waitlist/confirm   double opt-in: the signed link from the email

The answer to a join never says whether the email was already on the list. A filled honeypot
field is accepted and dropped. Joins are limited per client address.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from strong_api.auth.deps import DbSession
from strong_api.auth.magic_links import InvalidMagicLinkError, MagicLinks, RedisUsedTokenStore
from strong_api.auth.settings import AuthSettings, get_auth_settings
from strong_core.config import get_settings
from strong_core.db.models import WaitlistEntry
from strong_core.email import EmailSender, make_email_sender
from strong_core.schemas.enums import InterviewWithin, RoleFamily

log = logging.getLogger(__name__)

WAITLIST_LINK_SALT = "strong-hire-waitlist"
LINK_MAX_AGE_S = 7 * 24 * 3600
JOINS_PER_HOUR = 5


class WaitlistIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr = Field(max_length=320)
    interview_within: InterviewWithin
    role_family: RoleFamily | None = None
    marketing_consent: bool = False
    source: str | None = Field(default=None, max_length=100, description="utm_source, if any")
    website: str | None = Field(
        default=None, max_length=200, description="Honeypot: hidden in the form, left empty"
    )


class WaitlistOut(BaseModel):
    status: Literal["check_email"] = "check_email"


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=2000)


class ConfirmOut(BaseModel):
    status: Literal["confirmed"] = "confirmed"


class JoinLimiter:
    """At most `limit` joins per key (client address) per hour, in this process."""

    def __init__(self, limit: int = JOINS_PER_HOUR, window_s: float = 3600) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] < now - self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


@dataclass
class Waitlist:
    links: MagicLinks
    email_sender: EmailSender
    limiter: JoinLimiter
    web_base_url: str


def _confirmation(link: str) -> tuple[str, str]:
    return "Confirm your place on the Strong Hire waitlist", (
        "Thanks for joining the Strong Hire waitlist. Open this link to confirm your email. "
        f"It works for 7 days.\n\n{link}\n\n"
        "We'll write when sign-ups open. If you did not ask for this, ignore this email and "
        "we won't contact you."
    )


router = APIRouter(prefix="/public", tags=["public"])


def _waitlist(request: Request) -> Waitlist:
    waitlist: Waitlist = request.app.state.waitlist
    return waitlist


@router.post("/waitlist", status_code=status.HTTP_202_ACCEPTED, response_model=WaitlistOut)
async def join_waitlist(body: WaitlistIn, request: Request, db: DbSession) -> WaitlistOut:
    waitlist = _waitlist(request)
    if body.website:
        return WaitlistOut()  # a bot filled the hidden field
    client = request.client.host if request.client else "unknown"
    if not waitlist.limiter.allow(client):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Try later.")

    email = str(body.email).strip().lower()
    entry = await db.scalar(select(WaitlistEntry).where(WaitlistEntry.email == email))
    if entry is None:
        entry = WaitlistEntry(email=email, source=body.source)
        db.add(entry)
    entry.interview_within = body.interview_within
    entry.role_family = body.role_family
    entry.marketing_consent = body.marketing_consent
    await db.commit()

    if entry.confirmed_at is None:
        token = waitlist.links.issue(email)
        link = f"{waitlist.web_base_url.rstrip('/')}/waitlist/confirm?token={token}"
        subject, text = _confirmation(link)
        try:
            await waitlist.email_sender.send(email, subject, text)
        except Exception:
            # The entry is saved; joining again sends a new link.
            log.exception("waitlist confirmation email failed")
    return WaitlistOut()


@router.post("/waitlist/confirm", response_model=ConfirmOut)
async def confirm_waitlist(body: ConfirmIn, request: Request, db: DbSession) -> ConfirmOut:
    try:
        data = _waitlist(request).links.peek(body.token)
    except InvalidMagicLinkError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_link") from exc
    entry = await db.scalar(select(WaitlistEntry).where(WaitlistEntry.email == data["email"]))
    if entry is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_link")
    if entry.confirmed_at is None:
        entry.confirmed_at = datetime.now(UTC)
        await db.commit()
    return ConfirmOut()


def install_public(
    app: FastAPI,
    settings: AuthSettings | None = None,
    *,
    email_sender: EmailSender | None = None,
    links: MagicLinks | None = None,
    limiter: JoinLimiter | None = None,
) -> None:
    settings = settings or get_auth_settings()
    app.state.waitlist = Waitlist(
        links=links
        or MagicLinks(
            settings.session_secret,
            LINK_MAX_AGE_S,
            RedisUsedTokenStore(get_settings().redis_url),
            salt=WAITLIST_LINK_SALT,
        ),
        email_sender=email_sender or make_email_sender(),
        limiter=limiter or JoinLimiter(),
        web_base_url=settings.web_base_url,
    )
    app.include_router(router)
