"""What a rule's metric reads now (AL-2): one value and the number of samples behind it.

Sampled metrics come from `ops_samples` in the rule's window, filtered by its labels. Samples are
grouped into series by their labels, each series is aggregated, and the worst series counts (the
highest for > and >=, the lowest for < and <=). So "any dependency down" is one rule.

Up metrics (`heartbeat.up`, `probe.up`): no sample in the window means down. A series the label
filter names (for example service=worker) with no sample counts as one sample of 0, and so does a
rule with no filter when no sample matched at all.

Derived metrics are computed from the domain tables (see `DERIVED`).
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core import runtime_settings as rs
from strong_core.db.models import (
    AlertRule,
    ErrorGroup,
    InterviewSession,
    OpsSample,
    Subscription,
    UsageEvent,
    VoiceTurnTiming,
)
from strong_core.ops.alerts import METRICS, UP_METRICS
from strong_core.schemas.enums import (
    AlertAggregation,
    AlertComparator,
    SessionStatus,
    SubscriptionStatus,
)

SCORING_STUCK_AFTER = timedelta(minutes=15)
ENDED_STATUSES = (
    SessionStatus.COMPLETED,
    SessionStatus.FAILED,
    SessionStatus.INTERRUPTED,
    SessionStatus.SCORING,
)


@dataclass(frozen=True)
class Reading:
    value: float | None
    count: int
    clear: bool = False
    """True: the rule's guard is off, so its condition is false whatever the value."""


