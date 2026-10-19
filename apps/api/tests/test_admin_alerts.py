"""Admin alerts API (AL-1, AL-4, AL-6): rules CRUD with metric validation, mute, test email,
history, AA-5/AA-6 on every write."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.auth.settings import get_auth_settings
from strong_api.main import create_app
from strong_core.config import get_settings
from strong_core.db.models import AlertEvent, AlertRule, AuditLog
from strong_core.ops.alerts import seed_default_rules
from strong_core.schemas.enums import AlertEventKind, AlertState

from .conftest import InlineQueue, sign_in, sign_in_admin

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
H = {"X-Admin-Request": "1"}
RULE: dict[str, Any] = {
    "reason": "watch the queue",
    "name": "Queue backed up",
    "metric": "queue.depth",
    "labels": {"queue": "arq:queue"},
    "aggregation": "avg",
    "window_s": 600,
    "comparator": "gt",
    "threshold": 50,
    "severity": "warning",
    "for_s": 300,
    "renotify_s": 86400,
}


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    async def send(self, to: str, subject: str, text: str) -> None:
        if self.fail:
            raise ConnectionError("SMTP is down")
        self.sent.append((to, subject, text))


async def _ok() -> None:
    return None


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def app(
    sessionmaker: Maker, queue: InlineQueue, sender: FakeSender, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setenv("ADMIN_BASE_URL", "https://admin.example.com")
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    app = create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    app.state.alert_email_sender = sender
    yield app
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, ADMIN)  # the admin's candidate account
        await sign_in_admin(http, app, ADMIN)  # AA-4: the admin session
        yield http


async def _create(admin: httpx.AsyncClient, **changes: Any) -> dict[str, Any]:
    r = await admin.post("/admin/alerts/rules", json={**RULE, **changes}, headers=H)
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_aa4_alert_routes_are_404_for_non_admins(
    anon_client: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    for http in (anon_client, client):
        assert (await http.get("/admin/alerts/rules")).status_code == 404
        assert (await http.get("/admin/alerts/events")).status_code == 404
        r = await http.post("/admin/alerts/rules", json=RULE, headers=H)
        assert r.status_code == 404


async def test_al1_metrics_catalog(admin: httpx.AsyncClient) -> None:
    metrics = {m["name"]: m for m in (await admin.get("/admin/alerts/metrics")).json()}
    assert metrics["heartbeat.up"]["up"] and metrics["heartbeat.up"]["labels"] == ["service"]
    assert metrics["spend.cap_pct"]["derived"] and metrics["spend.cap_pct"]["aggregation"] == "last"
    assert "sessions.failure_rate" in metrics and "stripe.webhook_age_s" in metrics


async def test_al1_create_list_update_with_audit(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    created = await _create(admin)
    assert created["state"] == "ok" and created["is_default"] is False
    assert created["labels"] == {"queue": "arq:queue"}
    rules = (await admin.get("/admin/alerts/rules")).json()
    assert [r["name"] for r in rules] == ["Queue backed up"]

    r = await admin.patch(
        f"/admin/alerts/rules/{created['id']}",
        json={"reason": "less noise", "threshold": 80, "renotify_s": None, "labels": None},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert r.json()["threshold"] == 80 and r.json()["renotify_s"] is None
    assert r.json()["labels"] is None
    async with sessionmaker() as db:
        rows = list(
            await db.scalars(
                select(AuditLog).where(AuditLog.action.like("alert_rule.%")).order_by(AuditLog.at)
            )
        )
    assert [a.action for a in rows] == ["alert_rule.create", "alert_rule.update"]
    update = rows[1].details_json
    assert update["reason"] == "less noise"
    assert update["before"]["threshold"] == 50 and update["after"]["threshold"] == 80


async def test_al1_metric_names_and_labels_are_validated(admin: httpx.AsyncClient) -> None:
    for bad in (
        {"metric": "no.such.metric"},
        {"labels": {"nope": "x"}},
        {"metric": "spend.cap_pct", "labels": None, "aggregation": "avg"},
        {"window_s": 10},
        {"renotify_s": 5},
        {"unknown_field": 1},
    ):
        r = await admin.post("/admin/alerts/rules", json={**RULE, **bad}, headers=H)
        assert r.status_code == 422, (bad, r.text)
    await _create(admin)
    r = await admin.post("/admin/alerts/rules", json=RULE, headers=H)
    assert r.status_code == 409


async def test_aa5_aa6_writes_need_header_and_reason(admin: httpx.AsyncClient) -> None:
    assert (await admin.post("/admin/alerts/rules", json=RULE)).status_code == 403
    no_reason = {k: v for k, v in RULE.items() if k != "reason"}
    assert (await admin.post("/admin/alerts/rules", json=no_reason, headers=H)).status_code == 422


async def test_al1_disabling_a_firing_rule_resets_it(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    created = await _create(admin)
    async with sessionmaker() as db:
        rule = await db.get(AlertRule, uuid.UUID(created["id"]))
        assert rule is not None
        rule.state = AlertState.FIRING
        await db.commit()
    assert (await admin.get("/admin/alerts/rules")).json()[0]["state"] == "firing"
    r = await admin.patch(
        f"/admin/alerts/rules/{created['id']}",
        json={"reason": "noisy", "enabled": False},
        headers=H,
    )
    assert r.json()["enabled"] is False and r.json()["state"] == "ok"


async def test_al1_default_rules_cannot_be_deleted_or_renamed(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    async with sessionmaker() as db:
        await seed_default_rules(db)
    rules = (await admin.get("/admin/alerts/rules")).json()
    assert len(rules) == 13 and all(r["is_default"] for r in rules)
    disk = next(r for r in rules if r["name"] == "Disk filling")
    url = f"/admin/alerts/rules/{disk['id']}"
    r = await admin.request("DELETE", url, json={"reason": "do not need"}, headers=H)
    assert r.status_code == 409
    r = await admin.patch(url, json={"reason": "rename", "name": "Disk"}, headers=H)
    assert r.status_code == 409
    r = await admin.patch(url, json={"reason": "tighter", "threshold": 80}, headers=H)
    assert r.status_code == 200 and r.json()["threshold"] == 80

    custom = await _create(admin)
    url = f"/admin/alerts/rules/{custom['id']}"
    r = await admin.request("DELETE", url, json={"reason": "not needed"}, headers=H)
    assert r.status_code == 204
    assert (await admin.patch(url, json={"reason": "x" * 5}, headers=H)).status_code == 404


async def test_al4_mute_and_unmute(admin: httpx.AsyncClient) -> None:
    created = await _create(admin)
    url = f"/admin/alerts/rules/{created['id']}/mute"
    until = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
    r = await admin.post(url, json={"reason": "deploying", "until": until}, headers=H)
    assert r.status_code == 200 and r.json()["muted_until"] is not None
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    r = await admin.post(url, json={"reason": "deploying", "until": past}, headers=H)
    assert r.status_code == 422
    r = await admin.post(url, json={"reason": "done", "until": None}, headers=H)
    assert r.json()["muted_until"] is None


async def test_al6_test_alert_sends_email_and_writes_test_event(
    admin: httpx.AsyncClient, sender: FakeSender, sessionmaker: Maker
) -> None:
    created = await _create(admin, severity="critical")
    url = f"/admin/alerts/rules/{created['id']}/test"
    r = await admin.post(url, json={"reason": "check email"}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] is True and body["event"]["kind"] == "test"
    [(to, subject, text)] = sender.sent
    assert to == "ops@example.com"
    assert subject == "[Strong Hire][CRITICAL] Queue backed up test alert"
    assert "https://admin.example.com/alerts" in text

    sender.fail = True
    r = await admin.post(url, json={"reason": "check email"}, headers=H)
    assert r.json()["sent"] is False and "SMTP is down" in r.json()["error"]
    async with sessionmaker() as db:
        rows = list(await db.scalars(select(AlertEvent).order_by(AlertEvent.at)))
    assert [(e.kind, e.notified) for e in rows] == [
        (AlertEventKind.TEST, True),
        (AlertEventKind.TEST, False),
    ]


async def test_al4_events_history_filters(admin: httpx.AsyncClient, sessionmaker: Maker) -> None:
    a = await _create(admin)
    b = await _create(admin, name="Other")
    now = datetime.now(UTC)
    async with sessionmaker() as db:
        db.add_all(
            [
                AlertEvent(rule_id=uuid.UUID(a["id"]), kind=AlertEventKind.FIRED, value=60,
                           at=now - timedelta(days=2), notified=True),
                AlertEvent(rule_id=uuid.UUID(a["id"]), kind=AlertEventKind.RESOLVED, value=10,
                           at=now - timedelta(hours=1), notified=False, notify_error="boom"),
                AlertEvent(rule_id=uuid.UUID(b["id"]), kind=AlertEventKind.FIRED, value=70,
                           at=now - timedelta(minutes=5), notified=True),
            ]
        )  # fmt: skip
        await db.commit()
    events = (await admin.get("/admin/alerts/events")).json()
    assert [e["rule_name"] for e in events] == ["Other", "Queue backed up", "Queue backed up"]
    by_rule = (await admin.get("/admin/alerts/events", params={"rule_id": a["id"]})).json()
    assert len(by_rule) == 2
    fired = (await admin.get("/admin/alerts/events", params={"kind": "fired"})).json()
    assert {e["rule_name"] for e in fired} == {"Other", "Queue backed up"}
    since = (now - timedelta(days=1)).isoformat()
    recent = (await admin.get("/admin/alerts/events", params={"since": since})).json()
    assert len(recent) == 2 and recent[1]["notify_error"] == "boom"
