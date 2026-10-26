"""Admin overview (AD-2, AO-1..AO-8, OB-15).

    GET /admin/overview?range=24h|7d|30d|90d

Every number is computed in SQL from our own tables (the L05 principle: the funnel comes from the
database, not from browser analytics). Each one comes with the same number for the previous
period of the same length (AO-1). Numbers the app cannot measure yet are returned with
`measured: false` and the reason (AO-8).

Definitions (docs/spec.md "Metrics and analytics"):
- Funnel (AO-2), for the users who signed up in the range: activated = has a ready gap analysis;
  free interview done = has a completed interview; paid within 14 days = has a Stripe
  subscription (not a `test-plan:` row) created no later than 14 days after their first completed
  interview.
- Revenue (AO-3): active paid = subscriptions in active or trialing, without `test-plan:` rows.
  MRR = active paid x BILLING_PRICE_USD_MONTH. New subscriptions and cancellations count the
  Stripe webhook events `customer.subscription.created` / `.deleted` received in the range.
  Monthly churn = cancellations in the last 30 days / subscribers 30 days ago (active now - new
  + canceled). Refunds count `billing.charge_refunded` audit rows (AU-6 webhook handler).
- Usage (AO-4): started (started_at in range), completed (ended in range), failed (technical
  failures created in range), billed minutes of the sessions that ended in range.
- Cost (AO-5): usage_events in range. Per completed session = cost of the sessions completed in
  range / their count. Self-hosted speech counts $0 (D-12). The server share (OB-15) is
  INFRA_MONTHLY_USD / sessions completed this calendar month, a separate line.
- Quality (AO-6): failure rate = technical failures / sessions created (both without the ones the
  candidate ended before the start); voice latency from voice_turn_timings (OB-3); perceived
  realism = the average post-session rating given in the range (L05, session_feedback).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin import metrics as m
from strong_api.admin.deps import Admin
from strong_api.admin.metrics import AdminMetric, not_measured, ratio
from strong_api.auth.deps import DbSession
from strong_api.billing.settings import get_billing_settings
from strong_api.billing.webhooks import REFUND_ACTION  # the charge.refunded audit action (AU-6)
from strong_core.config import get_settings
from strong_core.db.models import (
    AuditLog,
    GapAnalysis,
    InterviewSession,
    SessionFeedback,
    StripeEvent,
    Subscription,
    UsageEvent,
    User,
    VoiceTurnTiming,
)
from strong_core.schemas import GapStatus, SessionChannel, SessionStatus, SubscriptionStatus

router = APIRouter(prefix="/admin", tags=["admin"])


SUB_CREATED = "customer.subscription.created"
SUB_DELETED = "customer.subscription.deleted"
PAID_WITHIN = timedelta(days=14)
CHURN_WINDOW = timedelta(days=30)
ACTIVE_PAID = (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)

# Spec targets (docs/spec.md "Metrics and analytics").
TARGET_ACTIVATION = 0.60
TARGET_FREE_DONE = 0.50
TARGET_CONVERSION = 0.10
TARGET_CHURN = 0.15
TARGET_SESSIONS_PER_PAID = 4.0
TARGET_COST_PER_SESSION = 0.80
TARGET_FAILURE_RATE = 0.02
TARGET_P50_MS = 800.0
TARGET_P95_MS = 1500.0
TARGET_REALISM = 4.2


class FunnelStep(BaseModel):
    key: str
    label: str
    metric: AdminMetric
    conversion: AdminMetric | None = None


class OverviewRevenue(BaseModel):
    active_subscribers: AdminMetric
    mrr_usd: AdminMetric
    new_subscriptions: AdminMetric
    cancellations: AdminMetric
    monthly_churn: AdminMetric
    refunds: AdminMetric


class OverviewUsage(BaseModel):
    sessions_started: AdminMetric
    sessions_completed: AdminMetric
    sessions_failed: AdminMetric
    minutes: AdminMetric
    sessions_per_paid_user: AdminMetric
    voice_sessions: AdminMetric
    text_sessions: AdminMetric


class CostDay(BaseModel):
    day: datetime
    llm_usd: float
    stt_usd: float
    tts_usd: float
    total_usd: float


class CostSlice(BaseModel):
    key: str
    cost_usd: float
    rows: int


class OverviewCost(BaseModel):
    total_usd: AdminMetric
    per_completed_session_usd: AdminMetric
    server_share_per_session_usd: AdminMetric
    unmetered_rows: AdminMetric
    by_day: list[CostDay]
    by_component: list[CostSlice]
    by_role: list[CostSlice]


class OverviewQuality(BaseModel):
    failure_rate: AdminMetric
    voice_p50_ms: AdminMetric
    voice_p95_ms: AdminMetric
    realism_rating: AdminMetric
    scorer_agreement: AdminMetric
    offer_reported: AdminMetric


class AdminOverview(BaseModel):
    range: m.RangeKey
    start: datetime
    end: datetime
    previous_start: datetime
    funnel: list[FunnelStep]
    revenue: OverviewRevenue
    usage: OverviewUsage
    cost: OverviewCost
    quality: OverviewQuality


async def _count(db: AsyncSession, query: Any) -> int:
    return int(await db.scalar(query) or 0)


def _real_sub() -> Any:
    """Subscriptions that come from Stripe, not the test-plan script rows."""
    return or_(
        Subscription.stripe_customer_id.is_(None),
        not_(Subscription.stripe_customer_id.like("test-plan:%")),
    )


# --- Funnel (AO-2) ----------------------------------------------------------------------------


async def _funnel_counts(db: AsyncSession, start: datetime, end: datetime) -> list[int]:
    cohort = (
        select(User.id.label("user_id"), User.org_id.label("org_id"))
        .where(User.created_at >= start, User.created_at < end)
        .subquery()
    )
    first_done = (
        select(
            InterviewSession.org_id.label("org_id"),
            func.min(InterviewSession.ended_at).label("done_at"),
        )
        .where(InterviewSession.status == SessionStatus.COMPLETED)
        .group_by(InterviewSession.org_id)
        .subquery()
    )
    signups = await _count(db, select(func.count()).select_from(cohort))
    activated = await _count(
        db,
        select(func.count())
        .select_from(cohort)
        .where(
            exists().where(
                GapAnalysis.org_id == cohort.c.org_id, GapAnalysis.status == GapStatus.READY
            )
        ),
    )
    done = await _count(
        db,
        select(func.count()).select_from(
            cohort.join(first_done, first_done.c.org_id == cohort.c.org_id)
        ),
    )
    paid = await _count(
        db,
        select(func.count())
        .select_from(cohort.join(first_done, first_done.c.org_id == cohort.c.org_id))
        .where(
            exists().where(
                Subscription.org_id == cohort.c.org_id,
                Subscription.stripe_subscription_id.is_not(None),
                Subscription.status != SubscriptionStatus.INCOMPLETE,
                _real_sub(),
                m.epoch(Subscription.created_at)
                <= m.epoch(first_done.c.done_at) + int(PAID_WITHIN.total_seconds()),
            )
        ),
    )
    return [signups, activated, done, paid]


async def _funnel(
    db: AsyncSession, start: datetime, end: datetime, prev: datetime
) -> list[FunnelStep]:
    now = await _funnel_counts(db, start, end)
    before = await _funnel_counts(db, prev, start)
    steps = [
        ("signups", "Sign-ups", None, "Users who signed up in the range"),
        ("activated", "Activated", TARGET_ACTIVATION, "Has a ready gap analysis"),
        ("free_interview_done", "Free interview done", TARGET_FREE_DONE, "Completed an interview"),
        (
            "paid_14d",
            "Paid within 14 days",
            TARGET_CONVERSION,
            "Subscribed within 14 days of the first completed interview",
        ),
    ]
    out = []
    for i, (key, label, target, note) in enumerate(steps):
        conversion = None
        if i > 0:
            conversion = AdminMetric(
                value=ratio(now[i], now[i - 1]),
                previous=ratio(before[i], before[i - 1]),
                unit="pct",
                target=target,
                note=f"{label} / {steps[i - 1][1]}",
            )
        out.append(
            FunnelStep(
                key=key,
                label=label,
                metric=AdminMetric(
                    value=now[i], previous=before[i], note=note, link="/users" if i == 0 else None
                ),
                conversion=conversion,
            )
        )
    return out


# --- Revenue (AO-3) ---------------------------------------------------------------------------


async def _events(db: AsyncSession, etype: str, start: datetime, end: datetime) -> int:
    return await _count(
        db,
        select(func.count()).where(
            StripeEvent.type == etype,
            StripeEvent.received_at >= start,
            StripeEvent.received_at < end,
        ),
    )


async def _revenue(
    db: AsyncSession, now: datetime, start: datetime, end: datetime, prev: datetime
) -> OverviewRevenue:
    price = float(get_billing_settings().billing_price_usd_month)
    active = await _count(
        db, select(func.count()).where(Subscription.status.in_(ACTIVE_PAID), _real_sub())
    )
    churn_start = now - CHURN_WINDOW
    churn_prev = churn_start - CHURN_WINDOW
    new_30 = await _events(db, SUB_CREATED, churn_start, now)
    canceled_30 = await _events(db, SUB_DELETED, churn_start, now)
    new_prev_30 = await _events(db, SUB_CREATED, churn_prev, churn_start)
    canceled_prev_30 = await _events(db, SUB_DELETED, churn_prev, churn_start)
    base = active - new_30 + canceled_30
    base_prev = base - new_prev_30 + canceled_prev_30
    refunds = [
        await _count(
            db,
            select(func.count()).where(
                AuditLog.action == REFUND_ACTION, AuditLog.at >= a, AuditLog.at < b
            ),
        )
        for a, b in ((start, end), (prev, start))
    ]
    return OverviewRevenue(
        active_subscribers=AdminMetric(
            value=active,
            note="Active or trialing, without test-plan rows. Now, not per range.",
            link="/users?plan=paid",
        ),
        mrr_usd=AdminMetric(
            value=round(active * price, 2),
            unit="usd",
            note=f"Active paid x ${price:g} a month (BILLING_PRICE_USD_MONTH)",
        ),
        new_subscriptions=AdminMetric(
            value=await _events(db, SUB_CREATED, start, end),
            previous=await _events(db, SUB_CREATED, prev, start),
            note="Stripe customer.subscription.created events",
        ),
        cancellations=AdminMetric(
            value=await _events(db, SUB_DELETED, start, end),
            previous=await _events(db, SUB_DELETED, prev, start),
            note="Stripe customer.subscription.deleted events",
        ),
        monthly_churn=AdminMetric(
            value=ratio(canceled_30, base) if base > 0 else None,
            previous=ratio(canceled_prev_30, base_prev) if base_prev > 0 else None,
            unit="pct",
            target=TARGET_CHURN,
            note="Cancellations in the last 30 days / subscribers 30 days ago. Not per range.",
        ),
        refunds=AdminMetric(
            value=refunds[0],
            previous=refunds[1],
            note="Refunds are made in Stripe (D-7); counted from the charge.refunded webhook",
        ),
    )


# --- Usage (AO-4) -----------------------------------------------------------------------------


def _between(column: Any, a: datetime, b: datetime) -> Any:
    return and_(column >= a, column < b)


async def _usage_counts(db: AsyncSession, a: datetime, b: datetime) -> dict[str, float]:
    s = InterviewSession
    started = await _count(db, select(func.count()).where(_between(s.started_at, a, b)))
    completed = await _count(
        db,
        select(func.count()).where(s.status == SessionStatus.COMPLETED, _between(s.ended_at, a, b)),
    )
    failed = await _count(
        db,
        select(func.count()).where(m.technical_failure_clause(), _between(s.created_at, a, b)),
    )
    minutes = await _count(db, select(func.sum(s.minutes_billed)).where(_between(s.ended_at, a, b)))
    paid_orgs = select(Subscription.org_id).where(Subscription.status.in_(ACTIVE_PAID), _real_sub())
    paid_completed = await _count(
        db,
        select(func.count()).where(
            s.status == SessionStatus.COMPLETED,
            _between(s.ended_at, a, b),
            s.org_id.in_(paid_orgs),
        ),
    )
    voice = await _count(
        db,
        select(func.count()).where(_between(s.started_at, a, b), s.channel == SessionChannel.VOICE),
    )
    return {
        "started": started,
        "completed": completed,
        "failed": failed,
        "minutes": minutes,
        "paid_completed": paid_completed,
        "voice": voice,
        "text": started - voice,
    }


async def _usage(
    db: AsyncSession, start: datetime, end: datetime, prev: datetime
) -> tuple[OverviewUsage, dict[str, float], dict[str, float]]:
    now = await _usage_counts(db, start, end)
    before = await _usage_counts(db, prev, start)
    paid_users = await _count(
        db, select(func.count()).where(Subscription.status.in_(ACTIVE_PAID), _real_sub())
    )

    def metric(key: str, **kw: Any) -> AdminMetric:
        return AdminMetric(value=now[key], previous=before[key], **kw)

    usage = OverviewUsage(
        sessions_started=metric("started", link=m.session_link(None, start)),
        sessions_completed=metric("completed", link=m.session_link("completed", start)),
        sessions_failed=metric("failed", link=m.session_link("failed", start)),
        minutes=metric("minutes", unit="minutes", note="Billed minutes of sessions that ended"),
        sessions_per_paid_user=AdminMetric(
            value=ratio(now["paid_completed"], paid_users),
            previous=ratio(before["paid_completed"], paid_users),
            unit="ratio",
            target=TARGET_SESSIONS_PER_PAID,
            note="Completed sessions of paid users in the range / active paid users now "
            "(target: 4 a month)",
        ),
        voice_sessions=metric("voice", note="Started, voice channel"),
        text_sessions=metric("text", note="Started, text channel"),
    )
    return usage, now, before


# --- Cost (AO-5, OB-15) -----------------------------------------------------------------------


async def _total_cost(db: AsyncSession, a: datetime, b: datetime) -> float:
    return m.money(
        await db.scalar(
            select(func.sum(UsageEvent.cost_usd)).where(_between(UsageEvent.created_at, a, b))
        )
    )


async def _completed_session_cost(db: AsyncSession, a: datetime, b: datetime) -> float:
    done = select(InterviewSession.id).where(
        InterviewSession.status == SessionStatus.COMPLETED,
        _between(InterviewSession.ended_at, a, b),
    )
    return m.money(
        await db.scalar(
            select(func.sum(UsageEvent.cost_usd)).where(UsageEvent.session_id.in_(done))
        )
    )


async def _completed_between(db: AsyncSession, a: datetime, b: datetime) -> int:
    return await _count(
        db,
        select(func.count()).where(
            InterviewSession.status == SessionStatus.COMPLETED,
            _between(InterviewSession.ended_at, a, b),
        ),
    )


async def server_share(db: AsyncSession, now: datetime) -> AdminMetric:
    """OB-15: INFRA_MONTHLY_USD / sessions completed this calendar month (D-12)."""
    infra = get_settings().infra_monthly_usd
    if infra is None:
        return not_measured("INFRA_MONTHLY_USD is not set.", "usd")
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (month - timedelta(days=1)).replace(day=1)
    this = await _completed_between(db, month, now)
    before = await _completed_between(db, last_month, month)
    return AdminMetric(
        value=round(infra / this, 4) if this else None,
        previous=round(infra / before, 4) if before else None,
        unit="usd",
        note=f"${infra:g} a month / sessions completed this calendar month. Not in session cost.",
    )


async def _cost(
    db: AsyncSession,
    now: datetime,
    start: datetime,
    end: datetime,
    prev: datetime,
    usage_now: dict[str, float],
    usage_before: dict[str, float],
) -> OverviewCost:
    u = UsageEvent
    in_range = _between(u.created_at, start, end)
    day = m.bucket(u.created_at, 86400).label("day")
    per_day: dict[int, dict[str, float]] = {}
    rows = await db.execute(
        select(day, u.component, func.sum(u.cost_usd)).where(in_range).group_by(day, u.component)
    )
    for d, component, cost in rows.tuples():
        per_day.setdefault(int(d), {})[str(component)] = m.money(cost)
    by_day = [
        CostDay(
            day=m.from_epoch(d),
            llm_usd=v.get("llm", 0.0),
            stt_usd=v.get("stt", 0.0),
            tts_usd=v.get("tts", 0.0),
            total_usd=m.money(sum(v.values())),
        )
        for d, v in sorted(per_day.items())
    ]

    async def slices(column: Any) -> list[CostSlice]:
        result = await db.execute(
            select(column, func.sum(u.cost_usd), func.count())
            .where(in_range)
            .group_by(column)
            .order_by(func.sum(u.cost_usd).desc())
        )
        return [
            CostSlice(key=str(k) if k is not None else "unknown", cost_usd=m.money(c), rows=int(n))
            for k, c, n in result.tuples()
        ]

    unmetered = [
        await _count(
            db,
            select(func.count()).where(u.cost_known.is_(False), _between(u.created_at, a, b)),
        )
        for a, b in ((start, end), (prev, start))
    ]
    per_session = [
        ratio(await _completed_session_cost(db, start, end), usage_now["completed"]),
        ratio(await _completed_session_cost(db, prev, start), usage_before["completed"]),
    ]
    return OverviewCost(
        total_usd=AdminMetric(
            value=await _total_cost(db, start, end),
            previous=await _total_cost(db, prev, start),
            unit="usd",
            note="All model usage rows, with and without a session",
            link="/ops/spend",
        ),
        per_completed_session_usd=AdminMetric(
            value=per_session[0],
            previous=per_session[1],
            unit="usd",
            target=TARGET_COST_PER_SESSION,
            note="Metered providers only; self-hosted speech counts $0 (D-12)",
            link=m.session_link("completed", start),
        ),
        server_share_per_session_usd=await server_share(db, now),
        unmetered_rows=AdminMetric(
            value=unmetered[0],
            previous=unmetered[1],
            note="Usage rows without a price (self-hosted speech or unpriced models), counted $0",
        ),
        by_day=by_day,
        by_component=await slices(u.component),
        by_role=await slices(u.role),
    )


# --- Quality (AO-6) ---------------------------------------------------------------------------


async def failure_rate(db: AsyncSession, a: datetime, b: datetime) -> tuple[int, int]:
    """Technical failures and sessions created in [a, b), without the ones ended before start."""
    s = InterviewSession
    created = _between(s.created_at, a, b)
    ended_early = and_(
        s.status == SessionStatus.FAILED, s.started_at.is_(None), s.ended_at.is_not(None)
    )
    total = await _count(db, select(func.count()).where(created, not_(ended_early)))
    failed = await _count(db, select(func.count()).where(created, m.technical_failure_clause()))
    return failed, total


async def _realism(db: AsyncSession, start: datetime, end: datetime, prev: datetime) -> AdminMetric:
    """L05: the average post-session rating given in the range, "felt like a real interview"."""

    async def avg(a: datetime, b: datetime) -> tuple[float | None, int]:
        f = SessionFeedback
        row = (
            await db.execute(
                select(func.avg(f.realism), func.count()).where(_between(f.created_at, a, b))
            )
        ).one()
        return (round(float(row[0]), 2) if row[0] is not None else None), int(row[1])

    value, n = await avg(start, end)
    previous, _ = await avg(prev, start)
    if n == 0 and previous is None:
        return AdminMetric(
            measured=False,
            unit="rating",
            target=TARGET_REALISM,
            reason="No post-session ratings in this range yet (L05).",
        )
    return AdminMetric(
        value=value,
        previous=previous,
        unit="rating",
        target=TARGET_REALISM,
        note=f'Average of {n} ratings, "felt like a real interview", 1 to 5',
    )


async def _quality(
    db: AsyncSession, start: datetime, end: datetime, prev: datetime
) -> OverviewQuality:
    failed, total = await failure_rate(db, start, end)
    failed_prev, total_prev = await failure_rate(db, prev, start)
    t = VoiceTurnTiming
    now_p = (await m.percentiles(db, t.e2e_ms, [_between(t.created_at, start, end)])).get(None)
    prev_p = (await m.percentiles(db, t.e2e_ms, [_between(t.created_at, prev, start)])).get(None)
    no_turns = "No voice turn timings in this range yet (OB-3)."

    def latency(attr: str, target: float) -> AdminMetric:
        if now_p is None:
            return not_measured(no_turns, "ms")
        return AdminMetric(
            value=getattr(now_p, attr),
            previous=getattr(prev_p, attr) if prev_p else None,
            unit="ms",
            target=target,
            note=f"End of candidate speech to interviewer audio, {now_p.n} turns",
            link="/ops/performance",
        )

    return OverviewQuality(
        failure_rate=AdminMetric(
            value=ratio(failed, total),
            previous=ratio(failed_prev, total_prev),
            unit="pct",
            target=TARGET_FAILURE_RATE,
            note=f"{failed} of {total} sessions ended by a technical error",
            link=m.session_link("failed", start),
        ),
        voice_p50_ms=latency("p50", TARGET_P50_MS),
        voice_p95_ms=latency("p95", TARGET_P95_MS),
        realism_rating=await _realism(db, start, end, prev),
        scorer_agreement=not_measured(
            "Measured by the eval harness against the human gold set (evals/), not in the app.",
            "pct",
        ),
        offer_reported=not_measured("The offer survey is not built yet."),
    )


@router.get("/overview")
async def get_overview(
    db: DbSession,
    admin: Admin,
    range: Annotated[m.RangeKey, Query(description="AO-1: length of the period")] = "7d",
) -> AdminOverview:
    """AD-2: funnel, revenue, usage, cost and quality, each with the previous period."""
    now = m.now_utc().astimezone(UTC)
    length = m.RANGES[range]
    start, prev = now - length, now - 2 * length
    usage, usage_now, usage_before = await _usage(db, start, now, prev)
    return AdminOverview(
        range=range,
        start=start,
        end=now,
        previous_start=prev,
        funnel=await _funnel(db, start, now, prev),
        revenue=await _revenue(db, now, start, now, prev),
        usage=usage,
        cost=await _cost(db, now, start, now, prev, usage_now, usage_before),
        quality=await _quality(db, start, now, prev),
    )


__all__ = ["REFUND_ACTION", "failure_rate", "router", "server_share"]