def as_utc(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at


def p95(values: Sequence[float]) -> float | None:
    """Nearest-rank 95th percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def aggregate(agg: AlertAggregation, points: Sequence[tuple[datetime, float]]) -> float | None:
    """One series, oldest point first."""
    if not points:
        return None
    values = [v for _, v in points]
    if agg == AlertAggregation.LAST:
        return values[-1]
    if agg == AlertAggregation.AVG:
        return sum(values) / len(values)
    if agg == AlertAggregation.P95:
        return p95(values)
    if agg == AlertAggregation.COUNT:
        return float(len(values))
    # RATE: change per second between the first and the last sample.
    if len(points) < 2:
        return None
    seconds = (points[-1][0] - points[0][0]).total_seconds()
    return (values[-1] - values[0]) / seconds if seconds > 0 else None


def worst(comparator: AlertComparator, values: Sequence[float]) -> float | None:
    if not values:
        return None
    return max(values) if comparator in (AlertComparator.GT, AlertComparator.GTE) else min(values)


def _wanted(labels: dict[str, Any] | None) -> dict[str, list[str]]:
    return {k: v if isinstance(v, list) else [v] for k, v in (labels or {}).items()}


def _matches(sample: dict[str, Any] | None, wanted: dict[str, list[str]]) -> bool:
    have = sample or {}
    return all(have.get(k) in values for k, values in wanted.items())


async def read_sampled(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    since = now - timedelta(seconds=rule.window_s)
    rows = (
        await db.execute(
            select(OpsSample.ts, OpsSample.value, OpsSample.labels_json)
            .where(OpsSample.metric == rule.metric, OpsSample.ts > since, OpsSample.ts <= now)
            .order_by(OpsSample.ts)
        )
    ).all()
    wanted = _wanted(rule.labels_json)
    series: dict[str, list[tuple[datetime, float]]] = {}
    seen: list[dict[str, Any]] = []
    for ts, value, labels in rows:
        if not _matches(labels, wanted):
            continue
        key = json.dumps(labels or {}, sort_keys=True)
        if key not in series:
            seen.append(labels or {})
        series.setdefault(key, []).append((as_utc(ts), float(value)))

    values = [
        v for points in series.values() if (v := aggregate(rule.aggregation, points)) is not None
    ]
    count = sum(len(points) for points in series.values())

    if rule.metric in UP_METRICS:
        missing = 0
        if wanted:
            keys = list(wanted)
            for combo in itertools.product(*(wanted[k] for k in keys)):
                expected = dict(zip(keys, combo, strict=True))
                if not any(_matches(s, {k: [v] for k, v in expected.items()}) for s in seen):
                    missing += 1
        elif not series:
            missing = 1
        values += [0.0] * missing
        count += missing

    return Reading(worst(rule.comparator, values), count)


# --- derived metrics -----------------------------------------------------------------------

Derived = Callable[[AsyncSession, AlertRule, datetime], Awaitable[Reading]]


async def _failure_rate(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    since = now - timedelta(seconds=rule.window_s)
    ended = func.coalesce(InterviewSession.ended_at, InterviewSession.created_at)
    rows = (
        await db.execute(
            select(InterviewSession.status, func.count())
            .where(InterviewSession.status.in_(ENDED_STATUSES), ended > since, ended <= now)
            .group_by(InterviewSession.status)
        )
    ).all()
    total = sum(n for _, n in rows)
    failed = sum(n for status, n in rows if status == SessionStatus.FAILED)
    return Reading(100.0 * failed / total if total else None, total)


async def _e2e_p95(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    since = now - timedelta(seconds=rule.window_s)
    values = list(
        await db.scalars(
            select(VoiceTurnTiming.e2e_ms).where(
                VoiceTurnTiming.e2e_ms.is_not(None),
                VoiceTurnTiming.created_at > since,
                VoiceTurnTiming.created_at <= now,
            )
        )
    )
    return Reading(p95([float(v) for v in values if v is not None]), len(values))


async def _scoring_stuck(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    entered = func.coalesce(
        InterviewSession.ended_at, InterviewSession.started_at, InterviewSession.created_at
    )
    stuck = await db.scalar(
        select(func.count()).where(
            InterviewSession.status == SessionStatus.SCORING,
            entered < now - SCORING_STUCK_AFTER,
        )
    )
    return Reading(float(stuck or 0), 1)


async def spend_today_usd(db: AsyncSession, now: datetime) -> float:
    midnight = datetime.combine(now.astimezone(UTC).date(), time(0), tzinfo=UTC)
    total = await db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.created_at >= midnight, UsageEvent.created_at <= now
        )
    )
    return float(total or 0)


async def _spend_today(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    return Reading(await spend_today_usd(db, now), 1)


async def _spend_cap_pct(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    cap = float(await rs.get(db, rs.SettingKey.DAILY_SPEND_CAP_USD))
    if cap <= 0:
        return Reading(None, 0)
    return Reading(100.0 * await spend_today_usd(db, now) / cap, 1)


async def _new_error_groups(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    since = now - timedelta(seconds=rule.window_s)
    n = await db.scalar(
        select(func.count()).where(ErrorGroup.first_seen > since, ErrorGroup.first_seen <= now)
    )
    return Reading(float(n or 0), 1)


DERIVED: dict[str, Derived] = {
    "sessions.failure_rate": _failure_rate,
    "voice.e2e_p95_ms": _e2e_p95,
    "sessions.scoring_stuck": _scoring_stuck,
    "spend.today_usd": _spend_today,
    "spend.cap_pct": _spend_cap_pct,
    "errors.new_groups": _new_error_groups,
}
assert set(DERIVED) == {m.name for m in METRICS.values() if m.derived}, "derived metrics differ"


# --- guards: a rule on this metric only counts while the guard is true ---------------------


async def _has_active_subscriptions(db: AsyncSession) -> bool:
    """Active Stripe subscriptions (comp plans have no Stripe id and send no webhooks)."""
    n = await db.scalar(
        select(func.count()).where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.stripe_subscription_id.is_not(None),
        )
    )
    return bool(n)


GUARDS: dict[str, Callable[[AsyncSession], Awaitable[bool]]] = {
    # Stripe silent: no webhook for 48 h matters only while someone pays.
    "stripe.webhook_age_s": _has_active_subscriptions,
}


async def read(db: AsyncSession, rule: AlertRule, now: datetime) -> Reading:
    """The rule's current reading. Raises KeyError for a metric outside the catalog."""
    guard = GUARDS.get(rule.metric)
    if guard is not None and not await guard(db):
        return Reading(None, 0, clear=True)
    derived = DERIVED.get(rule.metric)
    if derived is not None:
        return await derived(db, rule, now)
    if rule.metric not in METRICS:
        raise KeyError(rule.metric)
    return await read_sampled(db, rule, now)
