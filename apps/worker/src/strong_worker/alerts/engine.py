"""The alert engine (AL-2..AL-5): one tick evaluates every enabled rule, then sends the emails.

State machine per rule, on each tick:

    condition true:   ok -> pending (or straight to firing when for_s is 0)
                      pending -> firing once the condition has held for for_s
                      firing -> firing; re-sends every renotify_s (NULL: never)
    condition false:  pending -> ok (no event); firing -> ok with a `resolved` event
    not enough data:  fewer than min_samples samples, or no value: nothing changes

`fired` and `resolved` events are written first and sent after, in the same transaction. A
failed send leaves `notified` false with `notify_error`, and the next tick retries it (events
from the last day only). A muted rule still changes state and writes events, but its events are
marked `notify_error = "muted"` and never sent. If a rule is still firing when its mute ends, the
next tick sends a `fired` email.

Two worker instances never send twice: the tick runs under a Postgres transaction-level
advisory lock, and an instance that does not get it skips the tick.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import AlertEvent, AlertRule
from strong_core.email import EmailSender
from strong_core.ops.alerts import alert_body, alert_subject
from strong_core.schemas.enums import AlertComparator, AlertEventKind, AlertState
from strong_worker.alerts.readings import as_utc, read

log = logging.getLogger(__name__)

LOCK_KEY = 0x5348_414C  # "SHAL": the alert engine's advisory lock id
MUTED = "muted"
NO_RECIPIENT = "ALERT_EMAIL is not set"
RETRY_FOR = timedelta(days=1)


@dataclass
class TickResult:
    skipped: bool = False
    evaluated: int = 0
    events: int = 0
    sent: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def holds(comparator: AlertComparator, value: float, threshold: float) -> bool:
    if comparator == AlertComparator.GT:
        return value > threshold
    if comparator == AlertComparator.GTE:
        return value >= threshold
    if comparator == AlertComparator.LT:
        return value < threshold
    return value <= threshold


def is_muted(rule: AlertRule, now: datetime) -> bool:
    return rule.muted_until is not None and as_utc(rule.muted_until) > now


def _event(
    db: AsyncSession, rule: AlertRule, kind: AlertEventKind, value: float | None, now: datetime
) -> AlertEvent:
    muted = is_muted(rule, now)
    event = AlertEvent(
        rule_id=rule.id,
        kind=kind,
        value=value,
        at=now,
        notified=False,
        notify_error=MUTED if muted else None,
    )
    db.add(event)
    if kind == AlertEventKind.FIRED and not muted:
        rule.last_notified_at = now
    return event


async def evaluate_rule(db: AsyncSession, rule: AlertRule, now: datetime) -> AlertEvent | None:
    """Move one rule through its states. Returns the event it wrote, if any."""
    reading = await read(db, rule, now)
    rule.last_value = reading.value
    if reading.clear:
        condition = False
    elif reading.value is None or reading.count < rule.min_samples:
        return None
    else:
        condition = holds(rule.comparator, reading.value, rule.threshold)

    since = as_utc(rule.state_since) if rule.state_since else None
    if condition:
        if rule.state == AlertState.OK:
            rule.state_since = since = now
            if rule.for_s > 0:
                rule.state = AlertState.PENDING
                return None
        if rule.state == AlertState.PENDING:
            if since is not None and now - since < timedelta(seconds=rule.for_s):
                return None
            rule.state = AlertState.FIRING  # state_since stays: when the condition started
            return _event(db, rule, AlertEventKind.FIRED, reading.value, now)
        if rule.state == AlertState.OK:  # for_s is 0
            rule.state = AlertState.FIRING
            return _event(db, rule, AlertEventKind.FIRED, reading.value, now)
        # Still firing.
        if is_muted(rule, now):
            return None
        last = as_utc(rule.last_notified_at) if rule.last_notified_at else None
        if last is None or (since is not None and last < since):
            return _event(db, rule, AlertEventKind.FIRED, reading.value, now)  # mute ended
        if rule.renotify_s and now - last >= timedelta(seconds=rule.renotify_s):
            return _event(db, rule, AlertEventKind.FIRED, reading.value, now)
        return None

    was = rule.state
    if was != AlertState.OK:
        rule.state = AlertState.OK
        rule.state_since = now
    if was == AlertState.FIRING:
        return _event(db, rule, AlertEventKind.RESOLVED, reading.value, now)
    return None


async def _since(db: AsyncSession, rule: AlertRule, event: AlertEvent) -> datetime | None:
    """Start of the episode the event belongs to: when the condition began, for the email."""
    if event.kind == AlertEventKind.FIRED and rule.state == AlertState.FIRING and rule.state_since:
        return as_utc(rule.state_since)
    if event.kind == AlertEventKind.RESOLVED:
        first_fired = await db.scalar(
            select(AlertEvent.at)
            .where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.kind == AlertEventKind.FIRED,
                AlertEvent.at <= event.at,
            )
            .order_by(AlertEvent.at.desc())
            .limit(1)
        )
        return as_utc(first_fired) if first_fired else None
    return as_utc(event.at)


async def send_event(
    db: AsyncSession,
    rule: AlertRule,
    event: AlertEvent,
    sender: EmailSender,
    *,
    to: str,
    admin_base_url: str,
) -> bool:
    """Email one event to ALERT_EMAIL. Records the outcome on the event; never raises."""
    if not to:
        event.notify_error = NO_RECIPIENT
        log.warning("alert %s not sent: %s", rule.name, NO_RECIPIENT)
        return False
    subject = alert_subject(rule.name, rule.severity, event.kind)
    body = alert_body(
        rule,
        event.kind,
        event.value,
        since=await _since(db, rule, event),
        at=as_utc(event.at),
        admin_base_url=admin_base_url,
    )
    try:
        await sender.send(to, subject, body)
    except Exception as exc:  # any send failure is retried next tick (AL-5)
        event.notify_error = f"{type(exc).__name__}: {exc}"[:500]
        log.warning("alert %s not sent: %s", rule.name, event.notify_error)
        return False
    event.notified = True
    event.notify_error = None
    return True


async def _try_lock(db: AsyncSession) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return True  # tests on SQLite: one process
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
    return bool(got)


async def run_tick(
    maker: async_sessionmaker[AsyncSession],
    sender: EmailSender,
    *,
    now: datetime,
    to: str,
    admin_base_url: str,
) -> TickResult:
    """Evaluate every enabled rule, then send unsent events. One transaction."""
    result = TickResult()
    async with maker() as db:
        if not await _try_lock(db):
            result.skipped = True
            return result
        rules = list(
            await db.scalars(
                select(AlertRule).where(AlertRule.enabled.is_(True)).order_by(AlertRule.name)
            )
        )
        for rule in rules:
            try:
                async with db.begin_nested():
                    event = await evaluate_rule(db, rule, now)
            except Exception as exc:  # one broken rule must not stop the others
                log.exception("alert rule %s failed to evaluate", rule.name)
                result.errors.append(f"{rule.name}: {type(exc).__name__}: {exc}")
                continue
            result.evaluated += 1
            if event is not None:
                result.events += 1
        await db.flush()

        pending = list(
            await db.scalars(
                select(AlertEvent)
                .where(
                    AlertEvent.notified.is_(False),
                    or_(AlertEvent.notify_error.is_(None), AlertEvent.notify_error != MUTED),
                    AlertEvent.at > now - RETRY_FOR,
                )
                .order_by(AlertEvent.at)
            )
        )
        by_id = {r.id: r for r in rules}
        for event in pending:
            owner = by_id.get(event.rule_id) or await db.get(AlertRule, event.rule_id)
            if owner is None:
                continue
            ok = await send_event(db, owner, event, sender, to=to, admin_base_url=admin_base_url)
            if ok:
                result.sent += 1
            else:
                result.failed += 1
        await db.commit()
    return result
