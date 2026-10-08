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
from strong_core.db.models import User

from .test_sessions_api import create, ready_job

TOKEN = "s" * 40


async def _ok() -> None:
    return None


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key in ("SIM_ENABLED", "SIM_TOKEN", "SIM_EMAIL", "APP_ENV"):
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
