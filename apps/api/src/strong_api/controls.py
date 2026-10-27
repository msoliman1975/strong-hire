"""Ops controls on the candidate side (admin spec OC-1 to OC-4).

The admin app sets them (strong_api.admin.controls); this module enforces them:

- `ensure_signups_open` (OC-1): every path that creates an account calls it. Existing users
  still sign in.
- `ensure_sessions_open` (OC-2, OC-3): creating a session and starting it (the first voice join,
  the text open) call it. A session already in progress is never stopped.
- `GET /status` (OC-4): public. The active site banner and whether sign-ups and new sessions
  are available, for the candidate app, and `custom_interview_access` (CU-11).

Refusals are HTTP 503 with detail {"code", "message"}:
`signups_paused`, `sessions_paused` and `spend_cap_reached`.

Settings come from strong_core.runtime_settings (10 s cache). Today's model cost (the sum of
usage_events.cost_usd since UTC midnight) is cached here for 30 s.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from datetime import time as dtime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core import runtime_settings as rs
from strong_core.db import get_sessionmaker
from strong_core.db.models import UsageEvent
from strong_core.schemas import SessionChannel

SPEND_CACHE_TTL_S = 30.0
RETRY_AFTER_S = 300

SIGNUPS_PAUSED = "signups_paused"
SESSIONS_PAUSED = "sessions_paused"
SPEND_CAP_REACHED = "spend_cap_reached"

MESSAGES = {
    SIGNUPS_PAUSED: (
        "We are not taking new sign-ups right now. Write to support@getstronghire.com to join "
        "the waitlist, and we will email you when we open again."
    ),
    SESSIONS_PAUSED: (
        "New interviews are temporarily unavailable. Please try again in a little while."
    ),
    SPEND_CAP_REACHED: (
        "New interviews are temporarily unavailable. Please try again in a little while."
    ),
}


class ControlRefusedError(HTTPException):
    """HTTP 503 for a paused feature, with detail {"code", "message"}."""

    def __init__(self, code: str) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": code, "message": MESSAGES[code]},
            headers={"Retry-After": str(RETRY_AFTER_S)},
        )
        self.code = code


# --- today's spend (OC-3) ---------------------------------------------------------------

_spend_cache: tuple[float, datetime, Decimal] | None = None


def clear_spend_cache() -> None:
    global _spend_cache
    _spend_cache = None


def utc_midnight(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return datetime.combine(now.astimezone(UTC).date(), dtime.min, tzinfo=UTC)


async def spend_today_usd(db: AsyncSession) -> Decimal:
    """Model cost since UTC midnight (usage_events.cost_usd), cached for 30 s."""
    global _spend_cache
    now = time.monotonic()
    midnight = utc_midnight()
    if (
        _spend_cache is not None
        and now - _spend_cache[0] < SPEND_CACHE_TTL_S
        and _spend_cache[1] == midnight
    ):
        return _spend_cache[2]
    total = await db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.created_at >= midnight
        )
    )
    value = Decimal(str(total or 0))
    _spend_cache = (now, midnight, value)
    return value


async def spend_cap_reached(db: AsyncSession, settings: rs.RuntimeSettings) -> bool:
    return await spend_today_usd(db) >= Decimal(str(settings.daily_spend_cap_usd))


# --- guards ------------------------------------------------------------------------------


async def signups_paused(db: AsyncSession) -> bool:
    return bool((await rs.get_all(db)).signups_paused)


async def ensure_signups_open(db: AsyncSession) -> None:
    """OC-1: raise 503 `signups_paused` while new accounts are paused."""
    if await signups_paused(db):
        raise ControlRefusedError(SIGNUPS_PAUSED)


def _channel_paused(settings: rs.RuntimeSettings, channel: SessionChannel) -> bool:
    if channel == SessionChannel.VOICE:
        return settings.sessions_paused_voice
    return settings.sessions_paused_text


async def session_block(db: AsyncSession, channel: SessionChannel) -> str | None:
    """The reason a new session on `channel` cannot start now, or None."""
    settings = await rs.get_all(db)
    if _channel_paused(settings, channel):
        return SESSIONS_PAUSED
    if await spend_cap_reached(db, settings):
        return SPEND_CAP_REACHED
    return None


async def ensure_sessions_open(db: AsyncSession, channel: SessionChannel) -> None:
    """OC-2, OC-3: raise 503 when new sessions on `channel` are paused or today's model cost
    reached the daily cap. Call it only before a session starts, never during one."""
    code = await session_block(db, channel)
    if code is not None:
        raise ControlRefusedError(code)


# --- public status (OC-4) -------------------------------------------------------------------


class BannerOut(BaseModel):
    text: str
    severity: Literal["info", "warning", "critical"]
    until: datetime


class SiteStatus(BaseModel):
    """What the candidate app shows: the site banner and what is paused (OC-1 to OC-4)."""

    banner: BannerOut | None = Field(description="OC-4: the active banner, None after `until`")
    signups_open: bool = Field(description="OC-1: false while new accounts are refused")
    voice_sessions_open: bool = Field(description="OC-2, OC-3: new voice sessions can start")
    text_sessions_open: bool = Field(description="OC-2, OC-3: new text sessions can start")
    custom_interview_access: rs.CustomInterviewAccess = Field(
        description="CU-11: everyone, or paid_only (free accounts see Custom locked)"
    )
    v2_enabled: bool = Field(description="FL-1: show the v2 screens that replace v1 screens")


def active_banner(settings: rs.RuntimeSettings, now: datetime | None = None) -> BannerOut | None:
    """The site banner while it is shown (before `until`; a naive `until` is UTC)."""
    banner = settings.site_banner
    if banner is None:
        return None
    until = banner.until if banner.until.tzinfo else banner.until.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) >= until:
        return None
    return BannerOut(text=banner.text, severity=banner.severity, until=until)


async def _db(request: Request) -> AsyncIterator[AsyncSession]:
    # Like strong_api.auth.deps.get_db; not imported, because the auth router imports this module.
    maker = getattr(request.app.state, "sessionmaker", None) or get_sessionmaker()
    async with maker() as session:
        yield session


router = APIRouter(tags=["status"])


@router.get("/status")
async def site_status(db: Annotated[AsyncSession, Depends(_db)]) -> SiteStatus:
    """Public: the active site banner, whether sign-ups and new sessions are open, and who may
    run Custom interviews (CU-11), and whether the v2 screens are on (FL-1)."""
    settings = await rs.get_all(db)
    capped = await spend_cap_reached(db, settings)
    return SiteStatus(
        banner=active_banner(settings),
        signups_open=not settings.signups_paused,
        voice_sessions_open=not (settings.sessions_paused_voice or capped),
        text_sessions_open=not (settings.sessions_paused_text or capped),
        custom_interview_access=settings.custom_interview_access,
        v2_enabled=settings.v2_enabled,
    )
