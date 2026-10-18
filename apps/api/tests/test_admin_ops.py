"""Admin overview (AD-2, AO-1..AO-8, OB-15), operations pages (OB-10..OB-14, D-12) and the
Interviews additions (AI-1..AI-4), on fixture rows with exact expected numbers.

The clock is fixed at NOW (2030-01-15 12:00 UTC), so the 7-day range is [01-08 12:00, NOW) and
the previous period is [01-01 12:00, 01-08 12:00). The admin who signs in is created at the real
time, outside both periods.
"""

from __future__ import annotations

import fnmatch
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.admin import metrics
from strong_api.auth.settings import get_auth_settings
from strong_api.main import create_app
from strong_core.config import get_settings
from strong_core.db.models import (
    AuditLog,
    ErrorEvent,
    ErrorGroup,
    GapAnalysis,
    InterviewerTrace,
    InterviewSession,
    JobTarget,
    OpsSample,
    Org,
    Resume,
    StripeEvent,
    Subscription,
    UsageEvent,
    User,
    VoiceTurnTiming,
)
from strong_core.schemas import (
    AuthProvider,
    Difficulty,
    GapStatus,
    InterviewType,
    Mode,
    Phase,
    SessionChannel,
    SessionStatus,
    SubscriptionStatus,
    UsageComponent,
)
from strong_core.schemas.enums import ErrorGroupStatus

from .conftest import InlineQueue, sign_in

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
WRITE = {"X-Admin-Request": "1"}
NOW = datetime(2030, 1, 15, 12, 0, tzinfo=UTC)


def d(day: int, hour: int = 0, minute: int = 0, month: int = 1, year: int = 2030) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


async def _ok() -> None:
    return None


class FakeRedis:
    """Just the calls the ops pages make: heartbeat keys and the Arq queue length."""

    def __init__(self, values: dict[str, str] | None = None, zsets: dict[str, int] | None = None):
        self.values = values or {}
        self.zsets = zsets or {}

    async def scan_iter(self, match: str = "*", count: int = 100) -> AsyncIterator[bytes]:
        for key in list(self.values):
            if fnmatch.fnmatch(key, match):
                yield key.encode()

    async def mget(self, keys: list[bytes]) -> list[str | None]:
        return [self.values.get(k.decode()) for k in keys]

    async def zcard(self, key: str) -> int:
        return self.zsets.get(key, 0)


@pytest.fixture
def app(
    sessionmaker: Maker, queue: InlineQueue, export_store: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    monkeypatch.delenv("INFRA_MONTHLY_USD", raising=False)
    monkeypatch.delenv("SHADOW_STT_USD_PER_SECOND", raising=False)
    monkeypatch.delenv("SHADOW_TTS_USD_PER_CHARACTER", raising=False)
    monkeypatch.setattr(metrics, "now_utc", lambda: NOW)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    app = create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    app.state.export_store = export_store
    beat = {
        "service": "worker",
        "instance": "w1",
        "version": "1.2.3",
        "model_profile": "fake",
        "started_at": "2030-01-15T10:00:00Z",
        "at": "2030-01-15T11:59:50Z",
    }
    app.state.ops_redis = FakeRedis({"heartbeat:worker:w1": json.dumps(beat)}, {"arq:queue": 3})
    yield app
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, ADMIN)
        yield http


@dataclass
class Seed:
    users: dict[str, User] = field(default_factory=dict)
    sessions: dict[str, InterviewSession] = field(default_factory=dict)
    gaps: dict[str, GapAnalysis] = field(default_factory=dict)
    errors: dict[str, ErrorGroup] = field(default_factory=dict)


async def _user(db: AsyncSession, seed: Seed, key: str, created: datetime) -> User:
    org = Org(name=key)
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id,
        email=f"{key}@example.com",
        auth_provider=AuthProvider.DEV,
        created_at=created,
        training_consent=True,
    )
    db.add(user)
    await db.flush()
    seed.users[key] = user
    return user


async def _gap(db: AsyncSession, seed: Seed, key: str, user: User, **kw: Any) -> GapAnalysis:
    job = JobTarget(org_id=user.org_id, user_id=user.id, raw_text="Engineer")
    resume = Resume(org_id=user.org_id, user_id=user.id)
    db.add_all([job, resume])
    await db.flush()
    gap = GapAnalysis(org_id=user.org_id, job_target_id=job.id, resume_id=resume.id, **kw)
    db.add(gap)
    await db.flush()
    seed.gaps[key] = gap
    return gap


