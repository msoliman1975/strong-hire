"""Phase 2 end to end, all fake (PT06): two real users with both production flags on.

One user consents to turn content and one does not. Each takes a text session. The traces land
in an in-memory store that answers the same searches as MLflow (tags.org_id, tags.content), and
the worker's delete job runs inline against it. Checks LT-16, LT-17, LT-18, LT-21, LT-22, LT-23,
LT-24 and LT-25 together.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import strong_worker.account.jobs as account_jobs
from strong_core.tracing import TraceRecord
from strong_core.tracing.prod import delete_org_traces
from strong_core.tracing.testing import InMemoryExporter, trace_capture

from .conftest import InlineQueue, sign_in
from .test_account import account_app, stripe
from .test_sessions_api import create, ready_job
from .test_tracing_consent import _flags

__all__ = ["account_app", "stripe", "trace_capture"]

ANSWER = "At Stripe I moved the ledger to Kafka; reach me at dev@example.com."
FLAGS = {
    "LLM_TRACING": "on",
    "MLFLOW_TRACKING_URI": "http://mlflow:5000/mlflow",
    "LLM_TRACING_PROD": "on",
    "LLM_TRACING_PROD_CONTENT": "on",
}


class CapturedStore:
    """prod.TraceStore over the captured traces: the two searches the delete job makes."""

    def __init__(self, exporter: InMemoryExporter) -> None:
        self.exporter = exporter

    def experiment_id(self, name: str) -> str | None:
        return "prod"

    def trace_ids(self, experiment_id: str, filter_string: str) -> list[str]:
        org = re.search(r"tags\.org_id = '([^']+)'", filter_string)
        assert org, filter_string
        content_only = "tags.content = 'turns'" in filter_string
        return [
            t.trace_id
            for t in self.exporter.traces
            if _tags(t).get("org_id") == org.group(1)
            and (not content_only or _tags(t).get("content") == "turns")
        ]

    def delete(self, experiment_id: str, trace_ids: list[str]) -> int:
        before = len(self.exporter.traces)
        self.exporter.traces[:] = [t for t in self.exporter.traces if t.trace_id not in trace_ids]
        return before - len(self.exporter.traces)

    def delete_before(self, experiment_id: str, before_ms: int) -> int:
        raise AssertionError("retention is not part of this test")


def _tags(trace: TraceRecord) -> dict[str, str]:
    return trace.tags.as_tags()


def _of(exporter: InMemoryExporter, org: str, name: str) -> list[TraceRecord]:
    return [t for t in exporter.traces if _tags(t).get("org_id") == org and t.root.name == name]


def _text(traces: list[TraceRecord]) -> str:
    return json.dumps(
        [[s.attributes, s.inputs, s.outputs] for t in traces for s in t.spans()], default=str
    )


@pytest.fixture
async def other(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A second real user, in their own org, who never consents."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, "bo@example.com")
        yield http


async def _text_session(client: httpx.AsyncClient, fake_fixtures: Path) -> None:
    job = await ready_job(client, fake_fixtures)
    made = await create(client, job["id"], channel="text")
    assert made.status_code == 201, made.text
    sid = made.json()["id"]
    assert (await client.post(f"/sessions/{sid}/text/open")).status_code == 200
    turn = await client.post(f"/sessions/{sid}/text/turn", json={"text": ANSWER})
    assert turn.status_code == 200, turn.text


async def _org(client: httpx.AsyncClient) -> str:
    return str((await client.get("/auth/me")).json()["user"]["org_id"])


async def test_pt06_two_users_from_first_turn_to_account_deletion(
    account_app: FastAPI,
    client: httpx.AsyncClient,
    other: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: InlineQueue,
    trace_capture: InMemoryExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-16 to LT-18, LT-21 to LT-25 in one flow."""
    _flags(monkeypatch, **FLAGS)
    store = CapturedStore(trace_capture)

    def delete(org_id: uuid.UUID, scope: Any) -> int:
        return delete_org_traces(org_id, scope, store)

    monkeypatch.setattr(account_jobs, "delete_org_traces", delete)

    ana, bo = await _org(client), await _org(other)
    assert ana != bo
    assert (
        await client.put("/account/tracing-consent", json={"tracing_consent": True})
    ).status_code == 200
    trace_capture.clear()
    await _text_session(client, fake_fixtures)
    await _text_session(other, fake_fixtures)

    # LT-16, LT-17, LT-18: both users' turns are traced as metadata, tagged with their org,
    # with no text anywhere in them.
    for org in (ana, bo):
        turns = _of(trace_capture, org, "turn")
        assert len(turns) == 2, org
        assert all(_tags(t)["session_id"] for t in turns)
        assert all(_tags(t)["content"] == "metadata" for t in turns)
        dump = _text(turns)
        assert "Kafka" not in dump and "Stripe" not in dump and "sha256" not in dump

    # LT-21 to LT-23: content only for the consenting user, scrubbed, in its own trace.
    assert _of(trace_capture, bo, "turn.content") == []
    content = _of(trace_capture, ana, "turn.content")
    assert len(content) == 2
    assert all(_tags(t)["content"] == "turns" for t in content)
    answer = content[1].root.inputs["candidate"]
    assert "Kafka" in answer
    assert "Stripe" not in answer and "dev@example.com" not in answer

    # LT-24: withdrawal deletes the content through the job; the metadata stays.
    assert (
        await client.put("/account/tracing-consent", json={"tracing_consent": False})
    ).status_code == 200
    assert queue.enqueued[-1][0] == "delete_traces"
    assert _of(trace_capture, ana, "turn.content") == []
    assert len(_of(trace_capture, ana, "turn")) == 2
    assert len(_of(trace_capture, bo, "turn")) == 2

    # LT-25: deleting the account removes the rest of that org's traces, and only that org's.
    assert (await client.delete("/account")).status_code == 202
    assert [t for t in trace_capture.traces if _tags(t).get("org_id") == ana] == []
    assert len(_of(trace_capture, bo, "turn")) == 2
