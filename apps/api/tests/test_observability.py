"""API side of admin observability: complete usage (OB-2), request ids and logs (OB-7), and
unhandled errors captured with the request id and no PII (OB-4)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.main import create_app
from strong_core.db.models import ErrorEvent, ErrorGroup, UsageEvent
from strong_core.gateway import UsageRecord, set_usage_sink
from strong_core.ops.errors import install_error_capture, uninstall_error_capture

from .test_sessions_api import create, ready_job

Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
def usage() -> list[UsageRecord]:
    records: list[UsageRecord] = []

    async def sink(record: UsageRecord) -> None:
        records.append(record)

    set_usage_sink(sink)  # the autouse fixture restores the previous sink
    return records


async def test_ob2_every_model_call_of_a_text_session_has_a_usage_row(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: Maker,
    usage: list[UsageRecord],
) -> None:
    """OB-2: extraction (no session), the brief job and every interviewer call (with the
    session), and no hand-written end-of-session row on top."""
    job = await ready_job(client, fake_fixtures)
    sid = uuid.UUID((await create(client, job["id"], channel="text")).json()["id"])
    await client.post(f"/sessions/{sid}/text/open")
    queue.run_jobs = False
    for _ in range(80):
        out = (await client.post(f"/sessions/{sid}/text/turn", json={"text": "No, thanks."})).json()
        if out["ended"]:
            break
    assert out["ended"]

    by_role: dict[str, set[uuid.UUID | None]] = {}
    for record in usage:
        by_role.setdefault(record.role.value, set()).add(record.session_id)
    assert by_role["extractor"] == {None}  # the job posting has no session
    assert by_role["planner"] == {sid}  # the interviewer brief
    assert by_role["interviewer"] == {sid}
    assert all(r.component == "llm" and r.org_id for r in usage)
    async with sessionmaker() as db:
        rows = list(await db.scalars(select(UsageEvent).where(UsageEvent.session_id == sid)))
    assert rows == []  # nothing written outside the gateway (the test sink keeps them)


async def test_ob7_request_id_is_returned_and_taken_from_a_safe_header(
    anon_client: httpx.AsyncClient,
) -> None:
    made = await anon_client.get("/health")
    assert len(made.headers["x-request-id"]) == 16
    given = await anon_client.get("/health", headers={"X-Request-ID": "edge-1234"})
    assert given.headers["x-request-id"] == "edge-1234"
    unsafe = await anon_client.get("/health", headers={"X-Request-ID": "a b<script>"})
    assert unsafe.headers["x-request-id"] != "a b<script>"


@pytest.fixture
async def boom_app(sessionmaker: Maker) -> AsyncIterator[tuple[FastAPI, Any]]:
    app = create_app({"database": _ok}, sessionmaker=sessionmaker)

    @app.post("/sessions/{session_id}/boom")
    async def boom(session_id: uuid.UUID, body: dict[str, Any]) -> None:
        raise ValueError(f"could not read {body['resume']}")

    capture = install_error_capture("api", sessionmaker)
    try:
        yield app, capture
    finally:
        uninstall_error_capture(capture)


async def _ok() -> None:
    return None


RESUME = (
    "Jane Candidate jane.candidate@example.com +1 425 555 0100. Staff engineer at Example "
    "Corp who led the payments ledger migration across four regions and mentored nine people."
)


async def test_ob4_unhandled_request_error_is_captured_with_request_id_and_no_pii(
    boom_app: tuple[FastAPI, Any], sessionmaker: Maker, caplog: pytest.LogCaptureFixture
) -> None:
    app, capture = boom_app
    sid = uuid.uuid4()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        with caplog.at_level(logging.ERROR):
            resp = await http.post(
                f"/sessions/{sid}/boom",
                json={"resume": RESUME},
                headers={"X-Request-ID": "req-42"},
            )
    assert resp.status_code == 500
    assert await capture.write_pending() == 1
    async with sessionmaker() as db:
        group = (await db.scalars(select(ErrorGroup))).one()
        event = (await db.scalars(select(ErrorEvent))).one()
    assert group.service == "api" and group.exception_type == "ValueError" and group.count == 1
    assert event.request_id == "req-42" and event.session_id == sid
    stored = " ".join([group.message, group.sample_stack or ""])
    assert "jane.candidate@example.com" not in stored
    assert "555 0100" not in stored
    assert "mentored nine people" not in stored  # free text is cut, never kept whole
    assert "test_observability.py" in (group.sample_stack or "")
