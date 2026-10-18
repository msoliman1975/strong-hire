"""Shared pieces of the admin overview and operations pages (AO, OB-10..OB-15, AI).

- `AdminMetric`: one number with its previous-period value, or `measured: false` and the reason
  (AO-8: metrics the app cannot measure are shown as "not measured", never hidden).
- SQL helpers that work the same on Postgres and on the SQLite used by the tests:
  `epoch(col)` (seconds since 1970, UTC), `bucket(col, seconds)` (start of a time bucket as
  epoch seconds) and `percentiles(...)` (nearest-rank p50/p95 with window functions).
- Session health: `stuck_clause` (AI-1) and `failure_info` (AI-4), shared by the Interviews list,
  the overview and the Jobs page.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, ColumnElement, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import expression
from sqlalchemy.sql.compiler import SQLCompiler

from strong_api.billing.entitlements import as_utc
from strong_api.sessions.failure import (
    BRIEF_FAILED,
    ENDED_BEFORE_START,
    brief_is_stale,
    failed_before_start,
)
from strong_core.db.models import InterviewSession
from strong_core.schemas import SessionStatus

RangeKey = Literal["24h", "7d", "30d", "90d"]
RANGES: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

# AI-1: a session is stuck when it stays in scoring, or in progress past its planned length,
# for longer than this.
STUCK_AFTER = timedelta(minutes=15)


def now_utc() -> datetime:
    """The current time. Tests replace it to get exact windows."""
    return datetime.now(UTC)


class AdminMetric(BaseModel):
    """One number on an admin page. `previous` is the same metric over the previous period."""

    measured: bool = True
    value: float | None = None
    previous: float | None = None
    unit: Literal["count", "usd", "pct", "ms", "minutes", "ratio", "rating", "bytes"] = Field(
        default="count", description="pct values are fractions: 0.02 is 2%"
    )
    target: float | None = Field(default=None, description="Spec target, same unit")
    reason: str | None = Field(default=None, description="AO-8: why it is not measured")
    note: str | None = Field(default=None, description="How the number is computed")
    link: str | None = Field(default=None, description="AO-7: admin app path of the list behind it")


def not_measured(reason: str, unit: Any = "count") -> AdminMetric:
    return AdminMetric(measured=False, unit=unit, reason=reason)


def ratio(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None
    return round(part / whole, 6)


def money(value: Any) -> float:
    return round(float(value or 0), 6)


# --- SQL helpers ------------------------------------------------------------------------------


class epoch(expression.FunctionElement[int]):  # noqa: N801 - reads like a SQL function
    """Whole seconds since 1970 (UTC) of a timestamp column."""

    type = BigInteger()
    name = "epoch"
    inherit_cache = True


@compiles(epoch)
def _epoch_postgres(element: epoch, compiler: SQLCompiler, **kw: Any) -> str:
    return f"CAST(FLOOR(EXTRACT(EPOCH FROM {compiler.process(element.clauses, **kw)})) AS BIGINT)"


@compiles(epoch, "sqlite")
def _epoch_sqlite(element: epoch, compiler: SQLCompiler, **kw: Any) -> str:
    return f"CAST(STRFTIME('%s', {compiler.process(element.clauses, **kw)}) AS INTEGER)"


def bucket(column: Any, seconds: int) -> ColumnElement[int]:
    """Start of the `seconds`-wide bucket that holds the timestamp, as epoch seconds."""
    return (epoch(column) // seconds) * seconds


def from_epoch(value: int | float) -> datetime:
    return datetime.fromtimestamp(int(value), UTC)


@dataclass(frozen=True)
class Percentiles:
    n: int
    p50: float | None
    p95: float | None


async def percentiles(
    db: AsyncSession,
    value: Any,
    where: Sequence[Any] = (),
    group: Any = None,
) -> dict[Any, Percentiles]:
    """Nearest-rank p50 and p95 of `value` (rows where it is not NULL), per `group`.

    The result key is the group value, or None without a group. Window functions keep it in SQL
    on both Postgres and SQLite (percentile_cont is Postgres only).
    """
    group_col = group if group is not None else expression.literal(0)
    inner = (
        select(
            group_col.label("g"),
            value.label("v"),
            func.row_number().over(partition_by=group_col, order_by=value).label("rn"),
            func.count().over(partition_by=group_col).label("n"),
        )
        .where(value.is_not(None), *where)
        .subquery()
    )
    query = select(
        inner.c.g,
        inner.c.n,
        func.min(case((inner.c.rn >= inner.c.n * 0.5, inner.c.v))),
        func.min(case((inner.c.rn >= inner.c.n * 0.95, inner.c.v))),
    ).group_by(inner.c.g, inner.c.n)
    out: dict[Any, Percentiles] = {}
    for g, n, p50, p95 in (await db.execute(query)).tuples():
        key = g if group is not None else None
        out[key] = Percentiles(
            int(n), None if p50 is None else float(p50), None if p95 is None else float(p95)
        )
    return out


# --- Session health (AI-1, AI-4) --------------------------------------------------------------


def stuck_clause(now: datetime) -> ColumnElement[bool]:
    """AI-1: in scoring for over 15 min, or in progress for over its length + 15 min."""
    now_s = int(now.timestamp())
    slack = int(STUCK_AFTER.total_seconds())
    scoring_since = func.coalesce(InterviewSession.ended_at, InterviewSession.started_at)
    return or_(
        and_(
            InterviewSession.status == SessionStatus.SCORING,
            scoring_since.is_not(None),
            epoch(scoring_since) + slack < now_s,
        ),
        and_(
            InterviewSession.status == SessionStatus.IN_PROGRESS,
            InterviewSession.started_at.is_not(None),
            epoch(InterviewSession.started_at) + InterviewSession.duration_min * 60 + slack < now_s,
        ),
    )


def technical_failure_clause() -> ColumnElement[bool]:
    """AO-6: failed sessions, except the ones the candidate ended before they started."""
    return and_(
        InterviewSession.status == SessionStatus.FAILED,
        or_(InterviewSession.started_at.is_not(None), InterviewSession.ended_at.is_(None)),
    )


FailureKind = Literal[
    "brief_failed",
    "ended_before_start",
    "scoring_failed",
    "brief_stale",
    "stuck_scoring",
    "stuck_in_progress",
]

SCORING_FAILED = "Scoring failed after the interview ended. Retry it from Operations, Jobs."
BRIEF_STALE = "The interviewer brief has not arrived; the worker job was probably lost."


@dataclass(frozen=True)
class FailureInfo:
    kind: FailureKind
    reason: str


def failure_info(row: InterviewSession, now: datetime) -> FailureInfo | None:
    """AI-4: the derived failure reason (sessions/failure.py), plus stuck and scoring failures."""
    if failed_before_start(row):
        if row.ended_at is None:
            return FailureInfo("brief_failed", BRIEF_FAILED)
        return FailureInfo("ended_before_start", ENDED_BEFORE_START)
    if row.status == SessionStatus.FAILED:
        return FailureInfo("scoring_failed", SCORING_FAILED)
    if brief_is_stale(row, now):
        return FailureInfo("brief_stale", BRIEF_STALE)
    started, ended = as_utc(row.started_at), as_utc(row.ended_at)
    if row.status == SessionStatus.SCORING:
        since = ended or started
        if since is not None and now - since > STUCK_AFTER:
            minutes = int((now - since).total_seconds() // 60)
            return FailureInfo("stuck_scoring", f"In scoring for {minutes} minutes.")
    if row.status == SessionStatus.IN_PROGRESS and started is not None:
        limit = started + timedelta(minutes=row.duration_min) + STUCK_AFTER
        if now > limit:
            minutes = int((now - started).total_seconds() // 60)
            return FailureInfo(
                "stuck_in_progress",
                f"In progress for {minutes} minutes ({row.duration_min} planned).",
            )
    return None


def session_link(status: str | None = None, start: datetime | None = None) -> str:
    """AO-7: the Interviews list with filters."""
    parts = []
    if status:
        parts.append(f"status={status}")
    if start is not None:
        parts.append(f"from={start.date().isoformat()}")
    return "/interviews" + ("?" + "&".join(parts) if parts else "")


def uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
