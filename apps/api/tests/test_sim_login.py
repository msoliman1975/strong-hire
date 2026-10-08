"""The AI candidate's sign-in and its session rules (P13)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.auth.settings import AppEnv, get_auth_settings
from strong_api.auth.sim import FailureLimiter
from strong_api.main import create_app
from strong_core.db.models import AuditLog, User

from .accounts_support import add_session
from .conftest import sign_in
from .test_sessions_api import create, ready_job

TOKEN = "s" * 40


async def _ok() -> None:
    return None


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key in ("SIM_ENABLED", "SIM_TOKEN", "SIM_EMAIL", "APP_ENV", "ADMIN_EMAILS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_auth_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings() -> Any:
    yield
    get_auth_settings.cache_clear()


def _app(sessionmaker: Any, queue: Any) -> FastAPI:
    return create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)


async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://test"
    ) as http:  # secure cookies outside local
        yield http


async def _login(http: httpx.AsyncClient, token: str | None = TOKEN) -> httpx.Response:
    headers = {"X-Sim-Token": token} if token else {}
    return await http.post("/auth/sim-login", headers=headers)


@pytest.mark.parametrize(
    "env",
    [
        {},  # flag off
        {"SIM_ENABLED": "false", "SIM_TOKEN": TOKEN},
        {"SIM_ENABLED": "true"},  # no token
        {"SIM_ENABLED": "true", "SIM_TOKEN": "short"},  # token too short
    ],
)
async def test_sim_login_is_404_unless_enabled_with_a_real_token(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, sessionmaker: Any, queue: Any
) -> None:
    _env(monkeypatch, **env)
    async for http in _client(_app(sessionmaker, queue)):
        assert (await _login(http, env.get("SIM_TOKEN", TOKEN))).status_code == 404


async def test_sim_login_wrong_token_is_404_and_right_token_signs_in_the_sim_user(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: Any,
) -> None:
    _env(monkeypatch, SIM_ENABLED="true", SIM_TOKEN=TOKEN, SIM_EMAIL="Sim@Example.com")
    async for http in _client(_app(sessionmaker, queue)):
        assert (await _login(http, None)).status_code == 404
        assert (await _login(http, "x" * 40)).status_code == 404
        assert (await _login(http)).status_code == 204
        me = (await http.get("/auth/me")).json()
        assert me["status"] == "signed_in" and me["email"] == "sim@example.com"
        assert (await _login(http)).status_code == 204  # the same user, not a second one
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1


def test_failure_limiter_blocks_after_five_failures() -> None:
    limiter = FailureLimiter(max_failures=5, window_s=600)
    for _ in range(4):
        limiter.fail("1.2.3.4")
    assert not limiter.blocked("1.2.3.4")
    limiter.fail("1.2.3.4")
    assert limiter.blocked("1.2.3.4") and not limiter.blocked("5.6.7.8")


async def test_sim_user_gets_text_sessions_and_skips_the_plan_check_outside_local(
    monkeypatch: pytest.MonkeyPatch, sessionmaker: Any, queue: Any, fake_fixtures: Path
) -> None:
    """On the server (APP_ENV=staging) only the sim user may use the text channel (PL-7)."""
    _env(
        monkeypatch,
        APP_ENV=AppEnv.STAGING.value,
        SESSION_SECRET="k" * 40,
        SIM_ENABLED="true",
        SIM_TOKEN=TOKEN,
        SIM_EMAIL="sim@example.com",
    )
    async for http in _client(_app(sessionmaker, queue)):
        assert (await _login(http)).status_code == 204
        job = await ready_job(http, fake_fixtures)
        # A 45-minute session needs a paid plan for real users; the sim user has none.
        record = await create(http, job["id"], channel="text", duration_min=45)
        assert record.status_code == 201, record.text
        opened = await http.post(f"/sessions/{record.json()['id']}/text/open")
        assert opened.status_code == 200, opened.text


async def test_sim_budget_routes_are_only_for_the_sim_user_and_add_up(
    monkeypatch: pytest.MonkeyPatch, sessionmaker: Any, queue: Any
) -> None:
    """P13: the AI-to-AI budget is $5 per day, and the sim reports its own model cost."""
    from strong_api.auth.sim import MemorySpendStore

    _env(monkeypatch, SIM_ENABLED="true", SIM_TOKEN=TOKEN, SIM_EMAIL="sim@example.com")
    app = _app(sessionmaker, queue)
    app.state.sim_spend_store = MemorySpendStore()
    async for http in _client(app):
        assert (await http.get("/auth/sim-budget")).status_code == 401  # nobody signed in
        await sign_in(http, "real@example.com")
        assert (await http.get("/auth/sim-budget")).status_code == 404  # a real user
        assert (await http.post("/auth/sim-spend", json={"usd": 1})).status_code == 404
    async for http in _client(app):
        assert (await _login(http)).status_code == 204
        first = (await http.get("/auth/sim-budget")).json()
        assert first["limit_usd"] == 5.0 and first["remaining_usd"] == 5.0
        assert first["server_usd"] is None  # no sim LiteLLM key in tests
        assert (await http.post("/auth/sim-spend", json={"usd": 1.25})).status_code == 204
        after = (await http.get("/auth/sim-budget")).json()
        assert after["sim_usd"] == 1.25 and after["remaining_usd"] == 3.75


async def test_the_sim_org_gets_its_own_litellm_key(
    monkeypatch: pytest.MonkeyPatch, sessionmaker: async_sessionmaker[AsyncSession], queue: Any
) -> None:
    """P13: model calls for the sim org use SIM_LITELLM_KEY; every other org keeps the app key."""
    from strong_core import sim as core_sim
    from strong_core.config import get_settings
    from strong_core.gateway import ModelGateway
    from strong_core.gateway.registry import fake_models_config

    _env(monkeypatch, SIM_ENABLED="true", SIM_TOKEN=TOKEN, SIM_EMAIL="sim@example.com")
    monkeypatch.setenv("SIM_LITELLM_KEY", "sk-sim-budget")
    get_settings.cache_clear()
    monkeypatch.setattr(core_sim, "_sim_orgs", set())
    app = _app(sessionmaker, queue)
    async for http in _client(app):
        assert (await _login(http)).status_code == 204
        sim_org = (await http.get("/auth/me")).json()["user"]["org_id"]
    async for http in _client(app):
        real_org = (await sign_in(http, "real@example.com"))["user"]["org_id"]
    base = ModelGateway(fake_models_config(), api_key="sk-app")
    import uuid as _uuid

    async with sessionmaker() as db:
        sim_gw = await core_sim.gateway_for_org(db, _uuid.UUID(sim_org), base)
        real_gw = await core_sim.gateway_for_org(db, _uuid.UUID(real_org), base)
    assert sim_gw._api_key == "sk-sim-budget"
    assert real_gw is base
    get_settings.cache_clear()


async def test_sim_user_has_consent_and_the_admin_downloads_its_transcript_and_audio(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: Any,
    tmp_path: Path,
) -> None:
    """Our own test user: the admin sees its transcripts and downloads them and its recordings."""
    _env(monkeypatch, SIM_ENABLED="true", SIM_TOKEN=TOKEN, ADMIN_EMAILS="boss@example.com")
    monkeypatch.setenv("SIM_RESULTS_DIR", str(tmp_path))
    get_auth_settings.cache_clear()
    app = _app(sessionmaker, queue)

    # A sim user made before this change, with consent off: the next sign-in turns it on.
    async for http in _client(app):
        await sign_in(http, "sim@getstronghire.com")
    async with sessionmaker() as db:
        sim = await db.scalar(select(User).where(User.email == "sim@getstronghire.com"))
        assert sim is not None and sim.training_consent is False
    async for http in _client(app):
        assert (await _login(http)).status_code == 204
    async with sessionmaker() as db:
        sim = await db.scalar(select(User).where(User.email == "sim@getstronghire.com"))
        assert sim is not None and sim.training_consent is True
        changed = await db.scalar(
            select(AuditLog).where(AuditLog.action == "account.consent_changed")
        )
        assert changed is not None and changed.actor == "sim-login"
        session = await add_session(db, sim.org_id, sim.id)
        sid = session.id

    run = tmp_path / "20261008-120000-voice-smoke-abcd" / str(sid)
    run.mkdir(parents=True)
    (run / "audio.ogg").write_bytes(b"OggS-test-audio")

    # A real user with consent on: transcript download yes, audio no (never stored).
    async for real in _client(app):
        await sign_in(real, "dev@example.com")
        await real.put("/account/consent", json={"training_consent": True})
    async with sessionmaker() as db:
        dev = await db.scalar(select(User).where(User.email == "dev@example.com"))
        assert dev is not None
        real_sid = (await add_session(db, dev.org_id, dev.id)).id
    real_dir = tmp_path / "20261008-120000-voice-smoke-abcd" / str(real_sid)
    real_dir.mkdir()
    (real_dir / "audio.ogg").write_bytes(b"not served")

    async for admin in _client(app):
        await sign_in(admin, "boss@example.com")
        detail = (await admin.get(f"/admin/sessions/{sid}")).json()
        assert detail["content_visible"] is True and detail["audio_available"] is True

        text = await admin.get(f"/admin/sessions/{sid}/transcript.txt")
        assert text.status_code == 200
        assert text.headers["content-disposition"].startswith("attachment;")
        assert text.text.startswith(f"Interview {sid}")

        audio = await admin.get(f"/admin/sessions/{sid}/audio")
        assert audio.status_code == 200 and audio.content == b"OggS-test-audio"
        assert audio.headers["content-type"] == "audio/ogg"
        assert audio.headers["content-disposition"].startswith("attachment;")

        real_detail = (await admin.get(f"/admin/sessions/{real_sid}")).json()
        assert real_detail["content_visible"] is True and real_detail["audio_available"] is False
        assert (await admin.get(f"/admin/sessions/{real_sid}/audio")).status_code == 404
        assert (await admin.get(f"/admin/sessions/{real_sid}/transcript.txt")).status_code == 200

    # Not for the sim user itself, and every download is in the audit log.
    async for http in _client(app):
        assert (await _login(http)).status_code == 204
        assert (await http.get(f"/admin/sessions/{sid}/audio")).status_code == 404
    async with sessionmaker() as db:
        actions = list(
            await db.scalars(select(AuditLog.action).where(AuditLog.action.like("admin.%")))
        )
    assert actions.count("admin.audio_downloaded") == 1
    assert actions.count("admin.transcript_downloaded") == 2

    # Consent is read at download time.
    async with sessionmaker() as db:
        sim = await db.scalar(select(User).where(User.email == "sim@getstronghire.com"))
        assert sim is not None
        sim.training_consent = False
        await db.commit()
    async for admin in _client(app):
        await sign_in(admin, "boss@example.com")
        assert (await admin.get(f"/admin/sessions/{sid}/audio")).status_code == 404
        assert (await admin.get(f"/admin/sessions/{sid}/transcript.txt")).status_code == 404
