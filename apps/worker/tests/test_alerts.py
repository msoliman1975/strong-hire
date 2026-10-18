"""Alert engine (admin spec AL-1..AL-7): state machine, min_samples, mute, re-notify, send
failures, missing heartbeats, derived metrics, the default rules and the digest. A fake clock
(`now` passed per tick) and a fake email sender; samples are fixture ops_samples rows in the A3
metric catalog."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from arq.cron import CronJob
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core import runtime_settings as rs
from strong_core.db.models import (
    AlertEvent,
    AlertRule,
    ErrorGroup,
    InterviewSession,
    JobTarget,
    OpsSample,
    Subscription,
    UsageEvent,
    VoiceTurnTiming,
)
from strong_core.ops.alerts import DEFAULT_RULES, seed_default_rules
from strong_core.schemas import Difficulty, InterviewType, Mode
from strong_core.schemas.enums import (
    AlertAggregation,
    AlertComparator,
    AlertEventKind,
    AlertSeverity,
    AlertState,
    SessionStatus,
    SubscriptionStatus,
    UsageComponent,
)
from strong_worker.alerts import engine
from strong_worker.alerts.digest import build_digest
from strong_worker.alerts.engine import MUTED, NO_RECIPIENT, run_tick
from strong_worker.alerts.jobs import AlertsContext, alert_digest, evaluate_alerts, startup
from strong_worker.main import WorkerSettings

Maker = async_sessionmaker[AsyncSession]
T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
TO = "ops@example.com"
BASE = "https://admin.example.com"


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    async def send(self, to: str, subject: str, text: str) -> None:
        if self.fail:
            raise ConnectionError("SMTP is down")
        self.sent.append((to, subject, text))

    @property
    def subjects(self) -> list[str]:
        return [s for _, s, _ in self.sent]


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    rs.clear_cache()


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


async def tick(maker: Maker, sender: FakeSender, minutes: float, to: str = TO) -> engine.TickResult:
    return await run_tick(maker, sender, now=at(minutes), to=to, admin_base_url=BASE)


async def add_rule(maker: Maker, **changes: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "name": "Disk filling",
        "metric": "host.disk_pct",
        "aggregation": AlertAggregation.LAST,
        "window_s": 300,
        "comparator": AlertComparator.GT,
        "threshold": 85.0,
        "min_samples": 1,
        "for_s": 0,
        "severity": AlertSeverity.CRITICAL,
        "renotify_s": None,
        **changes,
    }
    async with maker() as db:
        rule = AlertRule(**values)
        db.add(rule)
        await db.commit()
        return rule.id


async def sample(
    maker: Maker, minutes: float, value: float, metric: str = "host.disk_pct", **labels: str
) -> None:
    async with maker() as db:
        db.add(OpsSample(ts=at(minutes), metric=metric, value=value, labels_json=labels or None))
        await db.commit()


async def rule_row(maker: Maker, rule_id: uuid.UUID) -> AlertRule:
    async with maker() as db:
        rule = await db.get(AlertRule, rule_id)
        assert rule is not None
        return rule


async def events(maker: Maker) -> list[AlertEvent]:
    async with maker() as db:
        return list(await db.scalars(select(AlertEvent).order_by(AlertEvent.at)))


# --- state machine -------------------------------------------------------------------------


async def test_al2_ok_pending_firing_after_for_s_then_resolved(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(sessionmaker, for_s=120)
    await sample(sessionmaker, 0, 90)
    await tick(sessionmaker, sender, 0)
    rule = await rule_row(sessionmaker, rule_id)
    assert rule.state == AlertState.PENDING and rule.last_value == 90
    assert sender.sent == []

    await sample(sessionmaker, 1, 91)
    await tick(sessionmaker, sender, 1)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.PENDING

    await sample(sessionmaker, 2, 92)
    await tick(sessionmaker, sender, 2)
    rule = await rule_row(sessionmaker, rule_id)
    assert rule.state == AlertState.FIRING
    assert sender.subjects == ["[Strong Hire][CRITICAL] Disk filling firing"]
    to, _, body = sender.sent[0]
    assert to == TO
    assert "Value:     92 %" in body and "Threshold: > 85 %" in body
    assert "Since:     2026-10-18 12:00 UTC" in body
    assert f"{BASE}/alerts" in body

    await sample(sessionmaker, 3, 50)
    await tick(sessionmaker, sender, 3)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.OK
    assert sender.subjects[-1] == "[Strong Hire][CRITICAL] Disk filling resolved"
    assert "Since:     2026-10-18 12:02 UTC" in sender.sent[-1][2]
    kinds = [(e.kind, e.notified) for e in await events(sessionmaker)]
    assert kinds == [(AlertEventKind.FIRED, True), (AlertEventKind.RESOLVED, True)]


async def test_al2_pending_that_clears_goes_back_to_ok_without_events(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(sessionmaker, for_s=600)
    await sample(sessionmaker, 0, 90)
    await tick(sessionmaker, sender, 0)
    await sample(sessionmaker, 1, 10)
    await tick(sessionmaker, sender, 1)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.OK
    assert await events(sessionmaker) == [] and sender.sent == []


async def test_al2_for_s_zero_fires_on_the_first_tick(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(sessionmaker)
    await sample(sessionmaker, 0, 99)
    await tick(sessionmaker, sender, 0)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING
    assert len(sender.sent) == 1


async def test_al1_min_samples_not_met_changes_nothing(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(sessionmaker, aggregation=AlertAggregation.AVG, min_samples=3)
    await sample(sessionmaker, 0, 99)
    await sample(sessionmaker, 1, 99)
    await tick(sessionmaker, sender, 1)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.OK
    await sample(sessionmaker, 2, 99)
    await tick(sessionmaker, sender, 2)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING
    # No data at all later on: a firing rule stays firing, no resolved email.
    await tick(sessionmaker, sender, 30)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING
    assert len(sender.sent) == 1


async def test_al1_disabled_rules_are_not_evaluated(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(sessionmaker, enabled=False)
    await sample(sessionmaker, 0, 99)
    result = await tick(sessionmaker, sender, 0)
    assert result.evaluated == 0
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.OK


async def test_al1_aggregations_avg_p95_count_rate(sessionmaker: Maker, sender: FakeSender) -> None:
    for minute, value in enumerate((10, 20, 30, 40)):
        await sample(sessionmaker, minute, value, "queue.depth", queue="arq:queue")
    ids = {
        agg: await add_rule(
            sessionmaker,
            name=f"q {agg}",
            metric="queue.depth",
            aggregation=agg,
            threshold=1e9,
        )
        for agg in AlertAggregation
    }
    await tick(sessionmaker, sender, 3)
    got = {agg: (await rule_row(sessionmaker, rid)).last_value for agg, rid in ids.items()}
    assert got[AlertAggregation.LAST] == 40
    assert got[AlertAggregation.AVG] == 25
    assert got[AlertAggregation.P95] == 40
    assert got[AlertAggregation.COUNT] == 4
    assert got[AlertAggregation.RATE] == pytest.approx(30 / 180)


async def test_al1_worst_series_counts_and_labels_filter(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    any_mount = await add_rule(sessionmaker, name="any")
    root_only = await add_rule(sessionmaker, name="root", labels_json={"mount": "root"})
    await sample(sessionmaker, 0, 50, mount="root")
    await sample(sessionmaker, 0, 97, mount="pgdata")
    await tick(sessionmaker, sender, 0)
    assert (await rule_row(sessionmaker, any_mount)).state == AlertState.FIRING
    assert (await rule_row(sessionmaker, any_mount)).last_value == 97
    assert (await rule_row(sessionmaker, root_only)).state == AlertState.OK


# --- re-notify, mute, failures -------------------------------------------------------------


async def test_al3_renotify_while_firing(sessionmaker: Maker, sender: FakeSender) -> None:
    await add_rule(sessionmaker, renotify_s=3600, window_s=24 * 3600)
    await sample(sessionmaker, 0, 99)
    await tick(sessionmaker, sender, 0)
    await tick(sessionmaker, sender, 30)
    assert len(sender.sent) == 1
    await tick(sessionmaker, sender, 60)
    assert len(sender.sent) == 2
    assert sender.subjects[1] == "[Strong Hire][CRITICAL] Disk filling firing"
    await tick(sessionmaker, sender, 61)
    await tick(sessionmaker, sender, 120)
    assert len(sender.sent) == 3


async def test_al3_renotify_null_never_resends(sessionmaker: Maker, sender: FakeSender) -> None:
    await add_rule(sessionmaker, renotify_s=None, window_s=7 * 24 * 3600)
    await sample(sessionmaker, 0, 99)
    for minutes in (0, 60, 24 * 60, 3 * 24 * 60):
        await tick(sessionmaker, sender, minutes)
    assert len(sender.sent) == 1


async def test_al4_muted_rule_changes_state_but_sends_nothing_until_mute_ends(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(sessionmaker, muted_until=at(30), window_s=3600)
    await sample(sessionmaker, 0, 99)
    await tick(sessionmaker, sender, 0)
    rule = await rule_row(sessionmaker, rule_id)
    assert rule.state == AlertState.FIRING and sender.sent == []
    [event] = await events(sessionmaker)
    assert event.kind == AlertEventKind.FIRED and not event.notified
    assert event.notify_error == MUTED

    await tick(sessionmaker, sender, 10)
    assert sender.sent == []  # muted events are never retried
    await tick(sessionmaker, sender, 31)  # mute over, still firing: one email now
    assert sender.subjects == ["[Strong Hire][CRITICAL] Disk filling firing"]
    await tick(sessionmaker, sender, 32)
    assert len(sender.sent) == 1


async def test_al4_resolved_while_muted_is_not_sent(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    await add_rule(sessionmaker, muted_until=at(30))
    await sample(sessionmaker, 0, 99)
    await tick(sessionmaker, sender, 0)
    await sample(sessionmaker, 1, 10)
    await tick(sessionmaker, sender, 1)
    await tick(sessionmaker, sender, 40)
    assert sender.sent == []
    assert [e.kind for e in await events(sessionmaker)] == [
        AlertEventKind.FIRED,
        AlertEventKind.RESOLVED,
    ]


async def test_al5_send_failure_is_stored_and_retried_next_tick(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    await add_rule(sessionmaker, window_s=3600)
    await sample(sessionmaker, 0, 99)
    sender.fail = True
    result = await tick(sessionmaker, sender, 0)
    assert result.failed == 1
    [event] = await events(sessionmaker)
    assert not event.notified and event.notify_error == "ConnectionError: SMTP is down"

    sender.fail = False
    result = await tick(sessionmaker, sender, 1)
    assert result.sent == 1 and result.events == 0
    [event] = await events(sessionmaker)
    assert event.notified and event.notify_error is None
    assert len(sender.sent) == 1
    await tick(sessionmaker, sender, 2)
    assert len(sender.sent) == 1


async def test_d10_without_alert_email_the_event_waits(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    await add_rule(sessionmaker)
    await sample(sessionmaker, 0, 99)
    await tick(sessionmaker, sender, 0, to="")
    [event] = await events(sessionmaker)
    assert not event.notified and event.notify_error == NO_RECIPIENT
    await tick(sessionmaker, sender, 1)
    assert len(sender.sent) == 1 and sender.sent[0][0] == TO


async def test_al2_lock_held_elsewhere_skips_the_tick(
    sessionmaker: Maker, sender: FakeSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_lock(db: AsyncSession) -> bool:
        return False

    monkeypatch.setattr(engine, "_try_lock", no_lock)
    await add_rule(sessionmaker)
    await sample(sessionmaker, 0, 99)
    result = await tick(sessionmaker, sender, 0)
    assert result.skipped and sender.sent == [] and await events(sessionmaker) == []


async def test_al2_broken_rule_does_not_stop_the_others(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    await add_rule(sessionmaker, name="broken", metric="no.such.metric")
    good = await add_rule(sessionmaker, name="good")
    await sample(sessionmaker, 0, 99)
    result = await tick(sessionmaker, sender, 0)
    assert result.errors and "broken" in result.errors[0]
    assert (await rule_row(sessionmaker, good)).state == AlertState.FIRING


# --- missing heartbeat ---------------------------------------------------------------------


async def test_ob1_missing_heartbeat_counts_as_down(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(
        sessionmaker,
        name="Worker or voice down",
        metric="heartbeat.up",
        comparator=AlertComparator.LT,
        threshold=1,
        window_s=120,
        for_s=120,
        labels_json={"service": ["worker", "voice"]},
    )
    for minute in (0, 1, 2):
        await sample(sessionmaker, minute, 1, "heartbeat.up", service="worker")
    # No voice sample at all: voice is down.
    await tick(sessionmaker, sender, 0)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.PENDING
    await tick(sessionmaker, sender, 2)
    rule = await rule_row(sessionmaker, rule_id)
    assert rule.state == AlertState.FIRING and rule.last_value == 0
    assert sender.subjects == ["[Strong Hire][CRITICAL] Worker or voice down firing"]


async def test_ob1_no_samples_at_all_for_an_up_metric_is_down(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    rule_id = await add_rule(
        sessionmaker,
        name="Dependency down",
        metric="probe.up",
        comparator=AlertComparator.LT,
        threshold=1,
    )
    await tick(sessionmaker, sender, 0)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING
    await sample(sessionmaker, 1, 1, "probe.up", dep="postgres")
    await sample(sessionmaker, 1, 0, "probe.up", dep="redis")
    await tick(sessionmaker, sender, 1)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING
    await sample(sessionmaker, 2, 1, "probe.up", dep="redis")
    await tick(sessionmaker, sender, 2)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.OK


# --- derived metrics -----------------------------------------------------------------------


async def _sessions(
    maker: Maker,
    account: tuple[uuid.UUID, uuid.UUID],
    statuses: list[SessionStatus],
    ended: datetime,
) -> None:
    org_id, user_id = account
    async with maker() as db:
        job = JobTarget(org_id=org_id, user_id=user_id, raw_text="Engineer")
        db.add(job)
        await db.flush()
        for status in statuses:
            db.add(
                InterviewSession(
                    org_id=org_id,
                    job_target_id=job.id,
                    type=InterviewType.BEHAVIORAL,
                    difficulty=Difficulty.REALISTIC,
                    mode=Mode.REALISTIC,
                    duration_min=30,
                    status=status,
                    started_at=ended - timedelta(minutes=30),
                    ended_at=ended,
                )
            )
        await db.commit()


async def test_al2_session_failure_rate_with_minimum_sessions(
    sessionmaker: Maker, sender: FakeSender, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    [spec] = [r for r in DEFAULT_RULES if r.name == "Session failures"]
    async with sessionmaker() as db:
        db.add(spec.row())
        await db.commit()
    await _sessions(sessionmaker, account, [SessionStatus.FAILED, SessionStatus.COMPLETED], at(-10))
    await tick(sessionmaker, sender, 0)
    async with sessionmaker() as db:
        rule = await db.scalar(select(AlertRule))
    assert rule is not None and rule.state == AlertState.OK  # 2 sessions < 5
    await _sessions(sessionmaker, account, [SessionStatus.COMPLETED] * 3, at(-5))
    await tick(sessionmaker, sender, 1)
    async with sessionmaker() as db:
        rule = await db.scalar(select(AlertRule))
    assert rule is not None and rule.state == AlertState.FIRING
    assert rule.last_value == pytest.approx(20.0)


async def test_al2_scoring_stuck_and_voice_p95(
    sessionmaker: Maker, sender: FakeSender, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    stuck = await add_rule(
        sessionmaker,
        name="Scoring stuck",
        metric="sessions.scoring_stuck",
        aggregation=AlertAggregation.COUNT,
        threshold=0,
    )
    slow = await add_rule(
        sessionmaker,
        name="Voice slow",
        metric="voice.e2e_p95_ms",
        aggregation=AlertAggregation.P95,
        window_s=1800,
        threshold=1500,
        min_samples=20,
    )
    await _sessions(sessionmaker, account, [SessionStatus.SCORING], at(-10))
    await tick(sessionmaker, sender, 0)
    assert (await rule_row(sessionmaker, stuck)).state == AlertState.OK  # only 10 min
    await tick(sessionmaker, sender, 6)
    assert (await rule_row(sessionmaker, stuck)).state == AlertState.FIRING

    org_id, _ = account
    async with sessionmaker() as db:
        session_id = await db.scalar(select(InterviewSession.id))
        for i in range(20):
            db.add(
                VoiceTurnTiming(
                    org_id=org_id,
                    session_id=session_id,
                    turn_index=i,
                    e2e_ms=2000 if i >= 18 else 800,
                    created_at=at(0),
                )
            )
        await db.commit()
    await tick(sessionmaker, sender, 7)
    rule = await rule_row(sessionmaker, slow)
    assert rule.last_value == 2000 and rule.state == AlertState.FIRING


async def test_d6_spend_cap_pct_against_the_runtime_cap(
    sessionmaker: Maker, sender: FakeSender, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    rule_id = await add_rule(
        sessionmaker,
        name="Spend high",
        metric="spend.cap_pct",
        comparator=AlertComparator.GTE,
        threshold=80,
        severity=AlertSeverity.WARNING,
    )
    org_id, _ = account
    async with sessionmaker() as db:
        for cost, when in ((Decimal("19"), at(-60)), (Decimal("5"), at(-13 * 60))):  # yesterday
            db.add(
                UsageEvent(
                    org_id=org_id,
                    component=UsageComponent.LLM,
                    units=Decimal(1),
                    cost_usd=cost,
                    created_at=when,
                )
            )
        await db.commit()
    await tick(sessionmaker, sender, 0)
    rule = await rule_row(sessionmaker, rule_id)
    assert rule.last_value == pytest.approx(19 / 25 * 100)  # D-6: $25 default cap
    assert rule.state == AlertState.OK
    async with sessionmaker() as db:
        await rs.set(db, rs.SettingKey.DAILY_SPEND_CAP_USD, 20, actor="admin@example.com")
        await db.commit()
    await tick(sessionmaker, sender, 1)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING
    assert sender.subjects == ["[Strong Hire][WARNING] Spend high firing"]


async def test_al2_new_error_group(sessionmaker: Maker, sender: FakeSender) -> None:
    rule_id = await add_rule(
        sessionmaker,
        name="New error",
        metric="errors.new_groups",
        aggregation=AlertAggregation.COUNT,
        window_s=600,
        threshold=0,
    )
    async with sessionmaker() as db:
        db.add(
            ErrorGroup(
                fingerprint="f" * 64,
                service="api",
                exception_type="ValueError",
                message="bad",
                first_seen=at(-1),
                last_seen=at(-1),
            )
        )
        await db.commit()
    await tick(sessionmaker, sender, 0)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING
    await tick(sessionmaker, sender, 10)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.OK


async def test_al2_stripe_silent_only_with_active_paid_subscriptions(
    sessionmaker: Maker, sender: FakeSender, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    rule_id = await add_rule(
        sessionmaker,
        name="Stripe silent",
        metric="stripe.webhook_age_s",
        threshold=48 * 3600,
        window_s=900,
    )
    await sample(sessionmaker, 0, 50 * 3600, "stripe.webhook_age_s")
    await tick(sessionmaker, sender, 0)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.OK
    org_id, user_id = account
    async with sessionmaker() as db:
        db.add(
            Subscription(
                org_id=org_id,
                user_id=user_id,
                status=SubscriptionStatus.ACTIVE,
                stripe_subscription_id="sub_1",
            )
        )
        await db.commit()
    await tick(sessionmaker, sender, 1)
    assert (await rule_row(sessionmaker, rule_id)).state == AlertState.FIRING


# --- default rules, jobs, digest ------------------------------------------------------------


async def test_al1_default_rules_seeded_once_and_edits_kept(sessionmaker: Maker) -> None:
    async with sessionmaker() as db:
        assert await seed_default_rules(db) == len(DEFAULT_RULES) == 13
    async with sessionmaker() as db:
        rule = await db.scalar(select(AlertRule).where(AlertRule.name == "Disk filling"))
        assert rule is not None and rule.threshold == 85 and rule.renotify_s == 24 * 3600
        rule.threshold = 70
        await db.commit()
    await startup({"alerts": AlertsContext(sessionmaker=sessionmaker, sender=FakeSender())})
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(AlertRule)) == 13
        rule = await db.scalar(select(AlertRule).where(AlertRule.name == "Disk filling"))
        assert rule is not None and rule.threshold == 70
        spend = await db.scalar(select(AlertRule).where(AlertRule.name == "Spend high"))
        assert spend is not None and spend.metric == "spend.cap_pct" and spend.threshold == 80
        new_error = await db.scalar(select(AlertRule).where(AlertRule.name == "New error"))
        assert new_error is not None and new_error.renotify_s is None


async def test_al1_default_rules_evaluate_without_errors(
    sessionmaker: Maker, sender: FakeSender
) -> None:
    async with sessionmaker() as db:
        await seed_default_rules(db)
    result = await tick(sessionmaker, sender, 0)
    assert result.errors == [] and result.evaluated == 13


def test_al2_cron_runs_every_minute() -> None:
    jobs = {job.name: job for job in WorkerSettings.cron_jobs if isinstance(job, CronJob)}
    job = jobs["cron:evaluate_alerts"]
    assert job.minute is None and job.second == 0 and job.unique
    assert "cron:alert_digest" in jobs


async def test_al2_cron_job_uses_alert_email(
    sessionmaker: Maker, sender: FakeSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strong_core.config import get_settings

    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    get_settings.cache_clear()
    await add_rule(sessionmaker)
    await sample(sessionmaker, 0, 99)
    ctx = {"alerts": AlertsContext(sessionmaker=sessionmaker, sender=sender, clock=lambda: at(0))}
    out = await evaluate_alerts(ctx)
    assert out["sent"] == 1 and sender.sent[0][0] == "ops@example.com"
    assert "/alerts" in sender.sent[0][2]


async def test_al7_digest_off_by_default_and_body_when_on(
    sessionmaker: Maker, sender: FakeSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strong_core.config import get_settings

    ctx = {"alerts": AlertsContext(sessionmaker=sessionmaker, sender=sender, clock=lambda: at(0))}
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    get_settings.cache_clear()
    assert await alert_digest(ctx) == {"sent": False}
    monkeypatch.setenv("ALERT_DIGEST", "true")
    get_settings.cache_clear()
    await add_rule(sessionmaker)
    await sample(sessionmaker, 0, 99)
    await tick(sessionmaker, sender, 0)
    sender.sent.clear()
    assert await alert_digest(ctx) == {"sent": True}
    [(to, subject, body)] = sender.sent
    assert to == "ops@example.com" and subject == "[Strong Hire] Daily digest 2026-10-17"
    assert "Open alerts (1):" in body and "Disk filling" in body
    async with sessionmaker() as db:
        _, again = await build_digest(db, at(0), BASE)
    assert "New error groups (0):" in again
