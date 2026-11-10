"""BL-4: give back the minutes of a session whose scoring failed.

The API bills a session when it ends (strong_api.billing.entitlements.record_session_minutes):
it sets `sessions.minutes_billed` and adds the minutes to `subscriptions.minutes_used` on a paid
plan. When scoring then fails, the debrief tells the candidate their minutes are refunded, so
`refund_session_minutes` takes them back:

- `minutes_billed` goes to 0. Minutes used under a comp plan are the sum of `minutes_billed`, so
  this alone refunds a comp plan.
- On a paid plan (Stripe status active or trialing) the minutes come off `minutes_used`, but only
  when the session started in the current billing period: a new period has already reset usage
  to 0, and the refund never takes it below 0.
- It is safe to run twice: the second call finds `minutes_billed` at 0 and does nothing.

A free interview needs no refund: a failed session does not count as a used free interview.
When an admin retries the scoring (strong_api.admin.ops), the API bills the session again with
the same period rule (strong_api.billing.entitlements.rebill_session_minutes); if that scoring
fails too, this refunds it again.

The worker cannot import strong_api, so the paid statuses are repeated here; an API test checks
they match strong_api.billing.entitlements.PAID_STATUSES.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import InterviewSession, Subscription
from strong_core.schemas import SubscriptionStatus

PAID_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING})


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def in_current_period(sub: Subscription, session: InterviewSession) -> bool:
    """The session started in the subscription's current period (or the period is unknown)."""
    start = _utc(sub.period_start)
    started = _utc(session.started_at)
    return start is None or started is None or started >= start


async def refund_session_minutes(db: AsyncSession, session: InterviewSession) -> int:
    """Set minutes_billed to 0 and take the minutes off the paid plan. The caller commits.

    Returns the minutes taken off `subscriptions.minutes_used`.
    """
    minutes = session.minutes_billed or 0
    if minutes <= 0:
        return 0
    session.minutes_billed = 0
    sub = await db.scalar(
        select(Subscription)
        .where(Subscription.org_id == session.org_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    if sub is None or sub.status not in PAID_STATUSES or not in_current_period(sub, session):
        return 0
    used = sub.minutes_used or 0
    sub.minutes_used = max(0, used - minutes)
    return used - sub.minutes_used