async def _session(
    db: AsyncSession,
    seed: Seed,
    key: str,
    user: User,
    status: SessionStatus,
    created: datetime,
    started: datetime | None = None,
    ended: datetime | None = None,
    billed: int = 0,
    channel: SessionChannel = SessionChannel.VOICE,
    duration: int = 10,
) -> InterviewSession:
    job = JobTarget(org_id=user.org_id, user_id=user.id, raw_text="Engineer")
    db.add(job)
    await db.flush()
    row = InterviewSession(
        org_id=user.org_id,
        job_target_id=job.id,
        type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=duration,
        channel=channel,
        status=status,
        created_at=created,
        started_at=started,
        ended_at=ended,
        minutes_billed=billed,
        brief_json={"ok": True} if started else None,
    )
    db.add(row)
    await db.flush()
    seed.sessions[key] = row
    return row


def _usage(
    org: uuid.UUID,
    session: InterviewSession | None,
    component: UsageComponent,
    role: str,
    cost: str,
    at: datetime,
    units: str = "100",
    known: bool = True,
) -> UsageEvent:
    return UsageEvent(
        org_id=org,
        session_id=session.id if session else None,
        component=component,
        role=role,
        units=Decimal(units),
        cost_usd=Decimal(cost),
        cost_known=known,
        created_at=at,
    )


