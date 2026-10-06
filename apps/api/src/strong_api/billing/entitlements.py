"""What a user may do under their plan (BL-1, BL-2), and minute metering.

Rules (numbers come from BillingSettings):
- Free plan: gap analyses are free (rate limited, see limits.py) plus `billing_free_interviews`
  interviews in the life of the account. An interview counts once it has started and did not fail.
- Paid plan (Stripe status active or trialing): interview minutes up to `billing_minutes_cap`
  per billing period. A session may start while at least one minute is left; `max_minutes`
  tells the session timer where to stop.
- Usage resets when Stripe starts a new period (webhooks.py sets minutes_used to 0).

The session workstream (P7/P10) calls `ensure_can_start_session` in POST /sessions and
`record_session_minutes` when a session ends.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.billing.settings import BillingSettings, get_billing_settings
from strong_core.db.models import InterviewSession, Subscription
from strong_core.schemas import SessionStatus, SubscriptionStatus

PAID_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING})
UPGRADE_PATH = "/upgrade"

BlockCode = Literal["upgrade_required", "minutes_exhausted"]

BLOCK_MESSAGES: dict[str, str] = {
    "upgrade_required": "You have used your free interview. Subscribe to keep practicing.",
    "minutes_exhausted": "You have used this period's interview minutes.",
}


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes. Treat them as UTC so comparisons work in tests too."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Entitlement:
    plan: Literal["free", "paid"]
    status: SubscriptionStatus | None
    minutes_used: int
    minutes_cap: int
    period_start: datetime | None
    period_end: datetime | None
    cancel_at_period_end: bool
    free_interviews_total: int
    free_interviews_used: int
    block_code: BlockCode | None

    @property
    def minutes_left(self) -> int:
        return max(0, self.minutes_cap - self.minutes_used) if self.plan == "paid" else 0

    @property
    def free_interviews_left(self) -> int:
        return max(0, self.free_interviews_total - self.free_interviews_used)

    @property
    def can_start_session(self) -> bool:
        return self.block_code is None

    def max_minutes(self, duration_min: int) -> int:
        """How long a new session may run before the plan runs out."""
        if self.plan == "paid":
            return min(duration_min, self.minutes_left)
        return duration_min


async def get_subscription(db: AsyncSession, org_id: uuid.UUID) -> Subscription | None:
    return await db.scalar(
        select(Subscription)
        .where(Subscription.org_id == org_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )


async def count_free_interviews_used(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Interviews that started and did not fail, over the life of the account."""
    used = await db.scalar(
        select(func.count())
        .select_from(InterviewSession)
        .where(
            InterviewSession.org_id == org_id,
            InterviewSession.started_at.is_not(None),
            InterviewSession.status != SessionStatus.FAILED,
        )
    )
    return int(used or 0)


def is_paid(sub: Subscription | None) -> bool:
    return sub is not None and sub.status in PAID_STATUSES


async def get_entitlement(
    db: AsyncSession, org_id: uuid.UUID, settings: BillingSettings | None = None
) -> Entitlement:
    settings = settings or get_billing_settings()
    sub = await get_subscription(db, org_id)
    used_free = await count_free_interviews_used(db, org_id)
    paid = is_paid(sub)
    block: BlockCode | None = None
    if paid:
        assert sub is not None
        cap = sub.minutes_cap or settings.billing_minutes_cap
        if sub.minutes_used >= cap:
            block = "minutes_exhausted"
    else:
        cap = 0
        if used_free >= settings.billing_free_interviews:
            block = "upgrade_required"
    return Entitlement(
        plan="paid" if paid else "free",
        status=sub.status if sub else None,
        minutes_used=sub.minutes_used if (sub and paid) else 0,
        minutes_cap=cap,
        period_start=as_utc(sub.period_start) if sub else None,
        period_end=as_utc(sub.period_end) if sub else None,
        cancel_at_period_end=bool(sub and sub.cancel_at_period_end),
        free_interviews_total=settings.billing_free_interviews,
        free_interviews_used=used_free,
        block_code=block,
    )


async def ensure_can_start_session(
    db: AsyncSession, org_id: uuid.UUID, settings: BillingSettings | None = None
) -> Entitlement:
    """Raise HTTP 402 when the plan does not allow a new session (BL-1, BL-2).

    The detail is {"code", "message", "upgrade_url"}. The web app sends the user to the paywall.
    """
    ent = await get_entitlement(db, org_id, settings)
    if ent.block_code is not None:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {
                "code": ent.block_code,
                "message": BLOCK_MESSAGES[ent.block_code],
                "upgrade_url": UPGRADE_PATH,
            },
        )
    return ent


def session_minutes(session: InterviewSession, now: datetime | None = None) -> int:
    """Whole minutes from start to end (rounded up), never more than the chosen duration."""
    started = as_utc(session.started_at)
    if started is None:
        return 0
    ended = as_utc(session.ended_at) or now or datetime.now(UTC)
    seconds = max(0.0, (ended - started).total_seconds())
    return min(session.duration_min, math.ceil(seconds / 60))


async def record_session_minutes(
    db: AsyncSession, session: InterviewSession, now: datetime | None = None
) -> int:
    """Bill a session's minutes to the paid plan. Safe to call more than once per session.

    Sets session.minutes_billed and adds only the difference to Subscription.minutes_used.
    Free-plan sessions get minutes_billed too, but no plan minutes are used. The caller commits.
    Returns the minutes added to the plan.
    """
    minutes = session_minutes(session, now)
    delta = minutes - (session.minutes_billed or 0)
    session.minutes_billed = minutes
    sub = await get_subscription(db, session.org_id)
    if delta <= 0 or not is_paid(sub):
        return 0
    assert sub is not None
    sub.minutes_used = (sub.minutes_used or 0) + delta
    return delta
