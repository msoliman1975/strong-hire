"""LLM tracing of interview sessions in the API (LT-3, LT-6, LT-7, LT-14)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import strong_core.sim as sim_module
from strong_api.auth.settings import AppEnv, get_auth_settings
from strong_core.config import get_settings
from strong_core.db.models import InterviewSession
from strong_core.tracing.testing import InMemoryExporter, trace_capture

from .test_sessions_api import create, ready_job
from .test_sim_login import TOKEN, _app, _client, _env, _login

__all__ = ["trace_capture"]

SIM_HEADERS = {
    "X-Sim-Run": "20261105-120000-text-smoke-ab12",
    "X-Sim-Scenario": "backend-senior",
    "X-Sim-Trace-Content": "full",
}


@pytest.fixture(autouse=True)
def _fresh_sim_cache() -> Iterator[None]:
    sim_module._sim_orgs.clear()
    get_auth_settings.cache_clear()
    yield
    sim_module._sim_orgs.clear()
    get_settings.cache_clear()
    get_auth_settings.cache_clear()


def _sim_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        APP_ENV=AppEnv.STAGING.value,
        SESSION_SECRET="k" * 40,
        SIM_ENABLED="true",
        SIM_TOKEN=TOKEN,
        SIM_EMAIL="sim@example.com",
    )
    get_settings.cache_clear()


async def _stored(maker: async_sessionmaker[AsyncSession], sid: str) -> Any:
    async with maker() as db:
        row = await db.get(InterviewSession, uuid.UUID(sid))
        assert row is not None
        return row.trace_json


async def test_lt14_sim_headers_are_stored_for_the_sim_user(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: Any,
    fake_fixtures: Path,
) -> None:
    """LT-14: the sim's run, scenario and content mode go into sessions.trace_json."""
    _sim_env(monkeypatch)
    async for http in _client(_app(sessionmaker, queue)):
        assert (await _login(http)).status_code == 204
        job = await ready_job(http, fake_fixtures)
        made = await http.post(
            "/sessions",
            json={
                "job_target_id": job["id"],
                "config": _config(),
                "channel": "text",
            },
            headers=SIM_HEADERS,
        )
        assert made.status_code == 201, made.text
        assert await _stored(sessionmaker, made.json()["id"]) == {
            "sim_run_id": SIM_HEADERS["X-Sim-Run"],
            "scenario": "backend-senior",
            "content": "full",
        }
        bad = await http.post(
            "/sessions",
            json={"job_target_id": job["id"], "config": _config(), "channel": "text"},
            headers={"X-Sim-Run": "run id; drop", "X-Sim-Trace-Content": "everything"},
        )
        assert bad.status_code == 201, bad.text
        assert await _stored(sessionmaker, bad.json()["id"]) == {
            "sim_run_id": None,
            "scenario": None,
            "content": "redacted",
        }
        plain = await http.post(
            "/sessions",
            json={"job_target_id": job["id"], "config": _config(), "channel": "text"},
        )
        assert await _stored(sessionmaker, plain.json()["id"]) is None


def _config() -> dict[str, Any]:
    return {
        "interview_type": "behavioral",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 45,
        "level": "senior",
    }


async def test_lt14_sim_headers_from_a_real_user_are_ignored(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-14: anyone else sending the headers stores nothing."""
    monkeypatch.setenv("SIM_ENABLED", "true")
    monkeypatch.setenv("SIM_EMAIL", "sim@example.com")
    get_settings.cache_clear()
    get_auth_settings.cache_clear()
    job = await ready_job(client, fake_fixtures)
    made = await client.post(
        "/sessions",
        json={
            "job_target_id": job["id"],
            "config": {**_config(), "duration_min": 10},
            "channel": "text",
        },
        headers=SIM_HEADERS,
    )
    assert made.status_code == 201, made.text
    assert await _stored(sessionmaker, made.json()["id"]) is None


async def test_lt6_sim_text_turns_are_turn_traces_with_the_session_tags(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: Any,
    fake_fixtures: Path,
    trace_capture: InMemoryExporter,
) -> None:
    """LT-6, LT-7: the greeting and each answer are `turn` traces with the interviewer inside."""
    _sim_env(monkeypatch)
    async for http in _client(_app(sessionmaker, queue)):
        assert (await _login(http)).status_code == 204
        job = await ready_job(http, fake_fixtures)
        made = await http.post(
            "/sessions",
            json={"job_target_id": job["id"], "config": _config(), "channel": "text"},
            headers=SIM_HEADERS,
        )
        sid = made.json()["id"]
        trace_capture.clear()
        assert (await http.post(f"/sessions/{sid}/text/open")).status_code == 200
        turn = await http.post(f"/sessions/{sid}/text/turn", json={"text": "I led a migration."})
        assert turn.status_code == 200, turn.text
    turns = [t for t in trace_capture.traces if t.root.name == "turn"]
    assert [t.root.attributes["turn.index"] for t in turns] == [0, 1]
    for trace in turns:
        assert trace.root.attributes["turn.kind"] == "text"
        assert trace.root.attributes["duration_ms"] >= 0
        assert any(c.name == "gateway.interviewer" for c in trace.root.children)
        tags = trace.tags
        assert tags.session_id == sid and tags.service == "api" and tags.content == "full"
        assert tags.sim_run_id == SIM_HEADERS["X-Sim-Run"] and tags.scenario == "backend-senior"


async def test_lt3_real_users_text_session_is_not_traced(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    trace_capture: InMemoryExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-3: a real user's session makes no trace, with tracing on and the sim headers sent."""
    monkeypatch.setenv("SIM_ENABLED", "true")
    monkeypatch.setenv("SIM_EMAIL", "sim@example.com")
    get_settings.cache_clear()
    job = await ready_job(client, fake_fixtures)
    made = await create(client, job["id"], channel="text")
    sid = made.json()["id"]
    trace_capture.clear()
    assert (await client.post(f"/sessions/{sid}/text/open")).status_code == 200
    turn = await client.post(f"/sessions/{sid}/text/turn", json={"text": "An answer."})
    assert turn.status_code == 200, turn.text
    assert trace_capture.traces == []