async def seed_all(maker: Maker) -> Seed:
    seed = Seed()
    S = SessionStatus  # noqa: N806
    async with maker() as db:
        # Users: four sign-ups in the range, two in the previous period.
        u1 = await _user(db, seed, "u1", d(9))
        u2 = await _user(db, seed, "u2", d(10))
        u3 = await _user(db, seed, "u3", d(11))
        u4 = await _user(db, seed, "u4", d(12))
        p1 = await _user(db, seed, "p1", d(2))
        p2 = await _user(db, seed, "p2", d(3))
        for key, user in (("g1", u1), ("g2", u2), ("gp1", p1), ("gp2", p2)):
            await _gap(db, seed, key, user, status=GapStatus.READY, created_at=d(9))
        await _gap(
            db,
            seed,
            "g3_failed",
            u3,
            status=GapStatus.FAILED,
            error="The job posting is not ready yet.",
            created_at=d(11, 12),
            updated_at=d(11, 12),
        )
        await _gap(db, seed, "g4_stuck", u4, status=GapStatus.RUNNING, created_at=d(15, 11))

        # Sessions in the range.
        s1 = await _session(db, seed, "s1", u1, S.COMPLETED, d(10, 9), d(10, 9), d(10, 10), 10)
        s2 = await _session(
            db, seed, "s2", u2, S.COMPLETED, d(11, 9), d(11, 9), d(11, 10), 10, SessionChannel.TEXT
        )
        await _session(db, seed, "s3_brief", u1, S.FAILED, d(12))
        await _session(db, seed, "s4_early", u2, S.FAILED, d(12), None, d(12, 1))
        s5 = await _session(
            db, seed, "s5_stuck", u3, S.SCORING, d(15, 10), d(15, 10), d(15, 10, 30)
        )
        await _session(db, seed, "s6_scoring", u4, S.FAILED, d(13, 9), d(13, 9), d(13, 9, 30))
        await _session(
            db, seed, "s7_live", u3, S.IN_PROGRESS, d(15, 11, 50), d(15, 11, 50), duration=30
        )
        # Previous period.
        sp1 = await _session(
            db, seed, "p1s", p1, S.COMPLETED, d(3, 9), d(3, 9), d(3, 10), 30, duration=30
        )
        await _session(db, seed, "p2s", p2, S.COMPLETED, d(3, 11), d(3, 11), d(3, 12), 10)
        await _session(db, seed, "p2_brief", p2, S.FAILED, d(4))

        # Subscriptions: u1 active, p1 trialing, p2 a test-plan row (never counted).
        db.add_all(
            [
                Subscription(
                    org_id=u1.org_id,
                    user_id=u1.id,
                    stripe_customer_id="cus_u1",
                    stripe_subscription_id="sub_u1",
                    status=SubscriptionStatus.ACTIVE,
                    created_at=d(12),
                ),
                Subscription(
                    org_id=p1.org_id,
                    user_id=p1.id,
                    stripe_customer_id="cus_p1",
                    stripe_subscription_id="sub_p1",
                    status=SubscriptionStatus.TRIALING,
                    created_at=d(4),
                ),
                Subscription(
                    org_id=p2.org_id,
                    user_id=p2.id,
                    stripe_customer_id=f"test-plan:{p2.id}",
                    stripe_subscription_id="test",
                    status=SubscriptionStatus.ACTIVE,
                    created_at=d(4),
                ),
            ]
        )
        created, deleted = "customer.subscription.created", "customer.subscription.deleted"
        db.add_all(
            [
                StripeEvent(id="evt_1", type=created, received_at=d(12)),
                StripeEvent(id="evt_2", type=created, received_at=d(4)),
                StripeEvent(id="evt_4", type=deleted, received_at=d(13)),
                StripeEvent(id="evt_5", type=deleted, received_at=d(1, month=12, year=2029)),
                AuditLog(
                    org_id=u1.org_id,
                    actor="stripe",
                    action="billing.charge_refunded",
                    entity=f"user:{u1.id}",
                    at=d(14),
                ),
            ]
        )

        # Cost.
        llm, stt, tts = UsageComponent.LLM, UsageComponent.STT, UsageComponent.TTS
        db.add_all(
            [
                _usage(u1.org_id, s1, llm, "interviewer", "0.10", d(10, 10)),
                _usage(u1.org_id, s1, stt, "stt", "0", d(10, 10), units="600", known=False),
                _usage(u1.org_id, s1, tts, "tts", "0.05", d(10, 10), units="2000"),
                _usage(u2.org_id, s2, llm, "interviewer", "0.20", d(11, 10)),
                _usage(u2.org_id, s2, llm, "scorer", "0.05", d(11, 10)),
                _usage(u1.org_id, None, llm, "planner", "0.03", d(9, 12)),
                _usage(u3.org_id, s5, llm, "interviewer", "0.04", d(15, 10)),
                _usage(p1.org_id, sp1, llm, "interviewer", "0.30", d(3, 10)),
            ]
        )

        # Voice latency: five turns in s1, one in the previous period.
        for i, e2e in enumerate([500, 700, 900, 1100, 2000]):
            db.add(
                VoiceTurnTiming(
                    org_id=u1.org_id,
                    session_id=s1.id,
                    turn_index=i,
                    e2e_ms=e2e,
                    stt_ms=100 + i,
                    created_at=d(10, 9, i),
                )
            )
        db.add(
            VoiceTurnTiming(
                org_id=p1.org_id, session_id=sp1.id, turn_index=0, e2e_ms=1000, created_at=d(3, 9)
            )
        )
        for seq, (call, latency) in enumerate([("say", 400), ("say", 600), ("decide", 1000)]):
            db.add(
                InterviewerTrace(
                    org_id=u1.org_id,
                    session_id=s1.id,
                    seq=seq,
                    turn_index=seq,
                    call=call,
                    move="ask",
                    phase=Phase.CORE,
                    elapsed_ms=0,
                    latency_ms=latency,
                    created_at=d(10, 9, seq),
                )
            )

        # Errors: one open group with events, one resolved group.
        g1 = ErrorGroup(
            fingerprint="f1",
            service="api",
            exception_type="ValueError",
            message="bad value",
            first_seen=d(12),
            last_seen=NOW - timedelta(hours=1),
            count=4,
            sample_stack="Traceback ...",
            release="1.2.3",
        )
        g2 = ErrorGroup(
            fingerprint="f2",
            service="worker",
            exception_type="KeyError",
            message="missing",
            first_seen=d(5),
            last_seen=d(6),
            status=ErrorGroupStatus.RESOLVED,
        )
        db.add_all([g1, g2])
        await db.flush()
        seed.errors = {"g1": g1, "g2": g2}
        for at in (
            NOW - timedelta(minutes=30),
            NOW - timedelta(minutes=30),
            NOW - timedelta(hours=3),
            NOW - timedelta(days=3),
        ):
            db.add(ErrorEvent(group_id=g1.id, at=at, service="api", release="1.2.3"))

        # Samples for the Health page.
        def sample(metric: str, value: float, ago: timedelta, **labels: str) -> OpsSample:
            return OpsSample(ts=NOW - ago, metric=metric, value=value, labels_json=labels)

        minute = timedelta(minutes=1)
        db.add_all(
            [
                sample("probe.up", 0, 2 * minute, dep="postgres"),
                sample("probe.up", 1, minute, dep="postgres"),
                sample("probe.latency_ms", 3.5, minute, dep="postgres"),
                sample("probe.up", 0, minute, dep="redis"),
                sample("probe.up", 1, 10 * minute, dep="litellm"),
                sample("host.disk_pct", 40, 90 * minute, mount="root"),
                sample("host.disk_pct", 50, 10 * minute, mount="root"),
                sample("host.disk_pct", 70, 10 * minute, mount="pgdata"),
                sample("host.mem_pct", 61, 5 * minute),
            ]
        )
        await db.commit()
    return seed


