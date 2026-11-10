"""Phase 2 in the API (LT-20, LT-21, LT-24, LT-25): consent, deletion requests, turn content."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import strong_core.sim as sim_module
import strong_worker.account.jobs as account_jobs
from strong_api.account.traces import DELETE_TRACES, TRACES_REQUESTED
from strong_core import runtime_settings as rs
from strong_core.config import get_settings
from strong_core.db.models import AuditLog
from strong_core.tracing.testing import InMemoryExporter, trace_capture

from .conftest import InlineQueue
from .test_account import account_app, stripe, user
from .test_sessions_api import create, ready_job

__all__ = ["account_app", "stripe", "trace_capture", "user"]

Maker = async_sessionmaker[AsyncSession]
ANSWER = "At Stripe I moved the ledger to Kafka; reach me at dev@example.com."


@pytest.fixture
def deleted(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[uuid.UUID, str]]]:
    """The worker job runs inline in these tests; record what it would delete in MLflow."""
    calls: list[tuple[uuid.UUID, str]] = []

    def fake(org_id: uuid.UUID, scope: str) -> int:
        calls.append((org_id, scope))
        return 1

    monkeypatch.setattr(account_jobs, "delete_org_traces", fake)
    yield calls


def _flags(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    rs.clear_cache()
    sim_module._sim_orgs.clear()


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    get_settings.cache_clear()
    rs.clear_cache()


CONFIGURED = {"LLM_TRACING": "on", "MLFLOW_TRACKING_URI": "http://mlflow:5000"}


def test_job_names_match_the_worker() -> None:
    assert account_jobs.delete_traces.__name__ == DELETE_TRACES
    assert TRACES_REQUESTED == account_jobs.TRACES_REQUESTED


# --- LT-20: the consent ---------------------------------------------------------------------------


async def test_lt20_toggle_is_hidden_and_refused_until_gate_2(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-20: rules out collecting this consent before the lawyer approved its wording."""
    monkeypatch.delenv("LLM_TRACING_PROD_CONTENT", raising=False)
    get_settings.cache_clear()
    me = (await client.get("/auth/me")).json()["user"]
    assert me["tracing_consent"] is False and me["tracing_consent_available"] is False
    resp = await client.put("/account/tracing-consent", json={"tracing_consent": True})
    assert resp.status_code == 404


