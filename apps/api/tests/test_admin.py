"""Admin area (R2): 404 for non-admins, consent gating, audit rows, costs, and the traces that the
text channel writes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.auth.settings import get_auth_settings
from strong_api.main import create_app
from strong_core.db.models import (
    AuditLog,
    InterviewerTrace,
    InterviewSession,
    UsageEvent,
    User,
)
from strong_core.schemas import InterviewType, Phase, UsageComponent

from .accounts_support import add_session
from .conftest import InlineQueue, sign_in
from .test_sessions_api import create, ready_job

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
ROUTES = ("/admin/users", "/admin/sessions", f"/admin/sessions/{uuid.uuid4()}", "/admin/audit")


async def _ok() -> None:
    return None


@pytest.fixture
def app(
    sessionmaker: Maker,
    queue: InlineQueue,
    export_store: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[FastAPI]:
    """The app with ADMIN_EMAILS set (mixed case and spaces, to check the parsing)."""
    monkeypatch.setenv("ADMIN_EMAILS", " Boss@Example.com , other-admin@example.com")
    get_auth_settings.cache_clear()
    app = create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    app.state.export_store = export_store
    yield app
    get_auth_settings.cache_clear()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, ADMIN)
        yield http


async def _user(maker: Maker, email: str) -> User:
    async with maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user


async def test_r2_admin_routes_are_404_for_everyone_else(
    anon_client: httpx.AsyncClient, client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    for path in ROUTES:
        assert (await anon_client.get(path)).status_code == 404, path
        assert (await client.get(path)).status_code == 404, path
    me = (await client.get("/auth/me")).json()
    assert me["user"]["is_admin"] is False
    boss = (await admin.get("/auth/me")).json()
    assert boss["user"]["is_admin"] is True
    assert (await admin.get("/admin/users")).status_code == 200


async def test_r2_users_page_lists_plan_consent_interviews_and_last_sign_in(
    client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker, "dev@example.com")
    async with sessionmaker() as db:
        await add_session(db, dev.org_id, dev.id)
    users = {u["email"]: u for u in (await admin.get("/admin/users")).json()}
    row = users["dev@example.com"]
    assert row["plan"] == "free" and row["minutes_used"] == 0
    assert row["training_consent"] is False
    assert row["interviews"] == 1
    assert row["last_sign_in_at"] is not None  # set at sign-up and sign-in
    assert row["is_admin"] is False
    assert users[ADMIN]["is_admin"] is True and users[ADMIN]["interviews"] == 0


async def test_r2_consent_gates_transcript_and_traces_and_views_are_audited(
    client: httpx.AsyncClient,
    admin: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: InlineQueue,
    sessionmaker: Maker,
) -> None:
    """A whole text session writes traces; the admin sees them only while consent is on."""
    job = await ready_job(client, fake_fixtures)
    sid = (await create(client, job["id"], channel="text")).json()["id"]
    await client.post(f"/sessions/{sid}/text/open")
    queue.run_jobs = False
    for answer in ("Happy to be here.", "Sounds good.", "I led the rollout.", "I led it again."):
        await client.post(f"/sessions/{sid}/text/turn", json={"text": answer})
    assert (await client.post(f"/sessions/{sid}/end")).status_code == 200

    # The text channel wrote one trace row per interviewer call, with move and reason.
    async with sessionmaker() as db:
        rows = list(
            await db.scalars(
                select(InterviewerTrace)
                .where(InterviewerTrace.session_id == uuid.UUID(sid))
                .order_by(InterviewerTrace.seq)
            )
        )
        usage = await db.scalar(
            select(UsageEvent).where(
                UsageEvent.session_id == uuid.UUID(sid),
                UsageEvent.component == UsageComponent.LLM,
            )
        )
    moves = [r.move for r in rows]
    assert moves[:4] == ["greet", "agenda", "ask", "decide"]  # a mini skips small talk
    assert "probe" in moves
    decide = rows[moves.index("decide")]
    assert decide.reason_json is not None and decide.reason_json["decision"]["action"] == "probe"
    probe = rows[moves.index("probe")]
    assert probe.reason_json is not None and probe.reason_json["why"] == ["model_chose_probe"]
    assert probe.phase == Phase.CORE and probe.messages_json and probe.raw_reply
    assert usage is not None and usage.units > 0  # the text channel saves its tokens too

    # Consent off (the default): metadata only, and no audit row.
    detail = (await admin.get(f"/admin/sessions/{sid}")).json()
    assert detail["content_visible"] is False
    assert detail["transcript"] is None and detail["traces"] is None
    meta = detail["session"]
    assert meta["user_email"] == "dev@example.com"
    assert meta["interview_type"] == "behavioral" and meta["duration_min"] == 10
    assert meta["status"] == "scoring" and meta["channel"] == "text"
    listed = (await admin.get("/admin/sessions")).json()["sessions"]
    assert [s["id"] for s in listed] == [sid]
    assert "transcript" not in listed[0] and "traces" not in listed[0]

    async def admin_views() -> list[AuditLog]:
        async with sessionmaker() as db:
            return list(await db.scalars(select(AuditLog).where(AuditLog.action.like("admin.%"))))

    assert await admin_views() == []

    # Consent on: transcript and traces, and two audit rows.
    await client.put("/account/consent", json={"training_consent": True})
    detail = (await admin.get(f"/admin/sessions/{sid}")).json()
    assert detail["content_visible"] is True
    assert detail["transcript"][0]["speaker"] == "interviewer"
    assert [t["move"] for t in detail["traces"]] == moves
    first = detail["traces"][0]
    assert first["messages"][0]["role"] == "system" and first["spoken_text"]
    assert detail["trace_retention_days"] == 90
    views = await admin_views()
    assert sorted(v.action for v in views) == ["admin.traces_viewed", "admin.transcript_viewed"]
    assert {v.actor for v in views} == {ADMIN}
    assert {v.entity for v in views} == {f"session:{sid}"}
    dev = await _user(sessionmaker, "dev@example.com")
    assert all(v.details_json and v.details_json["user_id"] == str(dev.id) for v in views)

    # The audit page shows them.
    audit = (await admin.get("/admin/audit")).json()
    assert {a["action"] for a in audit} == {"admin.traces_viewed", "admin.transcript_viewed"}
    everything = (await admin.get("/admin/audit", params={"scope": "all"})).json()
    assert "account.consent_changed" in {a["action"] for a in everything}

    # Consent is read at view time: turning it off hides the old session again.
    await client.put("/account/consent", json={"training_consent": False})
    detail = (await admin.get(f"/admin/sessions/{sid}")).json()
    assert detail["content_visible"] is False and detail["traces"] is None
    assert len(await admin_views()) == 2


async def test_r2_session_cost_daily_totals_and_filters(
    client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker, "dev@example.com")
    boss = await _user(sessionmaker, ADMIN)
    async with sessionmaker() as db:
        a = await add_session(db, dev.org_id, dev.id)  # cost from usage events
        b = await add_session(db, dev.org_id, dev.id)  # cost from traces
        c = await add_session(db, boss.org_id, boss.id)  # no cost known
        old = await add_session(db, dev.org_id, dev.id)
        row = await db.get(InterviewSession, old.id)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(days=3)
        row.type = InterviewType.CASE
        db.add(
            UsageEvent(
                org_id=dev.org_id,
                session_id=a.id,
                component=UsageComponent.LLM,
                units=Decimal(1000),
                cost_usd=Decimal("0.0125"),
            )
        )
        for seq, cost in ((1, "0.001"), (2, "0.002")):
            db.add(
                InterviewerTrace(
                    org_id=dev.org_id,
                    session_id=b.id,
                    seq=seq,
                    turn_index=seq,
                    call="say",
                    move="ask",
                    phase=Phase.CORE,
                    elapsed_ms=0,
                    input_tokens=10,
                    output_tokens=5,
                    cost_usd=Decimal(cost),
                )
            )
        await db.commit()

    body = (await admin.get("/admin/sessions")).json()
    by_id = {s["id"]: s for s in body["sessions"]}
    assert by_id[str(a.id)]["cost_usd"] == 0.0125
    assert by_id[str(a.id)]["cost_source"] == "usage_events"
    assert by_id[str(b.id)]["cost_usd"] == 0.003
    assert by_id[str(b.id)]["cost_source"] == "traces"
    assert by_id[str(c.id)]["cost_usd"] is None and by_id[str(c.id)]["cost_source"] == "none"
    assert by_id[str(a.id)]["duration_s"] == 30 * 60
    today = datetime.now(UTC).date().isoformat()
    days = {d["day"]: d for d in body["daily"]}
    assert days[today]["sessions"] == 3 and days[today]["cost_usd"] == 0.0155
    assert body["total_cost_usd"] == 0.0155

    mine = (await admin.get("/admin/sessions", params={"user_id": str(boss.id)})).json()
    assert [s["id"] for s in mine["sessions"]] == [str(c.id)]
    design = (await admin.get("/admin/sessions", params={"interview_type": "case"})).json()
    assert [s["id"] for s in design["sessions"]] == [str(old.id)]
    recent = (await admin.get("/admin/sessions", params={"day_from": today})).json()
    assert str(old.id) not in {s["id"] for s in recent["sessions"]}
    earlier = (
        await admin.get(
            "/admin/sessions",
            params={"day_to": (datetime.now(UTC) - timedelta(days=1)).date().isoformat()},
        )
    ).json()
    assert [s["id"] for s in earlier["sessions"]] == [str(old.id)]


async def test_r2_unknown_session_is_404_for_the_admin(admin: httpx.AsyncClient) -> None:
    assert (await admin.get(f"/admin/sessions/{uuid.uuid4()}")).status_code == 404
