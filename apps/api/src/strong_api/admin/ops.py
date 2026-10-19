"""Admin operations pages (OB-10..OB-14, D-12): read the data A3 collects.

    GET   /admin/ops/health                  one tile per service and dependency, host sparklines
    GET   /admin/ops/metrics?metric=&labels=&range=   one ops_samples metric, bucketed
    GET   /admin/ops/performance?range=      voice latency by component, LLM latency by call
    GET   /admin/ops/errors                  error groups, newest first, with a 24 h sparkline
    GET   /admin/ops/errors/{id}             one group: sample stack, recent events, daily counts
    PATCH /admin/ops/errors/{id}             resolve or reopen (AdminWrite, reason, audited)
    GET   /admin/ops/jobs                    queue depth, failed or stuck gap analyses and scorings
    POST  /admin/ops/jobs/{kind}/{id}/retry  re-enqueue the same Arq job (AdminWrite, audited)
    GET   /admin/ops/spend                   today's and this month's model cost vs the daily cap,
                                             the LiteLLM budgets, and the hosted equivalent

Sources: `ops_samples` (the A3 sampler, metric catalog in docs/admin-spec.md OB-5/OB-6), Redis
heartbeat keys `heartbeat:<service>:<instance>` (OB-1), `voice_turn_timings` (OB-3),
`interviewer_traces`, `error_groups`/`error_events` (OB-4), domain status columns (OB-13: Arq
results are not kept) and `usage_events` (OB-2). Admins never see gap analysis content (D-8):
the Jobs page shows ids, status and the plain error only.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin import metrics as m
from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin
from strong_api.admin.metrics import AdminMetric, not_measured
from strong_api.auth.deps import DbSession
from strong_api.billing.entitlements import as_utc
from strong_api.devtools import LiteLLM, ModelUsage, fetch_model_usage
from strong_api.gap.service import timed_out
from strong_api.gap.settings import get_gap_settings
from strong_api.inputs.deps import Queue
from strong_api.inputs.queue import RUN_GAP_ANALYSIS
from strong_api.scoring.router import start_scoring
from strong_core import runtime_settings as rs
from strong_core.config import get_settings
from strong_core.db.models import (
    ErrorEvent,
    ErrorGroup,
    GapAnalysis,
    InterviewerTrace,
    InterviewSession,
    OpsSample,
    Scorecard,
    UsageEvent,
    User,
    VoiceTurnTiming,
)
from strong_core.schemas import GapStatus, SessionStatus, UsageComponent
from strong_core.schemas.enums import ErrorGroupStatus

router = APIRouter(prefix="/admin/ops", tags=["admin"])

SERVICES = ("api", "worker", "voice")
DEPENDENCIES = ("postgres", "redis", "litellm", "livekit", "stt", "tts", "smtp")
DEP_LABELS = {
    "postgres": "Postgres",
    "redis": "Redis",
    "litellm": "LiteLLM",
    "livekit": "LiveKit",
    "stt": "Speech to text",
    "tts": "Text to speech",
    "smtp": "SMTP",
}
STALE_AFTER = timedelta(minutes=5)  # the sampler runs every minute
SMTP_STALE_AFTER = timedelta(minutes=30)  # SMTP is probed every 10 minutes
STRIPE_SILENT_S = 48 * 3600  # matches the "Stripe silent" alert
ARQ_QUEUE_KEY = "arq:queue"
REDIS_TIMEOUT_S = 2.0
JOB_LOOKBACK = timedelta(days=7)
JOB_LIMIT = 100
ERROR_LIMIT = 200
HOST_METRICS: tuple[tuple[str, str, str], ...] = (
    ("host.disk_pct", "Disk", "pct"),
    ("host.mem_pct", "Memory", "pct"),
    ("host.load1", "Load (1 min)", "ratio"),
    ("db.size_bytes", "Database size", "bytes"),
    ("redis.mem_bytes", "Redis memory", "bytes"),
    ("sessions.in_progress", "Sessions in progress", "count"),
    ("queue.depth", "Queue depth", "count"),
)
VOICE_COMPONENTS = ("e2e", "turn_detection", "stt", "llm_ttft", "tts_ttfb", "other")

MetricRange = Literal["1h", "24h", "7d", "30d"]
METRIC_RANGES: dict[str, tuple[timedelta, int]] = {
    "1h": (timedelta(hours=1), 60),
    "24h": (timedelta(hours=24), 900),
    "7d": (timedelta(days=7), 7200),
    "30d": (timedelta(days=30), 21600),
}
PERF_STEP = {"24h": 3600, "7d": 6 * 3600, "30d": 86400, "90d": 3 * 86400}

TileStatus = Literal["up", "degraded", "down", "unknown"]


# --- Redis (heartbeats, queue depth) ----------------------------------------------------------


def ops_redis(request: Request) -> Any:
    """The Redis client for heartbeats and queue depth. Tests put a fake on app.state."""
    client = getattr(request.app.state, "ops_redis", None)
    if client is None:
        client = Redis.from_url(
            get_settings().redis_url,
            socket_timeout=REDIS_TIMEOUT_S,
            socket_connect_timeout=REDIS_TIMEOUT_S,
        )
        request.app.state.ops_redis = client
    return client


OpsRedis = Annotated[Any, Depends(ops_redis)]


class Heartbeat(BaseModel):
    service: str
    instance: str
    version: str | None = None
    model_profile: str | None = None
    started_at: datetime | None = None
    at: datetime | None = None


async def _read_heartbeats(redis: Any) -> list[Heartbeat]:
    keys = [k async for k in redis.scan_iter(match="heartbeat:*", count=100)]
    if not keys:
        return []
    out = []
    for key, raw in zip(keys, await redis.mget(keys), strict=True):
        if raw is None:
            continue  # expired between the scan and the read
        name = key.decode() if isinstance(key, bytes) else str(key)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        parts = name.split(":", 2)
        data.setdefault("service", parts[1] if len(parts) > 1 else "unknown")
        data.setdefault("instance", parts[2] if len(parts) > 2 else "unknown")
        try:
            out.append(Heartbeat.model_validate(data))
        except ValueError:
            continue
    return sorted(out, key=lambda h: (h.service, h.instance))


async def heartbeats(redis: Any) -> tuple[list[Heartbeat], str | None]:
    try:
        return await asyncio.wait_for(_read_heartbeats(redis), REDIS_TIMEOUT_S), None
    except Exception as exc:  # Redis down: the page still shows the samples
        return [], f"Redis: {type(exc).__name__}"


async def live_queue_depth(redis: Any) -> int | None:
    try:
        return int(await asyncio.wait_for(redis.zcard(ARQ_QUEUE_KEY), REDIS_TIMEOUT_S))
    except Exception:
        return None


# --- Samples ----------------------------------------------------------------------------------


class OpsPoint(BaseModel):
    t: datetime
    value: float = Field(description="Average in the bucket")
    min: float
    max: float
    n: int


class OpsSeries(BaseModel):
    metric: str
    labels: dict[str, str]
    points: list[OpsPoint]


def _labels(raw: Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _label_filter(labels: dict[str, str] | None) -> list[Any]:
    return [OpsSample.labels_json[k].as_string() == v for k, v in (labels or {}).items()]


async def latest_samples(
    db: AsyncSession, metrics: tuple[str, ...], since: datetime
) -> dict[tuple[str, str], tuple[OpsSample, dict[str, str]]]:
    """The newest sample per metric and label set since `since`, keyed by (metric, labels)."""
    rn = (
        func.row_number()
        .over(partition_by=(OpsSample.metric, OpsSample.labels_json), order_by=OpsSample.ts.desc())
        .label("rn")
    )
    inner = (
        select(OpsSample.id, rn)
        .where(OpsSample.metric.in_(metrics), OpsSample.ts >= since)
        .subquery()
    )
    rows = await db.scalars(
        select(OpsSample).join(inner, inner.c.id == OpsSample.id).where(inner.c.rn == 1)
    )
    out = {}
    for row in rows:
        labels = _labels(row.labels_json)
        out[(row.metric, json.dumps(labels, sort_keys=True))] = (row, labels)
    return out


async def series(
    db: AsyncSession,
    metric: str,
    start: datetime,
    end: datetime,
    step: int,
    labels: dict[str, str] | None = None,
) -> list[OpsSeries]:
    """`metric` averaged per `step` seconds, one series per label set."""
    b = m.bucket(OpsSample.ts, step).label("b")
    rows = await db.execute(
        select(
            b,
            OpsSample.labels_json,
            func.avg(OpsSample.value),
            func.min(OpsSample.value),
            func.max(OpsSample.value),
            func.count(),
        )
        .where(
            OpsSample.metric == metric,
            OpsSample.ts >= start,
            OpsSample.ts < end,
            *_label_filter(labels),
        )
        .group_by(b, OpsSample.labels_json)
        .order_by(b)
    )
    grouped: dict[str, OpsSeries] = {}
    for t, raw, avg, low, high, n in rows.tuples():
        lab = _labels(raw)
        key = json.dumps(lab, sort_keys=True)
        if key not in grouped:
            grouped[key] = OpsSeries(metric=metric, labels=lab, points=[])
        grouped[key].points.append(
            OpsPoint(
                t=m.from_epoch(t),
                value=round(float(avg), 4),
                min=float(low),
                max=float(high),
                n=int(n),
            )
        )
    return [grouped[k] for k in sorted(grouped)]


# --- Health (OB-10) ---------------------------------------------------------------------------


class OpsTile(BaseModel):
    key: str
    label: str
    kind: Literal["service", "dependency"]
    status: TileStatus
    detail: str | None = None
    checked_at: datetime | None = None
    latency_ms: float | None = None
    version: str | None = None
    instances: list[Heartbeat] = Field(default_factory=list)


class OpsHostMetric(BaseModel):
    metric: str
    label: str
    unit: Literal["pct", "ratio", "bytes", "count"]
    labels: dict[str, str]
    latest: float | None
    latest_at: datetime | None
    points: list[OpsPoint]


class OpsHealth(BaseModel):
    generated_at: datetime
    tiles: list[OpsTile]
    host: list[OpsHostMetric]
    redis_error: str | None = None


def _service_tile(
    service: str,
    beats: list[Heartbeat],
    sample: tuple[OpsSample, dict[str, str]] | None,
    redis_error: str | None,
) -> OpsTile:
    mine = [h for h in beats if h.service == service]
    label = service.capitalize() if service != "api" else "API"
    if mine:
        versions = sorted({h.version or "?" for h in mine})
        profiles = sorted({h.model_profile or "?" for h in mine})
        mixed = len(versions) > 1 or len(profiles) > 1
        return OpsTile(
            key=service,
            label=label,
            kind="service",
            status="degraded" if mixed else "up",
            detail=(
                f"Instances differ: versions {', '.join(versions)}, profiles {', '.join(profiles)}"
                if mixed
                else f"{len(mine)} instance(s), profile {profiles[0]}"
            ),
            checked_at=max((h.at for h in mine if h.at), default=None),
            version=", ".join(versions),
            instances=mine,
        )
    if service == "api":
        return OpsTile(
            key="api",
            label=label,
            kind="service",
            status="up",
            detail="Answering this request; no heartbeat found",
        )
    if redis_error is None:
        return OpsTile(
            key=service, label=label, kind="service", status="down", detail="No heartbeat (OB-1)"
        )
    if sample is not None:
        row, _ = sample
        return OpsTile(
            key=service,
            label=label,
            kind="service",
            status="up" if row.value >= 1 else "down",
            detail=f"From the sampler; {redis_error}",
            checked_at=row.ts,
        )
    return OpsTile(key=service, label=label, kind="service", status="unknown", detail=redis_error)


def _dep_tile(
    dep: str,
    up: tuple[OpsSample, dict[str, str]] | None,
    latency: tuple[OpsSample, dict[str, str]] | None,
    now: datetime,
) -> OpsTile:
    label = DEP_LABELS[dep]
    if up is None:
        return OpsTile(
            key=dep,
            label=label,
            kind="dependency",
            status="unknown",
            detail="No probe samples yet (OB-6)",
        )
    row, _ = up
    checked = as_utc(row.ts)
    stale = STALE_AFTER if dep != "smtp" else SMTP_STALE_AFTER
    tile_status: TileStatus = "up" if row.value >= 1 else "down"
    detail = None
    if checked is not None and now - checked > stale and tile_status == "up":
        tile_status, detail = "degraded", "The last probe is old; is the sampler running?"
    return OpsTile(
        key=dep,
        label=label,
        kind="dependency",
        status=tile_status,
        detail=detail or ("Probe failing" if tile_status == "down" else None),
        checked_at=checked,
        latency_ms=latency[0].value if latency else None,
    )


def _stripe_tile(sample: tuple[OpsSample, dict[str, str]] | None) -> OpsTile:
    if sample is None:
        return OpsTile(
            key="stripe",
            label="Stripe webhooks",
            kind="dependency",
            status="unknown",
            detail="No samples yet (OB-6)",
        )
    row, _ = sample
    hours = row.value / 3600
    return OpsTile(
        key="stripe",
        label="Stripe webhooks",
        kind="dependency",
        status="up" if row.value < STRIPE_SILENT_S else "degraded",
        detail=f"Last webhook {hours:.1f} h ago",
        checked_at=as_utc(row.ts),
    )


@router.get("/health")
async def get_health(db: DbSession, admin: Admin, redis: OpsRedis) -> OpsHealth:
    """OB-10: one tile per service and dependency, plus host metrics with 24 h sparklines."""
    now = m.now_utc()
    since = now - timedelta(hours=24)
    beats, redis_error = await heartbeats(redis)
    host_names = tuple(name for name, _, _ in HOST_METRICS)
    latest = await latest_samples(
        db,
        ("probe.up", "probe.latency_ms", "heartbeat.up", "stripe.webhook_age_s", *host_names),
        since,
    )

    def one(metric: str, **labels: str) -> tuple[OpsSample, dict[str, str]] | None:
        return latest.get((metric, json.dumps(labels, sort_keys=True)))

    tiles = [_service_tile(s, beats, one("heartbeat.up", service=s), redis_error) for s in SERVICES]
    tiles += [
        _dep_tile(d, one("probe.up", dep=d), one("probe.latency_ms", dep=d), now)
        for d in DEPENDENCIES
    ]
    tiles.append(_stripe_tile(one("stripe.webhook_age_s")))

    host = []
    for name, label, unit in HOST_METRICS:
        for s in await series(db, name, since, now, 1800):
            found = latest.get((name, json.dumps(s.labels, sort_keys=True)))
            suffix = ", ".join(s.labels.values())
            host.append(
                OpsHostMetric(
                    metric=name,
                    label=f"{label} ({suffix})" if suffix else label,
                    unit=unit,
                    labels=s.labels,
                    latest=found[0].value if found else None,
                    latest_at=as_utc(found[0].ts) if found else None,
                    points=s.points,
                )
            )
    return OpsHealth(generated_at=now, tiles=tiles, host=host, redis_error=redis_error)


@router.get("/metrics")
async def get_metric(
    db: DbSession,
    admin: Admin,
    metric: Annotated[str, Query(min_length=1, max_length=100)],
    labels: Annotated[
        str | None, Query(description="Label filter, for example dep:redis,mount:root")
    ] = None,
    range: MetricRange = "24h",
) -> list[OpsSeries]:
    """One ops_samples metric, averaged per bucket (1 min for 1 h up to 6 h for 30 days)."""
    wanted: dict[str, str] = {}
    for part in (labels or "").split(","):
        if not part.strip():
            continue
        key, sep, value = part.partition(":")
        if not sep or not key.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "labels: use key:value")
        wanted[key.strip()] = value.strip()
    length, step = METRIC_RANGES[range]
    now = m.now_utc()
    return await series(db, metric, now - length, now, step, wanted)


# --- Performance (OB-11) ----------------------------------------------------------------------


class LatencyStat(BaseModel):
    key: str
    n: int
    p50_ms: float | None
    p95_ms: float | None


class LatencyPoint(BaseModel):
    t: datetime
    n: int
    p50_ms: float | None
    p95_ms: float | None


class LatencySeries(BaseModel):
    key: str
    points: list[LatencyPoint]


class OpsPerformance(BaseModel):
    range: m.RangeKey
    step_s: int
    voice: list[LatencyStat]
    voice_series: list[LatencySeries]
    llm_role: str = "interviewer"
    llm: list[LatencyStat]
    llm_series: list[LatencySeries]
    llm_other_roles: AdminMetric
    queue_wait: AdminMetric


def voice_column(component: str) -> Any:
    return getattr(VoiceTurnTiming, f"{component}_ms")


async def _stat_series(
    db: AsyncSession, value: Any, ts: Any, where: list[Any], step: int, key: str
) -> LatencySeries:
    b = m.bucket(ts, step)
    found = await m.percentiles(db, value, where, group=b)
    return LatencySeries(
        key=key,
        points=[
            LatencyPoint(t=m.from_epoch(t), n=p.n, p50_ms=p.p50, p95_ms=p.p95)
            for t, p in sorted(found.items())
        ],
    )


@router.get("/performance")
async def get_performance(db: DbSession, admin: Admin, range: m.RangeKey = "24h") -> OpsPerformance:
    """OB-11: voice latency p50/p95 by component over time (OB-3) and interviewer LLM latency."""
    now = m.now_utc()
    start = now - m.RANGES[range]
    step = PERF_STEP[range]
    t = VoiceTurnTiming
    in_range = [t.created_at >= start, t.created_at < now]
    voice, voice_series = [], []
    for comp in VOICE_COMPONENTS:
        col = voice_column(comp)
        p = (await m.percentiles(db, col, in_range)).get(None)
        voice.append(
            LatencyStat(key=comp, n=p.n if p else 0, p50_ms=p and p.p50, p95_ms=p and p.p95)
        )
        voice_series.append(await _stat_series(db, col, t.created_at, in_range, step, comp))

    tr = InterviewerTrace
    traced = [tr.created_at >= start, tr.created_at < now]
    by_call = await m.percentiles(db, tr.latency_ms, traced, group=tr.call)
    llm = [
        LatencyStat(key=str(call), n=p.n, p50_ms=p.p50, p95_ms=p.p95)
        for call, p in sorted(by_call.items())
    ]
    every = (await m.percentiles(db, tr.latency_ms, traced)).get(None)
    if every is not None:
        llm.insert(0, LatencyStat(key="all", n=every.n, p50_ms=every.p50, p95_ms=every.p95))
    return OpsPerformance(
        range=range,
        step_s=step,
        voice=voice,
        voice_series=voice_series,
        llm=llm,
        llm_series=[await _stat_series(db, tr.latency_ms, tr.created_at, traced, step, "all")],
        llm_other_roles=not_measured(
            "Only interviewer calls are traced with their latency; extractor, planner and scorer "
            "calls are not timed yet.",
            "ms",
        ),
        queue_wait=not_measured(
            "Arq does not keep enqueue and start times, so queue wait is not recorded yet.", "ms"
        ),
    )


# --- Errors (OB-12) ---------------------------------------------------------------------------


class OpsErrorGroup(BaseModel):
    id: uuid.UUID
    fingerprint: str
    service: str
    exception_type: str
    message: str
    first_seen: datetime
    last_seen: datetime
    count: int
    status: ErrorGroupStatus
    resolved_at: datetime | None
    resolved_by: str | None
    release: str | None
    events_24h: int
    sparkline: list[int] = Field(description="Events per hour over the last 24 hours, oldest first")


class OpsErrorEvent(BaseModel):
    at: datetime
    service: str
    release: str | None
    request_id: str | None
    session_id: uuid.UUID | None


class OpsErrorDetail(BaseModel):
    group: OpsErrorGroup
    sample_stack: str | None
    daily: list[int] = Field(description="Events per day over the last 14 days, oldest first")
    events: list[OpsErrorEvent]


class OpsErrorUpdate(ActionIn):
    status: ErrorGroupStatus


async def _hourly(
    db: AsyncSession, group_ids: list[uuid.UUID], now: datetime, hours: int, step: int
) -> dict[uuid.UUID, list[int]]:
    if not group_ids:
        return {}
    end_bucket = int(now.timestamp()) // step * step
    first = end_bucket - (hours - 1) * step
    b = m.bucket(ErrorEvent.at, step).label("b")
    rows = await db.execute(
        select(ErrorEvent.group_id, b, func.count())
        .where(ErrorEvent.group_id.in_(group_ids), ErrorEvent.at >= m.from_epoch(first))
        .group_by(ErrorEvent.group_id, b)
    )
    out = {gid: [0] * hours for gid in group_ids}
    for gid, t, n in rows.tuples():
        index = (int(t) - first) // step
        if 0 <= index < hours:
            out[gid][index] = int(n)
    return out


def _group_out(row: ErrorGroup, spark: list[int]) -> OpsErrorGroup:
    return OpsErrorGroup(
        id=row.id,
        fingerprint=row.fingerprint,
        service=row.service,
        exception_type=row.exception_type,
        message=row.message,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        count=row.count,
        status=row.status,
        resolved_at=row.resolved_at,
        resolved_by=row.resolved_by,
        release=row.release,
        events_24h=sum(spark),
        sparkline=spark,
    )


@router.get("/errors")
async def list_errors(
    db: DbSession,
    admin: Admin,
    status_filter: Annotated[Literal["open", "resolved", "all"], Query(alias="status")] = "open",
    service: str | None = None,
) -> list[OpsErrorGroup]:
    """OB-12: error groups sorted by last seen, each with a sparkline of the last 24 hours."""
    query = select(ErrorGroup).order_by(ErrorGroup.last_seen.desc()).limit(ERROR_LIMIT)
    if status_filter != "all":
        query = query.where(ErrorGroup.status == ErrorGroupStatus(status_filter))
    if service:
        query = query.where(ErrorGroup.service == service)
    groups = list(await db.scalars(query))
    sparks = await _hourly(db, [g.id for g in groups], m.now_utc(), 24, 3600)
    return [_group_out(g, sparks[g.id]) for g in groups]


async def _group(db: AsyncSession, group_id: uuid.UUID) -> ErrorGroup:
    row = await db.get(ErrorGroup, group_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Error group not found")
    return row


async def _error_detail(db: AsyncSession, row: ErrorGroup) -> OpsErrorDetail:
    now = m.now_utc()
    spark = (await _hourly(db, [row.id], now, 24, 3600))[row.id]
    daily = (await _hourly(db, [row.id], now, 14, 86400))[row.id]
    events = await db.scalars(
        select(ErrorEvent)
        .where(ErrorEvent.group_id == row.id)
        .order_by(ErrorEvent.at.desc())
        .limit(50)
    )
    return OpsErrorDetail(
        group=_group_out(row, spark),
        sample_stack=row.sample_stack,
        daily=daily,
        events=[
            OpsErrorEvent(
                at=e.at,
                service=e.service,
                release=e.release,
                request_id=e.request_id,
                session_id=e.session_id,
            )
            for e in events
        ],
    )


@router.get("/errors/{group_id}")
async def get_error(group_id: uuid.UUID, db: DbSession, admin: Admin) -> OpsErrorDetail:
    return await _error_detail(db, await _group(db, group_id))


@router.patch("/errors/{group_id}")
async def update_error(
    group_id: uuid.UUID, body: OpsErrorUpdate, db: DbSession, admin: AdminWrite
) -> OpsErrorDetail:
    """OB-12: mark resolved, or reopen. A resolved group that happens again reopens (OB-4)."""
    row = await _group(db, group_id)
    before = {"status": row.status.value, "resolved_by": row.resolved_by}
    if body.status == ErrorGroupStatus.RESOLVED:
        row.status = ErrorGroupStatus.RESOLVED
        row.resolved_at = m.now_utc()
        row.resolved_by = admin.email
        action = "ops.error_resolved"
    else:
        row.status = ErrorGroupStatus.OPEN
        row.resolved_at = None
        row.resolved_by = None
        action = "ops.error_reopened"
    audit_action(
        db,
        admin,
        action,
        f"error_group:{row.id}",
        reason=body.reason,
        before=before,
        after={"status": row.status.value, "resolved_by": row.resolved_by},
    )
    await db.commit()
    return await _error_detail(db, row)


# --- Jobs (OB-13) -----------------------------------------------------------------------------

JobKind = Literal["gap_analysis", "scoring"]


class OpsJob(BaseModel):
    kind: JobKind
    id: uuid.UUID
    state: Literal["failed", "stuck"]
    status: str
    reason: str | None
    user_email: str | None
    created_at: datetime
    updated_at: datetime | None = Field(description="Last change: gap updated_at, session end")
    retryable: bool


class OpsJobs(BaseModel):
    queue_depth: AdminMetric
    queue_series: list[OpsSeries]
    jobs_paused: list[str]
    gap_analyses: list[OpsJob]
    scorings: list[OpsJob]


async def _emails(db: AsyncSession, org_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not org_ids:
        return {}
    rows = await db.execute(select(User.org_id, User.email).where(User.org_id.in_(org_ids)))
    return {org: email for org, email in rows.tuples()}


def _scoring_retryable(row: InterviewSession, now: datetime) -> bool:
    info = m.failure_info(row, now)
    return info is not None and info.kind in ("scoring_failed", "stuck_scoring")


async def _job_lists(db: AsyncSession, now: datetime) -> tuple[list[OpsJob], list[OpsJob]]:
    settings = get_gap_settings()
    since = now - JOB_LOOKBACK
    stuck_before = now - timedelta(seconds=settings.gap_running_timeout_s)
    gaps = list(
        await db.scalars(
            select(GapAnalysis)
            .where(
                (
                    (GapAnalysis.status == GapStatus.FAILED)
                    & (func.coalesce(GapAnalysis.updated_at, GapAnalysis.created_at) >= since)
                )
                | (
                    (GapAnalysis.status == GapStatus.RUNNING)
                    & (GapAnalysis.created_at < stuck_before)
                )
            )
            .order_by(GapAnalysis.created_at.desc())
            .limit(JOB_LIMIT)
        )
    )
    s = InterviewSession
    scorings = list(
        await db.scalars(
            select(s)
            .where(
                ~select(Scorecard.id).where(Scorecard.session_id == s.id).exists(),
                (
                    (s.status == SessionStatus.FAILED)
                    & s.started_at.is_not(None)
                    & (func.coalesce(s.ended_at, s.created_at) >= since)
                )
                | ((s.status == SessionStatus.SCORING) & m.stuck_clause(now)),
            )
            .order_by(s.created_at.desc())
            .limit(JOB_LIMIT)
        )
    )
    emails = await _emails(db, {g.org_id for g in gaps} | {x.org_id for x in scorings})
    gap_jobs = [
        OpsJob(
            kind="gap_analysis",
            id=g.id,
            state="failed" if g.status == GapStatus.FAILED else "stuck",
            status=g.status.value,
            reason=g.error if g.status == GapStatus.FAILED else "Running past the time limit",
            user_email=emails.get(g.org_id),
            created_at=g.created_at,
            updated_at=g.updated_at,
            retryable=True,
        )
        for g in gaps
    ]
    score_jobs = []
    for x in scorings:
        info = m.failure_info(x, now)
        score_jobs.append(
            OpsJob(
                kind="scoring",
                id=x.id,
                state="failed" if x.status == SessionStatus.FAILED else "stuck",
                status=x.status.value,
                reason=info.reason if info else None,
                user_email=emails.get(x.org_id),
                created_at=x.created_at,
                updated_at=x.ended_at,
                retryable=_scoring_retryable(x, now),
            )
        )
    return gap_jobs, score_jobs


@router.get("/jobs")
async def get_jobs(db: DbSession, admin: Admin, redis: OpsRedis) -> OpsJobs:
    """OB-13: queue depth and the gap analyses and scorings that failed (7 days) or are stuck."""
    now = m.now_utc()
    live = await live_queue_depth(redis)
    if live is not None:
        depth = AdminMetric(value=live, note="Live, from Redis")
    else:
        found = await latest_samples(db, ("queue.depth",), now - timedelta(hours=1))
        if found:
            row, _ = max(found.values(), key=lambda x: x[0].ts)
            depth = AdminMetric(value=row.value, note=f"Sampled at {as_utc(row.ts)}")
        else:
            depth = not_measured("Redis is not reachable and there is no queue.depth sample.")
    gaps, scorings = await _job_lists(db, now)
    current = await rs.get_all(db)
    return OpsJobs(
        queue_depth=depth,
        queue_series=await series(db, "queue.depth", now - timedelta(hours=24), now, 900),
        jobs_paused=[str(k) for k in current.jobs_paused],
        gap_analyses=gaps,
        scorings=scorings,
    )


class OpsRetryOut(BaseModel):
    kind: JobKind
    id: uuid.UUID
    job_id: str
    status: str


@router.post("/jobs/{kind}/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(
    kind: JobKind,
    job_id: uuid.UUID,
    body: ActionIn,
    db: DbSession,
    admin: AdminWrite,
    queue: Queue,
) -> OpsRetryOut:
    """OB-13: re-enqueue the Arq job the normal path uses. 409 when the job is not failed or
    stuck."""
    now = m.now_utc()
    if kind == "gap_analysis":
        gap = await db.get(GapAnalysis, job_id)
        if gap is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Gap analysis not found")
        stuck = gap.status == GapStatus.RUNNING and timed_out(gap, get_gap_settings(), now)
        if gap.status != GapStatus.FAILED and not stuck:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This gap analysis is not failed or stuck"
            )
        before = {"status": gap.status.value, "error": gap.error, "created_at": str(gap.created_at)}
        # The run starts again: created_at is the run's start, so the time limit restarts too.
        gap.status, gap.error, gap.created_at, gap.updated_at = GapStatus.RUNNING, None, now, now
        audit_action(
            db,
            admin,
            "ops.job_retry",
            f"gap_analysis:{gap.id}",
            org_id=gap.org_id,
            reason=body.reason,
            before=before,
            after={"status": gap.status.value},
            details={"kind": kind},
        )
        await db.commit()
        arq_id = f"ga:{gap.id}:retry:{uuid.uuid4().hex[:8]}"
        await queue.enqueue(
            RUN_GAP_ANALYSIS, arq_id, gap_analysis_id=str(gap.id), org_id=str(gap.org_id)
        )
        await db.refresh(gap)
        return OpsRetryOut(kind=kind, id=gap.id, job_id=arq_id, status=gap.status.value)

    session = await db.get(InterviewSession, job_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if await db.scalar(select(Scorecard.id).where(Scorecard.session_id == session.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This session is already scored")
    if not _scoring_retryable(session, now):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scoring is not failed or stuck")
    audit_action(
        db,
        admin,
        "ops.job_retry",
        f"session:{session.id}",
        org_id=session.org_id,
        reason=body.reason,
        before={"status": session.status.value},
        after={"status": SessionStatus.SCORING.value},
        details={"kind": kind},
    )
    arq_id = await start_scoring(db, queue, session)  # commits the audit row with the change
    await db.refresh(session)
    return OpsRetryOut(kind=kind, id=session.id, job_id=arq_id, status=session.status.value)


# --- Spend (OB-14, D-12) ----------------------------------------------------------------------


class SpendSlice(BaseModel):
    key: str
    today_usd: float
    month_usd: float


class OpsHostedEquivalent(BaseModel):
    configured: bool
    reason: str | None = None
    stt_seconds: float
    tts_characters: float
    stt_usd_per_second: float | None = None
    tts_usd_per_character: float | None = None
    stt_usd: float | None = None
    tts_usd: float | None = None
    total_usd: float | None = None


class OpsSpend(BaseModel):
    generated_at: datetime
    today_usd: float
    month_usd: float
    daily_cap_usd: float
    cap_pct: float | None = Field(description="Today's cost / the cap, as a fraction")
    by_component: list[SpendSlice]
    by_role: list[SpendSlice]
    daily: list[OpsPoint]
    litellm: ModelUsage
    hosted_equivalent: OpsHostedEquivalent


def shadow_prices() -> tuple[float | None, float | None]:
    """D-12 shadow prices for self-hosted speech: what a hosted provider would charge.

    SHADOW_STT_USD_PER_SECOND and SHADOW_TTS_USD_PER_CHARACTER. Unset: "not configured".
    """

    def read(name: str) -> float | None:
        raw = os.environ.get(name, "").strip()
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    return read("SHADOW_STT_USD_PER_SECOND"), read("SHADOW_TTS_USD_PER_CHARACTER")


async def hosted_equivalent(
    db: AsyncSession, start: datetime, end: datetime
) -> OpsHostedEquivalent:
    u = UsageEvent
    rows = await db.execute(
        select(u.component, func.sum(u.units))
        .where(
            u.cost_known.is_(False),
            u.component.in_((UsageComponent.STT, UsageComponent.TTS)),
            u.created_at >= start,
            u.created_at < end,
        )
        .group_by(u.component)
    )
    units = {str(c): float(n or 0) for c, n in rows.tuples()}
    stt, tts = units.get("stt", 0.0), units.get("tts", 0.0)
    stt_price, tts_price = shadow_prices()
    if stt_price is None and tts_price is None:
        return OpsHostedEquivalent(
            configured=False,
            reason="Not configured: set SHADOW_STT_USD_PER_SECOND and "
            "SHADOW_TTS_USD_PER_CHARACTER.",
            stt_seconds=stt,
            tts_characters=tts,
        )
    stt_usd = round(stt * stt_price, 4) if stt_price is not None else None
    tts_usd = round(tts * tts_price, 4) if tts_price is not None else None
    return OpsHostedEquivalent(
        configured=True,
        stt_seconds=stt,
        tts_characters=tts,
        stt_usd_per_second=stt_price,
        tts_usd_per_character=tts_price,
        stt_usd=stt_usd,
        tts_usd=tts_usd,
        total_usd=round((stt_usd or 0) + (tts_usd or 0), 4),
    )


@router.get("/spend")
async def get_spend(db: DbSession, admin: Admin, http: LiteLLM) -> OpsSpend:
    """OB-14: today's and this month's model cost against the daily cap (OC-3)."""
    now = m.now_utc()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    u = UsageEvent

    async def total(a: datetime) -> float:
        value = await db.scalar(
            select(func.sum(u.cost_usd)).where(u.created_at >= a, u.created_at < now)
        )
        return m.money(value)

    async def slices(column: Any) -> list[SpendSlice]:
        month_rows = await db.execute(
            select(column, func.sum(u.cost_usd))
            .where(u.created_at >= month, u.created_at < now)
            .group_by(column)
        )
        today_rows = await db.execute(
            select(column, func.sum(u.cost_usd))
            .where(u.created_at >= today, u.created_at < now)
            .group_by(column)
        )
        by_today = {k: m.money(v) for k, v in today_rows.tuples()}
        out = [
            SpendSlice(
                key=str(k) if k is not None else "unknown",
                today_usd=by_today.get(k, 0.0),
                month_usd=m.money(v),
            )
            for k, v in month_rows.tuples()
        ]
        return sorted(out, key=lambda x: -x.month_usd)

    day = m.bucket(u.created_at, 86400).label("day")
    daily_rows = await db.execute(
        select(day, func.sum(u.cost_usd), func.min(u.cost_usd), func.max(u.cost_usd), func.count())
        .where(u.created_at >= month, u.created_at < now)
        .group_by(day)
        .order_by(day)
    )
    daily = [
        OpsPoint(t=m.from_epoch(t), value=m.money(s), min=m.money(lo), max=m.money(hi), n=int(n))
        for t, s, lo, hi, n in daily_rows.tuples()
    ]
    cap = float((await rs.get_all(db)).daily_spend_cap_usd)
    today_usd = await total(today)
    return OpsSpend(
        generated_at=now,
        today_usd=today_usd,
        month_usd=await total(month),
        daily_cap_usd=cap,
        cap_pct=round(today_usd / cap, 6) if cap > 0 else None,
        by_component=await slices(u.component),
        by_role=await slices(u.role),
        daily=daily,
        litellm=await fetch_model_usage(http),
        hosted_equivalent=await hosted_equivalent(db, month, now),
    )