async def test_lt20_consent_changes_are_saved_and_audited(
    client: httpx.AsyncClient, sessionmaker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-20: off by default; each change sets the time and writes an audit row."""
    _flags(monkeypatch, LLM_TRACING_PROD_CONTENT="on")
    me = (await client.get("/auth/me")).json()["user"]
    assert me["tracing_consent"] is False and me["tracing_consent_available"] is True
    resp = await client.put("/account/tracing-consent", json={"tracing_consent": True})
    assert resp.status_code == 200 and resp.json() == {"tracing_consent": True}
    assert (await client.get("/auth/me")).json()["user"]["tracing_consent"] is True
    async with sessionmaker() as db:
        rows = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "account.tracing_consent_changed")
            )
        ).scalars()
        (row,) = list(rows)
    assert row.details_json == {"tracing_consent_from": False, "tracing_consent_to": True}


# --- LT-24, LT-25: deletion requests --------------------------------------------------------------


async def _requests(maker: Maker) -> list[dict[str, Any]]:
    async with maker() as db:
        rows = (
            await db.execute(select(AuditLog).where(AuditLog.action == TRACES_REQUESTED))
        ).scalars()
        return [r.details_json or {} for r in rows]


async def test_lt24_withdrawal_queues_deletion_of_content(
    client: httpx.AsyncClient,
    sessionmaker: Maker,
    queue: InlineQueue,
    deleted: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-24: turning consent off deletes the content kept so far; turning it on does not."""
    _flags(monkeypatch, LLM_TRACING_PROD_CONTENT="on", **CONFIGURED)
    await client.put("/account/tracing-consent", json={"tracing_consent": True})
    assert deleted == []
    await client.put("/account/tracing-consent", json={"tracing_consent": False})
    org = uuid.UUID((await client.get("/auth/me")).json()["user"]["org_id"])
    assert deleted == [(org, "content")]
    (request,) = await _requests(sessionmaker)
    assert request["scope"] == "content"
    function, job_id, kwargs = queue.enqueued[-1]
    assert function == DELETE_TRACES and kwargs["request_id"] == request["request_id"] == job_id


async def test_lt24_nothing_is_queued_when_tracing_is_not_set_up(
    client: httpx.AsyncClient,
    sessionmaker: Maker,
    deleted: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-18: without MLflow there is nothing to delete, and a job would only raise the alert."""
    monkeypatch.delenv("LLM_TRACING", raising=False)
    _flags(monkeypatch, LLM_TRACING_PROD_CONTENT="on")
    await client.put("/account/tracing-consent", json={"tracing_consent": True})
    await client.put("/account/tracing-consent", json={"tracing_consent": False})
    assert deleted == [] and await _requests(sessionmaker) == []


async def test_lt25_account_deletion_queues_deletion_of_all_traces(
    account_app: Any,
    client: httpx.AsyncClient,
    user: dict[str, Any],
    sessionmaker: Maker,
    deleted: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-25: an account deletion asks for every production trace of the org, and the request
    outlives the account in the audit log."""
    _flags(monkeypatch, **CONFIGURED)
    org = uuid.UUID((await client.get("/auth/me")).json()["user"]["org_id"])
    assert (await client.delete("/account")).status_code == 202
    assert deleted == [(org, "all")]
    (request,) = await _requests(sessionmaker)
    assert request["scope"] == "all"


# --- LT-21: text turn content ------------------------------------------------------------------


async def _text_session(client: httpx.AsyncClient, fake_fixtures: Path) -> str:
    job = await ready_job(client, fake_fixtures)
    made = await create(client, job["id"], channel="text")
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def test_lt21_a_consenting_users_text_turn_keeps_scrubbed_content(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    trace_capture: InMemoryExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-21: the answer and the reply go into a turn.content trace, scrubbed of the companies
    and the email; the metadata turn trace holds no text."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")
    await client.put("/account/tracing-consent", json={"tracing_consent": True})
    sid = await _text_session(client, fake_fixtures)
    trace_capture.clear()
    assert (await client.post(f"/sessions/{sid}/text/open")).status_code == 200
    turn = await client.post(f"/sessions/{sid}/text/turn", json={"text": ANSWER})
    assert turn.status_code == 200, turn.text
    content = [t for t in trace_capture.traces if t.root.name == "turn.content"]
    metadata = [t for t in trace_capture.traces if t.root.name == "turn"]
    assert [t.root.attributes["turn.index"] for t in content] == [0, 1]
    answer = content[1].root.inputs["candidate"]
    assert "Kafka" in answer and "Stripe" not in answer and "dev@example.com" not in answer
    assert content[1].root.outputs["interviewer"]
    assert all(t.tags.as_tags()["content"] == "turns" for t in content)
    for trace in metadata:
        dump = json.dumps([[s.attributes, s.inputs, s.outputs] for s in trace.spans()], default=str)
        assert "Kafka" not in dump and "Stripe" not in dump and "sha256" not in dump


async def test_lt21_no_content_without_consent(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    trace_capture: InMemoryExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-21: rules out keeping a non-consenting user's answers; their turns are metadata only."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")
    sid = await _text_session(client, fake_fixtures)
    trace_capture.clear()
    await client.post(f"/sessions/{sid}/text/open")
    await client.post(f"/sessions/{sid}/text/turn", json={"text": ANSWER})
    assert [t.root.name for t in trace_capture.traces] == ["turn", "turn"]
    assert "Kafka" not in json.dumps(
        [[s.inputs, s.outputs] for t in trace_capture.traces for s in t.spans()], default=str
    )


async def test_lt24_withdrawal_stops_content_from_the_next_turn(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    trace_capture: InMemoryExporter,
    deleted: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-24: content stops at the next turn, even in the middle of a session."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")
    await client.put("/account/tracing-consent", json={"tracing_consent": True})
    sid = await _text_session(client, fake_fixtures)
    await client.post(f"/sessions/{sid}/text/open")
    await client.put("/account/tracing-consent", json={"tracing_consent": False})
    trace_capture.clear()
    await client.post(f"/sessions/{sid}/text/turn", json={"text": ANSWER})
    assert [t.root.name for t in trace_capture.traces] == ["turn"]
