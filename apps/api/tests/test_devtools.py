"""Dev-only model spend for the top-bar indicator (claude profile cost limits)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from strong_api import devtools
from strong_core.config import get_settings

KEY = {
    "info": {
        "spend": 0.12345,
        "max_budget": 5.0,
        "budget_reset_at": "2026-10-08T00:00:00+00:00",
        "rpm_limit": 60,
        "team_id": "team-1",
    }
}
TEAM = {"team_info": {"spend": 1.5, "max_budget": 30.0, "budget_reset_at": "2026-11-01T00:00:00Z"}}


def fake_litellm(app: FastAPI, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[no-any-return]

    async def client() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            base_url="http://litellm.test", transport=httpx.MockTransport(record)
        ) as http:
            yield http

    app.dependency_overrides[devtools.litellm_http] = client
    return seen


def app_key(monkeypatch: pytest.MonkeyPatch, key: str = "sk-app-key") -> None:
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", key)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    monkeypatch.setenv("MODEL_PROFILE", "fake")
    get_settings.cache_clear()


async def test_spend_today_and_this_month(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_key(monkeypatch)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/key/info":
            return httpx.Response(200, json=KEY)
        return httpx.Response(200, json=TEAM)

    seen = fake_litellm(app, handle)
    out = (await client.get("/dev/model-usage")).json()
    assert out["tracked"] is True
    assert out["today"] == {
        "spend_usd": 0.1235,
        "budget_usd": 5.0,
        "resets_at": "2026-10-08T00:00:00Z",
    }
    assert out["month"]["spend_usd"] == 1.5 and out["month"]["budget_usd"] == 30.0
    assert out["rpm_limit"] == 60
    assert seen[0].url.params["key"] == "sk-app-key"
    assert seen[1].url.params["team_id"] == "team-1"


async def test_not_tracked_with_the_master_key(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every profile except claude uses the master key: nothing to show."""
    app_key(monkeypatch, key="sk-master")
    seen = fake_litellm(app, lambda r: httpx.Response(500))
    out = (await client.get("/dev/model-usage")).json()
    assert out == {
        "profile": "fake",
        "tracked": False,
        "today": None,
        "month": None,
        "rpm_limit": None,
    }
    assert seen == []


async def test_not_tracked_when_litellm_fails(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_key(monkeypatch)
    fake_litellm(app, lambda r: httpx.Response(500, json={"error": "down"}))
    assert (await client.get("/dev/model-usage")).json()["tracked"] is False


async def test_only_in_dev_and_signed_in(
    client: httpx.AsyncClient,
    anon_client: httpx.AsyncClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_litellm(app, lambda r: httpx.Response(200, json=KEY))
    assert (await anon_client.get("/dev/model-usage")).status_code == 401
    from strong_api.auth.settings import AppEnv

    class Prod:
        app_env = AppEnv.PRODUCTION

    monkeypatch.setattr(devtools, "get_auth_settings", lambda: Prod())
    assert (await client.get("/dev/model-usage")).status_code == 404
