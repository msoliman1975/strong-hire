"""Ops controls (admin spec OC-1 to OC-6, AA-6, D-6, D-11): the admin settings routes, the
public /status, and the candidate-side checks on sign-up and on new sessions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api import controls
from strong_api.auth.settings import get_auth_settings
from strong_api.main import create_app
from strong_core import runtime_settings as rs
from strong_core.db.models import AuditLog, UsageEvent, User
from strong_core.schemas import UsageComponent

from .conftest import AuthHarness, InlineQueue, build_harness, sign_in, sign_in_admin
from .test_auth import ADULT, FakeGoogle
from .test_sessions_api import create, ready_job

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
HEADERS = {"X-Admin-Request": "1"}


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    rs.clear_cache()
    controls.clear_spend_cache()
    yield
    rs.clear_cache()
    controls.clear_spend_cache()


async def _set(maker: Maker, key: str, value: Any) -> None:
    async with maker() as db:
        await rs.set(db, key, value, actor="test@example.com")
        await db.commit()
    controls.clear_spend_cache()


def _harness_set(auth: AuthHarness, key: str, value: Any) -> None:
    async def q(db: AsyncSession) -> None:
        await rs.set(db, key, value, actor="test@example.com")
        await db.commit()

    auth.query(q)


def _users(auth: AuthHarness) -> list[str]:
    async def q(db: AsyncSession) -> list[str]:
        return list((await db.scalars(select(User.email))).all())

    return auth.query(q)  # type: ignore[no-any-return]


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


# ---------------------------------------------------------------- OC-1 pause sign-ups


SIGNUP = {
    "email": "new@example.com",
    "password": "correct horse battery",
    "age_confirmed": True,
    "terms_accepted": True,
}


def test_oc1_password_signup_is_refused_with_a_waitlist_message(auth: AuthHarness) -> None:
    _harness_set(auth, "signups_paused", True)
    resp = auth.client.post("/auth/password/signup", json=SIGNUP)
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "signups_paused"
    assert "waitlist" in resp.json()["detail"]["message"]
    assert _users(auth) == []


def test_oc1_existing_password_user_still_signs_in(auth: AuthHarness) -> None:
    signup = auth.client.post("/auth/password/signup", json=SIGNUP)
    assert signup.status_code == 200
    auth.client.get(signup.json()["dev_link"].replace("http://web.test/api", ""))  # AC-4
    auth.client.post("/auth/logout")
    _harness_set(auth, "signups_paused", True)
    login = {"email": SIGNUP["email"], "password": SIGNUP["password"]}
    resp = auth.client.post("/auth/password/login", json=login)
    assert resp.status_code == 200 and resp.json()["status"] == "signed_in"


def test_oc1_magic_link_first_sign_in_goes_back_with_the_paused_error(auth: AuthHarness) -> None:
    _harness_set(auth, "signups_paused", True)
    auth.client.post("/auth/magic-link", json={"email": "bo@example.com"})
    token = _token(auth.email.sent[-1][1])
    cb = auth.client.get(f"/auth/magic-link/callback?token={token}", follow_redirects=False)
    assert cb.headers["location"] == "http://web.test/signin?error=signups_paused"
    assert auth.client.get("/auth/me").json()["status"] == "signed_out"
    assert auth.client.post("/auth/signup", json=ADULT).status_code == 401
    assert _users(auth) == []


def test_oc1_magic_link_for_an_existing_user_still_signs_in(auth: AuthHarness) -> None:
    auth.client.post("/auth/dev-login", json={"email": "bo@example.com"})
    auth.client.post("/auth/signup", json=ADULT)
    auth.client.post("/auth/logout")
    _harness_set(auth, "signups_paused", True)
    auth.client.post("/auth/magic-link", json={"email": "bo@example.com"})
    token = _token(auth.email.sent[-1][1])
    cb = auth.client.get(f"/auth/magic-link/callback?token={token}", follow_redirects=False)
    assert cb.headers["location"] == "http://web.test/"
    assert auth.client.get("/auth/me").json()["status"] == "signed_in"


def test_oc1_google_first_sign_in_is_refused() -> None:
    for harness in build_harness(google=FakeGoogle("g@example.com")):
        _harness_set(harness, "signups_paused", True)
        cb = harness.client.get("/auth/google/callback", follow_redirects=False)
        assert cb.headers["location"] == "http://web.test/signin?error=signups_paused"
        assert _users(harness) == []


def test_oc1_signup_after_a_link_opened_before_the_pause_is_refused(auth: AuthHarness) -> None:
    assert auth.client.post("/auth/dev-login", json={"email": "late@example.com"}).json()[
        "status"
    ] == ("needs_signup")
    _harness_set(auth, "signups_paused", True)
    resp = auth.client.post("/auth/signup", json=ADULT)
    assert resp.status_code == 503 and resp.json()["detail"]["code"] == "signups_paused"
    assert _users(auth) == []


def test_oc1_dev_login_of_a_new_email_is_refused(auth: AuthHarness) -> None:
    _harness_set(auth, "signups_paused", True)
    resp = auth.client.post("/auth/dev-login", json={"email": "x@example.com"})
    assert resp.status_code == 503


def test_oc1_signups_open_again_after_unpausing(auth: AuthHarness) -> None:
    _harness_set(auth, "signups_paused", True)
    _harness_set(auth, "signups_paused", False)
    assert auth.client.post("/auth/password/signup", json=SIGNUP).status_code == 200


# ---------------------------------------------------------------- OC-2, OC-3 new sessions


async def test_oc2_paused_voice_refuses_new_voice_sessions_only(
    client: httpx.AsyncClient, sessionmaker: Maker, fake_fixtures: Path
) -> None:
    job = await ready_job(client, fake_fixtures)
    await _set(sessionmaker, "sessions_paused_voice", True)
    resp = await create(client, job["id"])
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "sessions_paused"
    assert "temporarily unavailable" in resp.json()["detail"]["message"]
    assert resp.headers["retry-after"]
    assert (await create(client, job["id"], channel="text")).status_code == 201


async def test_oc2_a_session_in_progress_goes_on(
    client: httpx.AsyncClient, sessionmaker: Maker, fake_fixtures: Path
) -> None:
    job = await ready_job(client, fake_fixtures)
    started = (await create(client, job["id"])).json()["id"]
    waiting = (await create(client, job["id"])).json()["id"]
    assert (await client.post(f"/sessions/{started}/voice/join")).status_code == 200
    await _set(sessionmaker, "sessions_paused_voice", True)
    # A rejoin of the started session works (IV-9); the one that never started may not start.
    assert (await client.post(f"/sessions/{started}/voice/join")).status_code == 200
    refused = await client.post(f"/sessions/{waiting}/voice/join")
    assert refused.status_code == 503 and refused.json()["detail"]["code"] == "sessions_paused"


async def test_oc2_paused_text_refuses_create_and_open(
    client: httpx.AsyncClient, sessionmaker: Maker, fake_fixtures: Path
) -> None:
    job = await ready_job(client, fake_fixtures)
    sid = (await create(client, job["id"], channel="text")).json()["id"]
    await _set(sessionmaker, "sessions_paused_text", True)
    assert (await create(client, job["id"], channel="text")).status_code == 503
    resp = await client.post(f"/sessions/{sid}/text/open")
    assert resp.status_code == 503 and resp.json()["detail"]["code"] == "sessions_paused"
    assert (await create(client, job["id"])).status_code == 201  # voice is not paused


async def _spend(maker: Maker, usd: str, at: datetime | None = None) -> None:
    async with maker() as db:
        org_id = (await db.scalars(select(User.org_id))).first() or uuid.uuid4()
        row = UsageEvent(
            org_id=org_id, component=UsageComponent.LLM, units=Decimal(1), cost_usd=Decimal(usd)
        )
        if at is not None:
            row.created_at = at
        db.add(row)
        await db.commit()


async def test_oc3_spend_cap_refuses_new_sessions_with_its_own_code(
    client: httpx.AsyncClient, sessionmaker: Maker, fake_fixtures: Path
) -> None:
    """OC-3, D-6: the default cap is $25; today's cost at or over it refuses new sessions."""
    assert rs.DEFAULTS.daily_spend_cap_usd == 25.0
    job = await ready_job(client, fake_fixtures)
    started = (await create(client, job["id"])).json()["id"]
    assert (await client.post(f"/sessions/{started}/voice/join")).status_code == 200
    await _spend(sessionmaker, "30", at=datetime.now(UTC) - timedelta(days=1, hours=1))
    controls.clear_spend_cache()
    assert (await create(client, job["id"])).status_code == 201  # yesterday does not count
    await _spend(sessionmaker, "25.000000")
    controls.clear_spend_cache()
    resp = await create(client, job["id"], channel="text")
    assert resp.status_code == 503 and resp.json()["detail"]["code"] == "spend_cap_reached"
    # The session in progress goes on.
    assert (await client.post(f"/sessions/{started}/voice/join")).status_code == 200
    await _set(sessionmaker, "daily_spend_cap_usd", 100)
    assert (await create(client, job["id"])).status_code == 201


