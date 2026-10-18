"""Alert rules shared by the API (rule editing, test email) and the worker (the engine, AL-1..AL-7).

- `METRICS`: the metric catalog. A rule's metric must be one of these names. Sampled metrics come
  from `ops_samples` (written by the sampler cron, OB-5); derived metrics are computed by the
  engine from the domain tables and have one fixed aggregation.
- `DEFAULT_RULES`: the spec's default rules, seeded by name (`seed_default_rules`). A seeded rule
  that an admin has edited is never overwritten.
- `alert_subject` / `alert_body`: the alert email text, the same for the engine and the test email.

See docs/alerts.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from strong_core.db.models import AlertRule
from strong_core.schemas.enums import (
    AlertAggregation,
    AlertComparator,
    AlertEventKind,
    AlertSeverity,
)

# AL-3: re-notify defaults while a rule keeps firing.
RENOTIFY_CRITICAL_S = 4 * 3600
RENOTIFY_WARNING_S = 24 * 3600


@dataclass(frozen=True)
class MetricInfo:
    name: str
    description: str
    unit: str = ""
    labels: tuple[str, ...] = ()
    derived: bool = False
    up: bool = False
    """1 = up, 0 = down. A missing sample in the window counts as 0 (no data means down)."""
    aggregation: AlertAggregation | None = None
    """Derived metrics only: the one aggregation the engine computes for them."""


_SAMPLED = (
    MetricInfo("probe.up", "Dependency probe passed (1) or failed (0)", "", ("dep",), up=True),
    MetricInfo("probe.latency_ms", "Dependency probe latency", "ms", ("dep",)),
    MetricInfo(
        "heartbeat.up", "Service heartbeat present (1) or missing (0)", "", ("service",), up=True
    ),
    MetricInfo("queue.depth", "Jobs waiting in a queue", "jobs", ("queue",)),
    MetricInfo("sessions.in_progress", "Interviews in progress", "sessions"),
    MetricInfo("host.disk_pct", "Disk used", "%", ("mount",)),
    MetricInfo("host.mem_pct", "Memory used", "%"),
    MetricInfo("host.load1", "Load average (1 min)"),
    MetricInfo("db.size_bytes", "Postgres database size", "bytes"),
    MetricInfo("redis.mem_bytes", "Redis memory used", "bytes"),
    MetricInfo(
        "stripe.webhook_age_s",
        "Time since the last Stripe webhook. Counts only while there are active subscriptions",
        "s",
    ),
)

_DERIVED = (
    MetricInfo(
        "sessions.failure_rate",
        "Failed interviews as a % of interviews that ended in the window; samples = interviews",
        "%",
        derived=True,
        aggregation=AlertAggregation.RATE,
    ),
    MetricInfo(
        "voice.e2e_p95_ms",
        "p95 of voice end-to-end turn latency in the window; samples = turns",
        "ms",
        derived=True,
        aggregation=AlertAggregation.P95,
    ),
    MetricInfo(
        "sessions.scoring_stuck",
        "Interviews in scoring for more than 15 minutes",
        "sessions",
        derived=True,
        aggregation=AlertAggregation.COUNT,
    ),
    MetricInfo(
        "spend.today_usd",
        "Model cost since UTC midnight",
        "USD",
        derived=True,
        aggregation=AlertAggregation.LAST,
    ),
    MetricInfo(
        "spend.cap_pct",
        "Model cost since UTC midnight as a % of the daily spend cap",
        "%",
        derived=True,
        aggregation=AlertAggregation.LAST,
    ),
    MetricInfo(
        "errors.new_groups",
        "Error groups first seen in the window",
        "groups",
        derived=True,
        aggregation=AlertAggregation.COUNT,
    ),
)

METRICS: dict[str, MetricInfo] = {m.name: m for m in (*_SAMPLED, *_DERIVED)}
UP_METRICS = frozenset(m.name for m in _SAMPLED if m.up)


class RuleError(ValueError):
    """A rule definition the engine cannot evaluate."""


def check_rule(metric: str, aggregation: AlertAggregation, labels: dict[str, Any] | None) -> None:
    """Raise RuleError when the metric, its aggregation or its label filter is not valid."""
    info = METRICS.get(metric)
    if info is None:
        raise RuleError(f"Unknown metric {metric!r}. Known: {', '.join(sorted(METRICS))}")
    if info.derived and aggregation != info.aggregation:
        raise RuleError(f"{metric} is derived and always uses aggregation {info.aggregation}")
    for key, value in (labels or {}).items():
        if key not in info.labels:
            raise RuleError(f"{metric} has no label {key!r}")
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(v, str) and v for v in values):
            raise RuleError(f"Label {key!r} needs a value or a list of values")


# --- default rules -------------------------------------------------------------------------


@dataclass(frozen=True)
class DefaultRule:
    name: str
    metric: str
    aggregation: AlertAggregation
    window_s: int
    comparator: AlertComparator
    threshold: float
    severity: AlertSeverity
    for_s: int = 0
    min_samples: int = 1
    labels: dict[str, Any] | None = field(default=None)
    renotify_s: int | None = -1  # -1: the default for the severity

    def row(self) -> AlertRule:
        renotify = self.renotify_s
        if renotify == -1:
            renotify = (
                RENOTIFY_CRITICAL_S
                if self.severity == AlertSeverity.CRITICAL
                else RENOTIFY_WARNING_S
            )
        return AlertRule(
            name=self.name,
            metric=self.metric,
            labels_json=self.labels,
            aggregation=self.aggregation,
            window_s=self.window_s,
            comparator=self.comparator,
            threshold=self.threshold,
            min_samples=self.min_samples,
            for_s=self.for_s,
            severity=self.severity,
            renotify_s=renotify,
            enabled=True,
        )


_A = AlertAggregation
_C = AlertComparator
_S = AlertSeverity

DEFAULT_RULES: tuple[DefaultRule, ...] = (
    # The API heartbeat stands in for the /health probe: the API writes it while it serves.
    DefaultRule("API down", "heartbeat.up", _A.LAST, 120, _C.LT, 1, _S.CRITICAL, for_s=120,
                labels={"service": "api"}),
    DefaultRule("Worker or voice down", "heartbeat.up", _A.LAST, 120, _C.LT, 1, _S.CRITICAL,
                for_s=120, labels={"service": ["worker", "voice"]}),
    # 15 min window: the SMTP probe runs every 10 min (OB-6). `last` is still the newest sample.
    DefaultRule("Dependency down", "probe.up", _A.LAST, 900, _C.LT, 1, _S.CRITICAL, for_s=180),
    DefaultRule("Disk filling", "host.disk_pct", _A.LAST, 300, _C.GT, 85, _S.WARNING),
    DefaultRule("Disk almost full", "host.disk_pct", _A.LAST, 300, _C.GT, 95, _S.CRITICAL),
    DefaultRule("Memory pressure", "host.mem_pct", _A.LAST, 300, _C.GT, 90, _S.WARNING, for_s=600),
    DefaultRule("Session failures", "sessions.failure_rate", _A.RATE, 3600, _C.GT, 5, _S.CRITICAL,
                min_samples=5),
    DefaultRule("Voice slow", "voice.e2e_p95_ms", _A.P95, 1800, _C.GT, 1500, _S.WARNING,
                min_samples=20),
    DefaultRule("Scoring stuck", "sessions.scoring_stuck", _A.COUNT, 900, _C.GT, 0, _S.WARNING),
    DefaultRule("Spend high", "spend.cap_pct", _A.LAST, 300, _C.GTE, 80, _S.WARNING),  # D-6
    DefaultRule("Spend cap reached", "spend.cap_pct", _A.LAST, 300, _C.GTE, 100, _S.CRITICAL),
    DefaultRule("New error", "errors.new_groups", _A.COUNT, 600, _C.GT, 0, _S.WARNING,
                renotify_s=None),
    DefaultRule("Stripe silent", "stripe.webhook_age_s", _A.LAST, 900, _C.GT, 48 * 3600,
                _S.WARNING),
)  # fmt: skip

DEFAULT_RULE_NAMES = frozenset(r.name for r in DEFAULT_RULES)


def _missing(existing: Iterable[str]) -> list[AlertRule]:
    have = set(existing)
    return [r.row() for r in DEFAULT_RULES if r.name not in have]


async def seed_default_rules(db: AsyncSession) -> int:
    """Add the default rules that do not exist yet (by name). Commits. Returns how many."""
    rows = _missing(await db.scalars(select(AlertRule.name)))
    db.add_all(rows)
    await db.commit()
    return len(rows)


def seed_default_rules_sync(db: Session) -> int:
    """`seed_default_rules` for scripts (strong_core.db.seed)."""
    rows = _missing(db.scalars(select(AlertRule.name)))
    db.add_all(rows)
    db.commit()
    return len(rows)


# --- email ---------------------------------------------------------------------------------

_COMPARATOR_TEXT = {_C.GT: ">", _C.GTE: ">=", _C.LT: "<", _C.LTE: "<="}


def comparator_text(comparator: AlertComparator) -> str:
    return _COMPARATOR_TEXT[comparator]


def format_value(value: float | None, metric: str) -> str:
    if value is None:
        return "no data"
    unit = METRICS[metric].unit if metric in METRICS else ""
    text = f"{value:.0f}" if abs(value) >= 100 or value == int(value) else f"{value:.2f}"
    return f"{text} {unit}".strip()


def alerts_url(admin_base_url: str) -> str:
    return admin_base_url.rstrip("/") + "/alerts"


def alert_subject(rule_name: str, severity: AlertSeverity, kind: AlertEventKind) -> str:
    """For example `[Strong Hire][CRITICAL] API down firing`."""
    word = {
        AlertEventKind.FIRED: "firing",
        AlertEventKind.RESOLVED: "resolved",
        AlertEventKind.TEST: "test alert",
    }[kind]
    return f"[Strong Hire][{severity.value.upper()}] {rule_name} {word}"


def _utc(at: datetime | None) -> str:
    return at.strftime("%Y-%m-%d %H:%M UTC") if at else "-"


def alert_body(
    rule: AlertRule,
    kind: AlertEventKind,
    value: float | None,
    *,
    since: datetime | None,
    at: datetime,
    admin_base_url: str,
) -> str:
    """The plain-text email: rule, value, threshold, start time and a link (AL-3)."""
    labels = f" {rule.labels_json}" if rule.labels_json else ""
    lines: Sequence[str] = (
        {
            AlertEventKind.FIRED: f"{rule.name} is firing.",
            AlertEventKind.RESOLVED: f"{rule.name} is resolved.",
            AlertEventKind.TEST: (
                f"This is a test of the alert rule {rule.name}. Nothing is wrong because of it."
            ),
        }[kind],
        "",
        f"Severity:  {rule.severity.value}",
        f"Metric:    {rule.aggregation.value}({rule.metric}{labels}) over {rule.window_s} s",
        f"Value:     {format_value(value, rule.metric)}",
        f"Threshold: {comparator_text(rule.comparator)} "
        f"{format_value(rule.threshold, rule.metric)}",
        f"Since:     {_utc(since)}",
        f"At:        {_utc(at)}",
        "",
        f"Alerts: {alerts_url(admin_base_url)}",
    )
    return "\n".join(lines) + "\n"
