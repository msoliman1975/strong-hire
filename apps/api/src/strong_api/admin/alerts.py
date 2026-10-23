"""Alerts (admin spec AL-1, AL-4, AL-6): edit the rules the worker's alert engine checks every
minute, mute them, send a test alert, and read the history.

    GET    /admin/alerts/metrics             the metric catalog a rule can use
    GET    /admin/alerts/rules               every rule with its current state
    POST   /admin/alerts/rules               add a rule
    PATCH  /admin/alerts/rules/{id}          change a rule (disabling one resets it to ok)
    DELETE /admin/alerts/rules/{id}          delete a rule (not a default rule: disable it)
    POST   /admin/alerts/rules/{id}/mute     {until}: no email until then (null unmutes)
    POST   /admin/alerts/rules/{id}/test     AL-6: send a test email now, write a `test` event
    GET    /admin/alerts/events              history, newest first (filter by rule, kind, range)

Writes follow AA-5/AA-6 (AdminWrite, a reason, an audit row). The engine itself is
strong_worker.alerts; the catalog and default rules are strong_core.ops.alerts.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin
from strong_api.auth.deps import DbSession
from strong_core.config import get_settings
from strong_core.db.models import AlertEvent, AlertRule
from strong_core.email import EmailSender, make_email_sender
from strong_core.ops.alerts import (
    DEFAULT_RULE_NAMES,
    METRICS,
    RuleError,
    alert_body,
    alert_subject,
    check_rule,
)
from strong_core.schemas.enums import (
    AlertAggregation,
    AlertComparator,
    AlertEventKind,
    AlertSeverity,
    AlertState,
)

router = APIRouter(prefix="/admin/alerts", tags=["admin"])

EVENT_LIMIT = 500
MAX_WINDOW_S = 30 * 24 * 3600
Labels = dict[str, str | list[str]]


# --- bodies ---------------------------------------------------------------------------------


class AlertMetric(BaseModel):
    name: str
    description: str
    unit: str
    labels: list[str]
    derived: bool
    up: bool = Field(description="1 = up, 0 = down; no sample in the window counts as down")
    aggregation: AlertAggregation | None = Field(
        description="Derived metrics: the one aggregation they support"
    )


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    metric: str
    labels: Labels | None
    aggregation: AlertAggregation
    window_s: int
    comparator: AlertComparator
    threshold: float
    min_samples: int
    for_s: int
    severity: AlertSeverity
    renotify_s: int | None
    enabled: bool
    muted_until: datetime | None
    state: AlertState
    state_since: datetime | None
    last_notified_at: datetime | None
    last_value: float | None
    is_default: bool = Field(description="Seeded default rule: cannot be deleted or renamed")
    created_at: datetime
    updated_at: datetime | None


class AlertEventOut(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str
    severity: AlertSeverity
    kind: AlertEventKind
    value: float | None
    at: datetime
    notified: bool
    notify_error: str | None


class AlertTestOut(BaseModel):
    sent: bool
    error: str | None
    event: AlertEventOut


class _RuleFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    metric: str | None = Field(default=None, max_length=100)
    labels: Labels | None = None
    aggregation: AlertAggregation | None = None
    window_s: int | None = Field(default=None, ge=60, le=MAX_WINDOW_S)
    comparator: AlertComparator | None = None
    threshold: float | None = None
    min_samples: int | None = Field(default=None, ge=1, le=100_000)
    for_s: int | None = Field(default=None, ge=0, le=MAX_WINDOW_S)
    severity: AlertSeverity | None = None
    renotify_s: int | None = Field(default=None, ge=300, le=MAX_WINDOW_S)
    enabled: bool | None = None

    @model_validator(mode="after")
    def _finite(self) -> _RuleFields:
        if self.threshold is not None and not math.isfinite(self.threshold):
            raise ValueError("threshold must be a finite number")
        return self


class AlertRuleCreateIn(ActionIn, _RuleFields):
    name: str = Field(min_length=1, max_length=100)
    metric: str = Field(max_length=100)
    aggregation: AlertAggregation
    window_s: int = Field(ge=60, le=MAX_WINDOW_S)
    comparator: AlertComparator
    threshold: float
    severity: AlertSeverity
    min_samples: int = Field(default=1, ge=1, le=100_000)
    for_s: int = Field(default=0, ge=0, le=MAX_WINDOW_S)
    enabled: bool = True


class AlertRulePatchIn(ActionIn, _RuleFields):
    """Only the fields that are set change. `labels` and `renotify_s` may be set to null."""


class AlertMuteIn(ActionIn):
    until: datetime | None = Field(description="No email until then. null: unmute")


class AlertTestIn(ActionIn):
    pass


# --- helpers ---------------------------------------------------------------------------------


def alert_email_sender(request: Request) -> EmailSender:
    """`app.state.alert_email_sender` when set (tests), else SMTP or the console."""
    sender: EmailSender | None = getattr(request.app.state, "alert_email_sender", None)
    return sender or make_email_sender()


AlertSender = Annotated[EmailSender, Depends(alert_email_sender)]


def _utc(at: datetime | None) -> datetime | None:
    if at is None:
        return None
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at


def _rule_out(rule: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=rule.id,
        name=rule.name,
        metric=rule.metric,
        labels=rule.labels_json,
        aggregation=rule.aggregation,
        window_s=rule.window_s,
        comparator=rule.comparator,
        threshold=rule.threshold,
        min_samples=rule.min_samples,
        for_s=rule.for_s,
        severity=rule.severity,
        renotify_s=rule.renotify_s,
        enabled=rule.enabled,
        muted_until=_utc(rule.muted_until),
        state=rule.state,
        state_since=_utc(rule.state_since),
        last_notified_at=_utc(rule.last_notified_at),
        last_value=rule.last_value,
        is_default=rule.name in DEFAULT_RULE_NAMES,
        created_at=_utc(rule.created_at) or rule.created_at,
        updated_at=_utc(rule.updated_at),
    )


def _event_out(event: AlertEvent, rule: AlertRule) -> AlertEventOut:
    return AlertEventOut(
        id=event.id,
        rule_id=rule.id,
        rule_name=rule.name,
        severity=rule.severity,
        kind=event.kind,
        value=event.value,
        at=_utc(event.at) or event.at,
        notified=event.notified,
        notify_error=event.notify_error,
    )


def _snapshot(rule: AlertRule) -> dict[str, Any]:
    return _rule_out(rule).model_dump(
        mode="json",
        include={
            "name", "metric", "labels", "aggregation", "window_s", "comparator", "threshold",
            "min_samples", "for_s", "severity", "renotify_s", "enabled", "muted_until",
        },
    )  # fmt: skip


def _check(metric: str, aggregation: AlertAggregation, labels: Labels | None) -> None:
    try:
        check_rule(metric, aggregation, dict(labels) if labels else None)
    except RuleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


async def _get(db: DbSession, rule_id: uuid.UUID) -> AlertRule:
    rule = await db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such alert rule")
    return rule


async def _commit(db: DbSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A rule with this name exists") from exc


# --- routes ----------------------------------------------------------------------------------


@router.get("/metrics")
async def list_metrics(admin: Admin) -> list[AlertMetric]:
    return [
        AlertMetric(
            name=m.name,
            description=m.description,
            unit=m.unit,
            labels=list(m.labels),
            derived=m.derived,
            up=m.up,
            aggregation=m.aggregation,
        )
        for m in METRICS.values()
    ]


@router.get("/rules")
async def list_rules(db: DbSession, admin: Admin) -> list[AlertRuleOut]:
    """Firing first, then pending, then by name."""
    order = {AlertState.FIRING: 0, AlertState.PENDING: 1, AlertState.OK: 2}
    rules = list(await db.scalars(select(AlertRule)))
    rules.sort(key=lambda r: (order[r.state], r.name.lower()))
    return [_rule_out(r) for r in rules]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(body: AlertRuleCreateIn, admin: AdminWrite, db: DbSession) -> AlertRuleOut:
    _check(body.metric, body.aggregation, body.labels)
    rule = AlertRule(
        name=body.name.strip(),
        metric=body.metric,
        labels_json=body.labels or None,
        aggregation=body.aggregation,
        window_s=body.window_s,
        comparator=body.comparator,
        threshold=body.threshold,
        min_samples=body.min_samples,
        for_s=body.for_s,
        severity=body.severity,
        renotify_s=body.renotify_s,
        enabled=body.enabled,
        state=AlertState.OK,
    )
    db.add(rule)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A rule with this name exists") from exc
    audit_action(
        db, admin, "alert_rule.create", f"alert_rule:{rule.id}",
        reason=body.reason, before=None, after=_snapshot(rule),
    )  # fmt: skip
    await _commit(db)
    await db.refresh(rule)
    return _rule_out(rule)


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID, body: AlertRulePatchIn, admin: AdminWrite, db: DbSession
) -> AlertRuleOut:
    rule = await _get(db, rule_id)
    before = _snapshot(rule)
    changes = body.model_dump(exclude_unset=True, exclude={"reason"})
    for required in ("name", "metric", "aggregation", "window_s", "comparator", "threshold",
                     "min_samples", "for_s", "severity", "enabled"):  # fmt: skip
        if required in changes and changes[required] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{required} cannot be null")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if rule.name in DEFAULT_RULE_NAMES and changes["name"] != rule.name:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A default rule keeps its name, so it is not seeded again"
            )
    _check(
        changes.get("metric", rule.metric),
        changes.get("aggregation", rule.aggregation),
        changes.get("labels", rule.labels_json),
    )
    now = datetime.now(UTC)
    for key, value in changes.items():
        if key == "labels":
            rule.labels_json = value or None
        else:
            setattr(rule, key, value)
    if changes.get("enabled") is False and rule.state != AlertState.OK:
        rule.state = AlertState.OK  # the engine skips disabled rules: no stale firing badge
        rule.state_since = now
    rule.updated_at = now
    audit_action(
        db, admin, "alert_rule.update", f"alert_rule:{rule.id}",
        reason=body.reason, before=before, after=_snapshot(rule),
    )  # fmt: skip
    await _commit(db)
    await db.refresh(rule)
    return _rule_out(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, body: ActionIn, admin: AdminWrite, db: DbSession) -> None:
    rule = await _get(db, rule_id)
    if rule.name in DEFAULT_RULE_NAMES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Default rules cannot be deleted. Disable the rule instead."
        )
    audit_action(
        db, admin, "alert_rule.delete", f"alert_rule:{rule.id}",
        reason=body.reason, before=_snapshot(rule), after=None,
    )  # fmt: skip
    await db.delete(rule)
    await db.commit()


@router.post("/rules/{rule_id}/mute")
async def mute_rule(
    rule_id: uuid.UUID, body: AlertMuteIn, admin: AdminWrite, db: DbSession
) -> AlertRuleOut:
    rule = await _get(db, rule_id)
    until = _utc(body.until)
    now = datetime.now(UTC)
    if until is not None and until <= now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "until must be in the future")
    before = _snapshot(rule)
    rule.muted_until = until
    rule.updated_at = now
    audit_action(
        db, admin, "alert_rule.mute" if until else "alert_rule.unmute", f"alert_rule:{rule.id}",
        reason=body.reason, before=before, after=_snapshot(rule),
    )  # fmt: skip
    await db.commit()
    await db.refresh(rule)
    return _rule_out(rule)


@router.post("/rules/{rule_id}/test")
async def test_rule(
    rule_id: uuid.UUID, body: AlertTestIn, admin: AdminWrite, db: DbSession, sender: AlertSender
) -> AlertTestOut:
    """AL-6: email a test alert for this rule to ALERT_EMAIL now. A failed send is retried by
    the engine on its next tick, like any other event (AL-5)."""
    rule = await _get(db, rule_id)
    settings = get_settings()
    now = datetime.now(UTC)
    event = AlertEvent(
        rule_id=rule.id, kind=AlertEventKind.TEST, value=rule.last_value, at=now, notified=False
    )
    db.add(event)
    error: str | None = None
    if not settings.alert_email:
        error = "ALERT_EMAIL is not set"
    else:
        try:
            await sender.send(
                settings.alert_email,
                alert_subject(rule.name, rule.severity, AlertEventKind.TEST),
                alert_body(
                    rule,
                    AlertEventKind.TEST,
                    rule.last_value,
                    since=now,
                    at=now,
                    admin_base_url=settings.admin_base_url,
                ),
            )
        except Exception as exc:  # report the failure; the engine retries the event
            error = f"{type(exc).__name__}: {exc}"[:500]
    event.notified = error is None
    event.notify_error = error
    audit_action(
        db, admin, "alert_rule.test", f"alert_rule:{rule.id}",
        reason=body.reason, details={"sent": error is None, "error": error},
    )  # fmt: skip
    await db.commit()
    await db.refresh(event)
    return AlertTestOut(sent=error is None, error=error, event=_event_out(event, rule))


@router.get("/events")
async def list_events(
    db: DbSession,
    admin: Admin,
    rule_id: uuid.UUID | None = None,
    kind: AlertEventKind | None = None,
    since: Annotated[datetime | None, Query(description="From (inclusive)")] = None,
    until: Annotated[datetime | None, Query(description="To (exclusive)")] = None,
    limit: Annotated[int, Query(ge=1, le=EVENT_LIMIT)] = EVENT_LIMIT,
) -> list[AlertEventOut]:
    """Newest first."""
    query = (
        select(AlertEvent, AlertRule)
        .join(AlertRule, AlertRule.id == AlertEvent.rule_id)
        .order_by(AlertEvent.at.desc(), AlertEvent.id)
        .limit(limit)
    )
    if rule_id is not None:
        query = query.where(AlertEvent.rule_id == rule_id)
    if kind is not None:
        query = query.where(AlertEvent.kind == kind)
    if since is not None:
        query = query.where(AlertEvent.at >= _utc(since))
    if until is not None:
        query = query.where(AlertEvent.at < _utc(until))
    return [_event_out(event, rule) for event, rule in (await db.execute(query)).all()]