async def test_oc3_todays_spend_is_cached_for_30_seconds(sessionmaker: Maker) -> None:
    async with sessionmaker() as db:
        assert await controls.spend_today_usd(db) == 0
    await _spend(sessionmaker, "3.5")
    async with sessionmaker() as db:
        assert await controls.spend_today_usd(db) == 0  # cached
        controls.clear_spend_cache()
        assert await controls.spend_today_usd(db) == Decimal("3.5")


# ---------------------------------------------------------------- OC-4 public status


async def test_oc4_status_shows_the_banner_until_it_ends(
    anon_client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    body = (await anon_client.get("/status")).json()
    assert body == {
        "banner": None,
        "signups_open": True,
        "voice_sessions_open": True,
        "text_sessions_open": True,
        "custom_interview_access": "everyone",
        "v2_enabled": False,
    }
    until = datetime.now(UTC) + timedelta(hours=1)
    banner = {"text": "Scoring is slow today.", "severity": "warning", "until": until.isoformat()}
    await _set(sessionmaker, "site_banner", banner)
    await _set(sessionmaker, "signups_paused", True)
    await _set(sessionmaker, "sessions_paused_voice", True)
    body = (await anon_client.get("/status")).json()
    assert body["banner"]["text"] == "Scoring is slow today."
    assert body["banner"]["severity"] == "warning"
    assert body["signups_open"] is False
    assert body["voice_sessions_open"] is False and body["text_sessions_open"] is True
    past = {**banner, "until": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    await _set(sessionmaker, "site_banner", past)
    assert (await anon_client.get("/status")).json()["banner"] is None


async def test_oc4_status_reports_the_spend_cap_as_sessions_closed(
    anon_client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    await _set(sessionmaker, "daily_spend_cap_usd", 1)
    await _spend(sessionmaker, "1.5")
    body = (await anon_client.get("/status")).json()
    assert body["voice_sessions_open"] is False and body["text_sessions_open"] is False


# ---------------------------------------------------------------- admin routes


@pytest.fixture
def admin_app(
    sessionmaker: Maker, queue: InlineQueue, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    get_auth_settings.cache_clear()

    async def _ok() -> None:
        return None

    yield create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    get_auth_settings.cache_clear()


@pytest.fixture
async def admin(admin_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, ADMIN)  # the admin's candidate account
        await sign_in_admin(http, admin_app, ADMIN)  # AA-4: the admin session
        yield http


@pytest.fixture
async def candidate(admin_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, "ana@example.com")
        yield http


async def test_settings_routes_are_for_admins_only(candidate: httpx.AsyncClient) -> None:
    """AA-4: 404 for everyone else."""
    assert (await candidate.get("/admin/ops/settings")).status_code == 404
    put = {"value": True, "reason": "testing it"}
    resp = await candidate.put("/admin/ops/settings/signups_paused", json=put, headers=HEADERS)
    assert resp.status_code == 404
    assert (await candidate.get("/admin/ops/models")).status_code == 404


async def test_get_settings_lists_every_key_with_defaults(admin: httpx.AsyncClient) -> None:
    body = (await admin.get("/admin/ops/settings")).json()
    assert body["values"] == body["defaults"]
    assert body["defaults"]["daily_spend_cap_usd"] == 25.0  # D-6
    assert {m["key"] for m in body["meta"]} == set(rs.KEYS)
    assert all(m["is_default"] and m["updated_by"] is None for m in body["meta"])
    assert body["spend_today_usd"] == 0


async def test_aa6_put_setting_is_audited_with_before_and_after(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    put = {"value": True, "reason": "incident 42"}
    assert (
        await admin.put("/admin/ops/settings/signups_paused", json=put)
    ).status_code == 403  # AA-5: the header is required
    resp = await admin.put("/admin/ops/settings/signups_paused", json=put, headers=HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["values"]["signups_paused"] is True
    meta = {m["key"]: m for m in body["meta"]}["signups_paused"]
    assert meta["updated_by"] == ADMIN and meta["is_default"] is False
    async with sessionmaker() as db:
        row = (
            await db.scalars(select(AuditLog).where(AuditLog.action == "ops.setting_changed"))
        ).one()
    assert row.actor == ADMIN and row.entity == "runtime_setting:signups_paused"
    assert row.details_json["reason"] == "incident 42"
    assert row.details_json["before"] == {"signups_paused": False}
    assert row.details_json["after"] == {"signups_paused": True}
    # The change is in force at once in this process.
    async with sessionmaker() as db:
        assert await rs.get(db, "signups_paused") is True


async def test_put_setting_validates_the_value_and_the_key(admin: httpx.AsyncClient) -> None:
    bad = {"value": -1, "reason": "testing it"}
    resp = await admin.put("/admin/ops/settings/daily_spend_cap_usd", json=bad, headers=HEADERS)
    assert resp.status_code == 422
    resp = await admin.put(
        "/admin/ops/settings/no_such_key", json={"value": 1, "reason": "x" * 5}, headers=HEADERS
    )
    assert resp.status_code == 404
    resp = await admin.put(
        "/admin/ops/settings/signups_paused", json={"value": True}, headers=HEADERS
    )
    assert resp.status_code == 422  # the reason is required


async def test_oc4_oc5_banner_and_jobs_paused_round_trip(admin: httpx.AsyncClient) -> None:
    banner = {"text": "Maintenance at 18:00 UTC", "severity": "info", "until": "2099-01-01T00:00"}
    resp = await admin.put(
        "/admin/ops/settings/site_banner",
        json={"value": banner, "reason": "planned work"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"]["site_banner"]["until"].startswith("2099-01-01T00:00:00")
    jobs = {"value": ["scoring", "gap_analysis", "scoring"], "reason": "provider down"}
    resp = await admin.put("/admin/ops/settings/jobs_paused", json=jobs, headers=HEADERS)
    assert resp.json()["values"]["jobs_paused"] == ["gap_analysis", "scoring"]
    cleared = {"value": None, "reason": "work done"}
    resp = await admin.put("/admin/ops/settings/site_banner", json=cleared, headers=HEADERS)
    assert resp.json()["values"]["site_banner"] is None
    bad = {"value": ["email"], "reason": "not a kind"}
    resp = await admin.put("/admin/ops/settings/jobs_paused", json=bad, headers=HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------- OC-6 model profile


async def test_oc6_models_shows_roles_and_no_heartbeats(
    admin: httpx.AsyncClient, admin_app: FastAPI
) -> None:
    async def none() -> list[dict[str, Any]]:
        return []

    admin_app.state.heartbeat_source = none
    body = (await admin.get("/admin/ops/models")).json()
    assert body["api_profile"] == "fake"
    roles = {r["role"]: r for r in body["roles"]}
    assert roles["interviewer"]["alias"] == "fake-interviewer"
    assert roles["tts"]["kind"] == "tts" and roles["candidate"]["test_only"] is True
    assert body["services"] == [] and body["heartbeats_available"] is True
    assert body["mismatch"] is False


async def test_oc6_models_flags_a_service_on_another_profile(
    admin: httpx.AsyncClient, admin_app: FastAPI
) -> None:
    now = datetime.now(UTC).isoformat()

    async def beats() -> list[dict[str, Any]]:
        return [
            {"service": "worker", "instance": "w1", "model_profile": "fake", "at": now},
            {"service": "voice", "instance": "v1", "model_profile": "hosted", "version": "1.2"},
        ]

    admin_app.state.heartbeat_source = beats
    body = (await admin.get("/admin/ops/models")).json()
    assert [s["service"] for s in body["services"]] == ["voice", "worker"]
    assert body["services"][0]["model_profile"] == "hosted"
    assert body["mismatch"] is True


async def test_oc6_models_survives_redis_being_down(
    admin: httpx.AsyncClient, admin_app: FastAPI
) -> None:
    async def broken() -> list[dict[str, Any]]:
        raise ConnectionError("no redis")

    admin_app.state.heartbeat_source = broken
    body = (await admin.get("/admin/ops/models")).json()
    assert body["heartbeats_available"] is False and body["services"] == []


async def test_fl1_status_reports_v2_enabled(
    anon_client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """FL-1: the candidate app reads v2_enabled from /status; it is off until set."""
    assert (await anon_client.get("/status")).json()["v2_enabled"] is False
    await _set(sessionmaker, "v2_enabled", True)
    assert (await anon_client.get("/status")).json()["v2_enabled"] is True