def by_key(items: list[dict[str, Any]], key: str = "key") -> dict[str, dict[str, Any]]:
    return {item[key]: item for item in items}


# --- Overview ---------------------------------------------------------------------------------


async def test_ao_overview_routes_are_404_for_non_admins(
    anon_client: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    """AA-4 for the new routes."""
    for path in (
        "/admin/overview",
        "/admin/ops/health",
        "/admin/ops/metrics?metric=host.mem_pct",
        "/admin/ops/performance",
        "/admin/ops/errors",
        "/admin/ops/jobs",
        "/admin/ops/spend",
    ):
        assert (await anon_client.get(path)).status_code == 404, path
        assert (await client.get(path)).status_code == 404, path


async def test_ao2_funnel_with_conversion_and_previous_period(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AO-1, AO-2: sign-ups, activation, free interview done, paid within 14 days."""
    await seed_all(sessionmaker)
    body = (await admin.get("/admin/overview", params={"range": "7d"})).json()
    assert body["range"] == "7d"
    assert body["end"].startswith("2030-01-15T12:00")
    assert body["start"].startswith("2030-01-08T12:00")
    assert body["previous_start"].startswith("2030-01-01T12:00")
    steps = by_key(body["funnel"])
    assert [s["key"] for s in body["funnel"]] == [
        "signups",
        "activated",
        "free_interview_done",
        "paid_14d",
    ]
    assert [s["metric"]["value"] for s in body["funnel"]] == [4, 2, 2, 1]
    assert [s["metric"]["previous"] for s in body["funnel"]] == [2, 2, 2, 1]
    assert steps["signups"]["conversion"] is None
    assert steps["activated"]["conversion"]["value"] == 0.5
    assert steps["activated"]["conversion"]["previous"] == 1.0
    assert steps["free_interview_done"]["conversion"]["value"] == 1.0
    assert steps["paid_14d"]["conversion"]["value"] == 0.5
    assert steps["paid_14d"]["conversion"]["previous"] == 0.5


async def test_ao3_revenue_excludes_test_plans(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AO-3: active paid, MRR, new subscriptions, cancellations, churn, refunds."""
    await seed_all(sessionmaker)
    rev = (await admin.get("/admin/overview?range=7d")).json()["revenue"]
    assert rev["active_subscribers"]["value"] == 2
    assert rev["mrr_usd"]["value"] == 58.0
    assert (rev["new_subscriptions"]["value"], rev["new_subscriptions"]["previous"]) == (1, 1)
    assert (rev["cancellations"]["value"], rev["cancellations"]["previous"]) == (1, 0)
    # Last 30 days: 1 cancellation / (2 active - 2 new + 1 canceled). Before: 1 / 2.
    assert rev["monthly_churn"]["value"] == 1.0
    assert rev["monthly_churn"]["previous"] == 0.5
    assert (rev["refunds"]["value"], rev["refunds"]["previous"]) == (1, 0)


async def test_ao4_usage(admin: httpx.AsyncClient, sessionmaker: Maker) -> None:
    """AO-4: started, completed, failed, minutes, sessions per paid user, voice and text."""
    await seed_all(sessionmaker)
    usage = (await admin.get("/admin/overview?range=7d")).json()["usage"]
    got = {k: (v["value"], v["previous"]) for k, v in usage.items()}
    assert got == {
        "sessions_started": (5, 2),
        "sessions_completed": (2, 2),
        "sessions_failed": (2, 1),
        "minutes": (20, 40),
        "sessions_per_paid_user": (0.5, 0.5),
        "voice_sessions": (4, 2),
        "text_sessions": (1, 0),
    }
    assert usage["sessions_failed"]["link"] == "/interviews?status=failed&from=2030-01-08"


async def test_ao5_cost_by_day_component_role_and_per_session(
    admin: httpx.AsyncClient, sessionmaker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AO-5 and OB-15: cost totals and breakdowns; the server share is its own line."""
    await seed_all(sessionmaker)
    cost = (await admin.get("/admin/overview?range=7d")).json()["cost"]
    assert cost["total_usd"]["value"] == 0.47
    assert cost["total_usd"]["previous"] == 0.3
    assert cost["per_completed_session_usd"]["value"] == 0.2
    assert cost["per_completed_session_usd"]["previous"] == 0.15
    assert cost["per_completed_session_usd"]["target"] == 0.8
    assert (cost["unmetered_rows"]["value"], cost["unmetered_rows"]["previous"]) == (1, 0)
    assert [c["key"] for c in cost["by_component"]] == ["llm", "tts", "stt"]
    assert by_key(cost["by_component"])["llm"]["cost_usd"] == 0.42
    roles = {r["key"]: r["cost_usd"] for r in cost["by_role"]}
    assert roles == {"interviewer": 0.34, "scorer": 0.05, "tts": 0.05, "planner": 0.03, "stt": 0.0}
    days = {c["day"][:10]: c["total_usd"] for c in cost["by_day"]}
    assert days == {"2030-01-09": 0.03, "2030-01-10": 0.15, "2030-01-11": 0.25, "2030-01-15": 0.04}
    assert cost["by_day"][1]["tts_usd"] == 0.05
    # OB-15, AO-8: no INFRA_MONTHLY_USD, not measured.
    share = cost["server_share_per_session_usd"]
    assert share["measured"] is False
    assert "INFRA_MONTHLY_USD" in share["reason"]

    monkeypatch.setenv("INFRA_MONTHLY_USD", "40")
    get_settings.cache_clear()
    share = (await admin.get("/admin/overview?range=7d")).json()["cost"][
        "server_share_per_session_usd"
    ]
    # $40 / 4 sessions completed in January; none in December.
    assert (share["measured"], share["value"], share["previous"]) == (True, 10.0, None)


async def test_ao6_quality_and_ao8_not_measured(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AO-6: failure rate and voice p50/p95; AO-8: realism and others are named, not hidden."""
    await seed_all(sessionmaker)
    q = (await admin.get("/admin/overview?range=7d")).json()["quality"]
    # 2 technical failures of 6 sessions (the one ended before it started does not count).
    assert q["failure_rate"]["value"] == 0.333333
    assert q["failure_rate"]["previous"] == 0.333333
    assert (q["voice_p50_ms"]["value"], q["voice_p50_ms"]["previous"]) == (900, 1000)
    assert (q["voice_p95_ms"]["value"], q["voice_p95_ms"]["previous"]) == (2000, 1000)
    for key in ("realism_rating", "scorer_agreement", "offer_reported"):
        assert q[key]["measured"] is False
        assert q[key]["reason"]
    assert q["realism_rating"]["target"] == 4.2


async def test_ao8_empty_database_marks_latency_not_measured(admin: httpx.AsyncClient) -> None:
    body = (await admin.get("/admin/overview?range=24h")).json()
    assert body["quality"]["voice_p95_ms"]["measured"] is False
    assert body["quality"]["failure_rate"]["value"] is None
    assert body["revenue"]["active_subscribers"]["value"] == 0


# --- Interviews (AI) --------------------------------------------------------------------------


async def test_ai1_ai4_status_filter_with_stuck_and_failure_reason(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    seed = await seed_all(sessionmaker)
    stuck = (await admin.get("/admin/sessions", params={"status": "stuck"})).json()["sessions"]
    assert [s["id"] for s in stuck] == [str(seed.sessions["s5_stuck"].id)]
    assert stuck[0]["stuck"] is True
    assert stuck[0]["failure_kind"] == "stuck_scoring"
    assert stuck[0]["failure_reason"] == "In scoring for 90 minutes."

    failed = (await admin.get("/admin/sessions", params={"status": "failed"})).json()["sessions"]
    kinds = {s["id"]: s["failure_kind"] for s in failed}
    assert kinds[str(seed.sessions["s3_brief"].id)] == "brief_failed"
    assert kinds[str(seed.sessions["s4_early"].id)] == "ended_before_start"
    assert kinds[str(seed.sessions["s6_scoring"].id)] == "scoring_failed"
    assert all(s["status"] == "failed" for s in failed)

    live = (await admin.get("/admin/sessions", params={"status": "in_progress"})).json()
    assert [s["failure_kind"] for s in live["sessions"]] == [None]
    assert (await admin.get("/admin/sessions", params={"status": "bogus"})).status_code == 422


async def test_ai2_ai3_detail_cost_breakdown_and_turn_latency(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    seed = await seed_all(sessionmaker)
    body = (await admin.get(f"/admin/sessions/{seed.sessions['s1'].id}")).json()
    lines = {(c["component"], c["role"]): c for c in body["cost_breakdown"]}
    assert set(lines) == {("llm", "interviewer"), ("stt", "stt"), ("tts", "tts")}
    assert lines[("llm", "interviewer")]["cost_usd"] == 0.1
    assert lines[("stt", "stt")]["cost_known"] is False
    assert lines[("stt", "stt")]["units"] == 600
    assert lines[("tts", "tts")]["cost_known"] is True
    assert body["cost_total_usd"] == 0.15
    assert [t["e2e_ms"] for t in body["turn_latency"]] == [500, 700, 900, 1100, 2000]
    summary = by_key(body["latency_summary"])
    assert (summary["e2e"]["p50_ms"], summary["e2e"]["p95_ms"]) == (900, 2000)
    assert summary["stt"]["n"] == 5
    assert summary["llm_ttft"] == {"key": "llm_ttft", "n": 0, "p50_ms": None, "p95_ms": None}

    other = (await admin.get(f"/admin/sessions/{seed.sessions['s3_brief'].id}")).json()
    assert other["cost_breakdown"] == []
    assert other["cost_total_usd"] is None
    assert other["latency_summary"] == []
    assert other["session"]["failure_kind"] == "brief_failed"


# --- Health and metrics (OB-10) ---------------------------------------------------------------


async def test_ob10_health_tiles_and_host_sparklines(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    await seed_all(sessionmaker)
    body = (await admin.get("/admin/ops/health")).json()
    tiles = by_key(body["tiles"])
    assert {k: t["status"] for k, t in tiles.items()} == {
        "api": "up",
        "worker": "up",
        "voice": "down",
        "postgres": "up",
        "redis": "down",
        "litellm": "degraded",
        "livekit": "unknown",
        "stt": "unknown",
        "tts": "unknown",
        "smtp": "unknown",
        "stripe": "unknown",
    }
    assert tiles["worker"]["version"] == "1.2.3"
    assert tiles["worker"]["instances"][0]["instance"] == "w1"
    assert tiles["postgres"]["latency_ms"] == 3.5
    host = {h["label"]: h for h in body["host"]}
    root = host["Disk (root)"]
    assert root["latest"] == 50
    assert [p["value"] for p in root["points"]] == [40, 50]
    assert host["Disk (pgdata)"]["latest"] == 70
    assert host["Memory"]["latest"] == 61
    assert body["redis_error"] is None


async def test_ob10_health_when_redis_is_down(
    admin: httpx.AsyncClient, app: FastAPI, sessionmaker: Maker
) -> None:
    class Broken(FakeRedis):
        async def scan_iter(self, match: str = "*", count: int = 100) -> AsyncIterator[bytes]:
            raise ConnectionError("down")
            yield b""

    app.state.ops_redis = Broken()
    body = (await admin.get("/admin/ops/health")).json()
    assert body["redis_error"] == "Redis: ConnectionError"
    tiles = by_key(body["tiles"])
    assert tiles["worker"]["status"] == "unknown"
    assert tiles["api"]["status"] == "up"


async def test_ob10_metric_series_with_label_filter(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    await seed_all(sessionmaker)
    resp = await admin.get(
        "/admin/ops/metrics", params={"metric": "host.disk_pct", "labels": "mount:root"}
    )
    series = resp.json()
    assert len(series) == 1
    assert series[0]["labels"] == {"mount": "root"}
    assert [(p["t"][11:16], p["value"]) for p in series[0]["points"]] == [
        ("10:30", 40),
        ("11:45", 50),
    ]
    both = (await admin.get("/admin/ops/metrics", params={"metric": "host.disk_pct"})).json()
    assert [s["labels"]["mount"] for s in both] == ["pgdata", "root"]
    bad = await admin.get("/admin/ops/metrics", params={"metric": "x", "labels": "nolabel"})
    assert bad.status_code == 422


# --- Performance (OB-11) ----------------------------------------------------------------------


async def test_ob11_voice_and_llm_latency(admin: httpx.AsyncClient, sessionmaker: Maker) -> None:
    await seed_all(sessionmaker)
    body = (await admin.get("/admin/ops/performance", params={"range": "7d"})).json()
    voice = by_key(body["voice"])
    assert (voice["e2e"]["n"], voice["e2e"]["p50_ms"], voice["e2e"]["p95_ms"]) == (5, 900, 2000)
    assert voice["stt"]["p50_ms"] == 102
    assert voice["tts_ttfb"]["n"] == 0
    e2e = by_key(body["voice_series"])["e2e"]["points"]
    assert len(e2e) == 1
    assert e2e[0]["n"] == 5
    llm = by_key(body["llm"])
    assert (llm["all"]["n"], llm["all"]["p50_ms"], llm["all"]["p95_ms"]) == (3, 600, 1000)
    assert (llm["say"]["p50_ms"], llm["say"]["p95_ms"]) == (400, 600)
    assert llm["decide"]["p50_ms"] == 1000
    assert body["queue_wait"]["measured"] is False
    assert body["llm_other_roles"]["measured"] is False


# --- Errors (OB-12) ---------------------------------------------------------------------------


async def test_ob12_error_inbox_sparkline_and_resolve(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    seed = await seed_all(sessionmaker)
    groups = (await admin.get("/admin/ops/errors")).json()
    assert [g["fingerprint"] for g in groups] == ["f1"]
    g1 = groups[0]
    assert g1["events_24h"] == 3
    assert len(g1["sparkline"]) == 24
    assert g1["sparkline"][22] == 2
    assert g1["sparkline"][20] == 1
    every = (await admin.get("/admin/ops/errors", params={"status": "all"})).json()
    assert [g["fingerprint"] for g in every] == ["f1", "f2"]

    gid = seed.errors["g1"].id
    detail = (await admin.get(f"/admin/ops/errors/{gid}")).json()
    assert detail["sample_stack"] == "Traceback ..."
    assert len(detail["events"]) == 4
    assert detail["daily"][13] == 3
    assert detail["daily"][10] == 1

    body = {"status": "resolved", "reason": "fixed in 1.2.4"}
    assert (await admin.patch(f"/admin/ops/errors/{gid}", json=body)).status_code == 403
    done = await admin.patch(f"/admin/ops/errors/{gid}", json=body, headers=WRITE)
    assert done.status_code == 200
    assert done.json()["group"]["status"] == "resolved"
    assert done.json()["group"]["resolved_by"] == ADMIN
    again = await admin.patch(
        f"/admin/ops/errors/{gid}", json={"status": "open", "reason": "still seen"}, headers=WRITE
    )
    assert again.json()["group"]["status"] == "open"
    assert again.json()["group"]["resolved_by"] is None
    async with sessionmaker() as db:
        rows = list(
            await db.scalars(select(AuditLog).where(AuditLog.entity == f"error_group:{gid}"))
        )
    assert sorted(r.action for r in rows) == ["ops.error_reopened", "ops.error_resolved"]
    assert all(r.actor == ADMIN for r in rows)
    assert {r.details_json["reason"] for r in rows if r.details_json} == {
        "fixed in 1.2.4",
        "still seen",
    }
    missing = await admin.get(f"/admin/ops/errors/{uuid.uuid4()}")
    assert missing.status_code == 404


# --- Jobs (OB-13) -----------------------------------------------------------------------------


async def test_ob13_jobs_lists_failed_and_stuck(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    seed = await seed_all(sessionmaker)
    body = (await admin.get("/admin/ops/jobs")).json()
    assert body["queue_depth"]["value"] == 3
    gaps = {g["id"]: g for g in body["gap_analyses"]}
    assert set(gaps) == {str(seed.gaps["g3_failed"].id), str(seed.gaps["g4_stuck"].id)}
    assert gaps[str(seed.gaps["g3_failed"].id)]["state"] == "failed"
    assert gaps[str(seed.gaps["g3_failed"].id)]["reason"] == "The job posting is not ready yet."
    assert gaps[str(seed.gaps["g4_stuck"].id)]["state"] == "stuck"
    assert gaps[str(seed.gaps["g4_stuck"].id)]["user_email"] == "u4@example.com"
    scorings = {s["id"]: s for s in body["scorings"]}
    assert set(scorings) == {str(seed.sessions["s5_stuck"].id), str(seed.sessions["s6_scoring"].id)}
    assert scorings[str(seed.sessions["s5_stuck"].id)]["state"] == "stuck"
    assert scorings[str(seed.sessions["s6_scoring"].id)]["retryable"] is True
    assert body["jobs_paused"] == []
    # D-8: no gap analysis content in the payload.
    assert "breakdown" not in json.dumps(body)


async def test_ob13_retry_reenqueues_the_same_jobs_and_is_audited(
    admin: httpx.AsyncClient, sessionmaker: Maker, queue: InlineQueue
) -> None:
    seed = await seed_all(sessionmaker)
    queue.run_jobs = False
    reason = {"reason": "provider outage over"}
    sid = seed.sessions["s6_scoring"].id
    no_header = await admin.post(f"/admin/ops/jobs/scoring/{sid}/retry", json=reason)
    assert no_header.status_code == 403
    resp = await admin.post(f"/admin/ops/jobs/scoring/{sid}/retry", json=reason, headers=WRITE)
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "scoring"
    function, job_id, kwargs = queue.enqueued[-1]
    assert function == "score_session"
    assert job_id == resp.json()["job_id"]
    assert kwargs == {"session_id": str(sid), "org_id": str(seed.sessions["s6_scoring"].org_id)}

    gid = seed.gaps["g3_failed"].id
    resp = await admin.post(f"/admin/ops/jobs/gap_analysis/{gid}/retry", json=reason, headers=WRITE)
    assert resp.status_code == 202, resp.text
    function, job_id, kwargs = queue.enqueued[-1]
    assert function == "run_gap_analysis_job"
    assert job_id.startswith(f"ga:{gid}:retry:")
    assert kwargs["gap_analysis_id"] == str(gid)
    async with sessionmaker() as db:
        gap = await db.get(GapAnalysis, gid)
        assert gap is not None and gap.status == GapStatus.RUNNING and gap.error is None
        audits = list(await db.scalars(select(AuditLog).where(AuditLog.action == "ops.job_retry")))
    assert sorted(a.entity for a in audits) == sorted([f"session:{sid}", f"gap_analysis:{gid}"])
    assert all(a.details_json and a.details_json["reason"] == reason["reason"] for a in audits)

    done = seed.sessions["s1"].id
    conflict = await admin.post(f"/admin/ops/jobs/scoring/{done}/retry", json=reason, headers=WRITE)
    assert conflict.status_code == 409
    ready = seed.gaps["g1"].id
    conflict = await admin.post(
        f"/admin/ops/jobs/gap_analysis/{ready}/retry", json=reason, headers=WRITE
    )
    assert conflict.status_code == 409
    missing = await admin.post(
        f"/admin/ops/jobs/scoring/{uuid.uuid4()}/retry", json=reason, headers=WRITE
    )
    assert missing.status_code == 404


# --- Spend (OB-14, D-12) ----------------------------------------------------------------------


async def test_ob14_spend_against_the_cap_and_hosted_equivalent(
    admin: httpx.AsyncClient, sessionmaker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_all(sessionmaker)
    body = (await admin.get("/admin/ops/spend")).json()
    assert body["today_usd"] == 0.04
    assert body["month_usd"] == 0.77
    assert body["daily_cap_usd"] == 25.0
    assert body["cap_pct"] == 0.0016
    comp = by_key(body["by_component"])
    assert (comp["llm"]["today_usd"], comp["llm"]["month_usd"]) == (0.04, 0.72)
    assert by_key(body["by_role"])["planner"]["month_usd"] == 0.03
    assert [p["t"][:10] for p in body["daily"]] == [
        "2030-01-03",
        "2030-01-09",
        "2030-01-10",
        "2030-01-11",
        "2030-01-15",
    ]
    assert body["litellm"]["tracked"] is False
    hosted = body["hosted_equivalent"]
    assert hosted["configured"] is False
    assert "not configured" in hosted["reason"].lower()
    assert hosted["stt_seconds"] == 600

    monkeypatch.setenv("SHADOW_STT_USD_PER_SECOND", "0.0001")
    hosted = (await admin.get("/admin/ops/spend")).json()["hosted_equivalent"]
    assert (hosted["configured"], hosted["stt_usd"], hosted["total_usd"]) == (True, 0.06, 0.06)
    assert hosted["tts_usd"] is None
