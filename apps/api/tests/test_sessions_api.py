"""Sessions API (P7): create, read, end, and the text channel (IV-7, IV-8, PL-7, BL-2, FB-3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.sessions import router as sessions_router  # the module
from strong_core.config import get_settings
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Turn as TurnRow
from strong_core.schemas import Phase, SessionStatus, Speaker
from strong_worker.inputs.testing import set_extractor_output

from .conftest import sign_in

FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"


async def ready_job(client: httpx.AsyncClient, fake_fixtures: Path) -> dict[str, Any]:
    text = (FIXTURES / "postings/swe-stripe-backend.txt").read_text(encoding="utf-8")
    posting = json.loads((FIXTURES / "postings/swe-stripe-backend.json").read_text("utf-8"))
    set_extractor_output(fake_fixtures, "JobPosting", posting)
    target: dict[str, Any] = (await client.post("/job-targets", json={"text": text})).json()[
        "job_target"
    ]
    assert target["status"] == "extracted"
    return target


def config(**changes: Any) -> dict[str, Any]:
    base = {
        "interview_type": "behavioral",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 30,
        "level": "staff_principal",
    }
    return {**base, **changes}


async def create(
    client: httpx.AsyncClient, job_id: str, channel: str = "voice", **changes: Any
) -> httpx.Response:
    body = {"job_target_id": job_id, "config": config(**changes), "channel": channel}
    return await client.post("/sessions", json=body)


async def test_create_read_and_list(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A new session queues its brief (built inline here) and appears on the job's list."""
    job = await ready_job(client, fake_fixtures)
    resp = await create(client, job["id"])
    assert resp.status_code == 201, resp.text
    record = resp.json()
    assert record["status"] == "created" and record["channel"] == "voice"
    assert record["brief_ready"] is True
    assert record["config"]["level"] == "staff_principal"
    assert record["started_at"] is None and record["minutes_billed"] == 0
    assert [name for name, _, _ in queue.enqueued][-1] == "build_interviewer_brief"
    assert (await client.get(f"/sessions/{record['id']}")).json() == record
    second = (await create(client, job["id"], mode="coach")).json()
    listed = (await client.get(f"/job-targets/{job['id']}/sessions")).json()
    # Newest first; both rows can share a created_at in SQLite, so compare as a set.
    assert {s["id"] for s in listed} == {second["id"], record["id"]}
    async with sessionmaker() as db:
        target = await db.get(JobTarget, __import__("uuid").UUID(job["id"]))
        assert target is not None and target.level == "staff_principal"  # IV-6


async def test_sessions_are_private(
    client: httpx.AsyncClient, app: Any, fake_fixtures: Path
) -> None:
    job = await ready_job(client, fake_fixtures)
    record = (await create(client, job["id"])).json()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await sign_in(other, "other@example.com")
        assert (await other.get(f"/sessions/{record['id']}")).status_code == 404
        assert (await create(other, job["id"])).status_code == 404
        assert (await other.post(f"/sessions/{record['id']}/end")).status_code == 404


async def test_pl7_text_session_runs_to_the_end_and_is_scored(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """PL-7 and IV-7: a whole text session; turns are saved; the end bills and starts scoring."""
    job = await ready_job(client, fake_fixtures)
    record = (await create(client, job["id"], channel="text")).json()
    sid = record["id"]
    opened = (await client.post(f"/sessions/{sid}/text/open")).json()
    assert [t["phase"] for t in opened["turns"]] == ["intro"]
    queue.run_jobs = False  # the scorer job is checked as queued, not run
    phase, ended = "intro", False
    for _ in range(80):
        # In the candidate questions phase, the candidate has none, so the interviewer wraps up.
        answer = "No, thanks." if phase == "candidate_questions" else "I led the rollout."
        out = (await client.post(f"/sessions/{sid}/text/turn", json={"text": answer})).json()
        phase, ended = out["phase"], out["ended"]
        if ended:
            break
    assert ended
    final = (await client.get(f"/sessions/{sid}")).json()
    assert final["status"] == "scoring"
    assert final["started_at"] is not None and final["ended_at"] is not None
    assert [name for name, _, _ in queue.enqueued][-1] == "score_session"
    async with sessionmaker() as db:
        rows = list(
            await db.scalars(
                select(TurnRow).where(TurnRow.session_id == __import__("uuid").UUID(sid))
            )
        )
        session = await db.get(InterviewSession, __import__("uuid").UUID(sid))
    phases = {row.phase for row in rows}
    assert {Phase.INTRO, Phase.CORE, Phase.WRAP_UP} <= phases
    assert {row.speaker for row in rows} == {Speaker.INTERVIEWER, Speaker.CANDIDATE}
    assert all((row.question_ref is not None) == (row.phase == Phase.CORE) for row in rows)
    assert session is not None
    assert session.model_profile == "fake" and session.interviewer_model_id
    assert session.prompt_version and "interviewer/turn" in session.prompt_version
    # After the end, the text channel refuses more turns.
    late = await client.post(f"/sessions/{sid}/text/turn", json={"text": "Hello?"})
    assert late.status_code == 409


async def test_iv8_coach_commands_only_in_coach_mode(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def allow(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(sessions_router, "ensure_can_start_session", allow)  # 2 sessions here
    job = await ready_job(client, fake_fixtures)
    realistic = (await create(client, job["id"], channel="text")).json()["id"]
    await client.post(f"/sessions/{realistic}/text/open")
    refused = await client.post(f"/sessions/{realistic}/coach", json={"command": "hint"})
    assert refused.status_code == 409
    coach = (await create(client, job["id"], channel="text", mode="coach")).json()["id"]
    await client.post(f"/sessions/{coach}/text/open")
    for answer in ("Thanks, happy to be here.", "Sounds good."):
        await client.post(f"/sessions/{coach}/text/turn", json={"text": answer})
    hint = (await client.post(f"/sessions/{coach}/coach", json={"command": "hint"})).json()
    assert len(hint["turns"]) == 1 and hint["turns"][0]["phase"] == "core"
    for command in ("pause", "resume"):
        resp = await client.post(f"/sessions/{coach}/coach", json={"command": command})
        assert resp.status_code == 200 and resp.json()["turns"] == []


async def test_bl2_ending_an_unstarted_session_uses_no_free_interview(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any
) -> None:
    """BL-2: a session that never started is marked failed, is not scored, and is free."""
    job = await ready_job(client, fake_fixtures)
    first = (await create(client, job["id"])).json()["id"]
    queue.run_jobs = False
    ended = (await client.post(f"/sessions/{first}/end")).json()
    assert ended["status"] == "failed" and ended["minutes_billed"] == 0
    assert "score_session" not in [name for name, _, _ in queue.enqueued]
    again = (await client.post(f"/sessions/{first}/end")).json()  # safe to call twice
    assert again["status"] == "failed"
    queue.run_jobs = True
    assert (await create(client, job["id"])).status_code == 201


async def test_bl2_free_plan_allows_one_started_interview(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    job = await ready_job(client, fake_fixtures)
    record = (await create(client, job["id"], channel="text")).json()
    await client.post(f"/sessions/{record['id']}/text/open")  # started: the free interview
    blocked = await create(client, job["id"])
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "upgrade_required"
    async with sessionmaker() as db:
        count = await db.scalar(select(func.count()).select_from(InterviewSession))
    assert count == 1


async def test_text_channel_rules(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = await ready_job(client, fake_fixtures)
    voice = (await create(client, job["id"])).json()["id"]
    assert (await client.post(f"/sessions/{voice}/text/open")).status_code == 409
    text = (await create(client, job["id"], channel="text")).json()["id"]
    turn = await client.post(f"/sessions/{text}/text/turn", json={"text": "Hi"})
    assert turn.status_code == 409  # not open yet
    monkeypatch.setattr(sessions_router, "_text_allowed", lambda: False)
    assert (await create(client, job["id"], channel="text")).status_code == 403
    assert (await client.post(f"/sessions/{text}/text/open")).status_code == 404


async def test_job_must_be_read_first(client: httpx.AsyncClient, queue: Any) -> None:
    queue.run_jobs = False  # the job posting stays unread
    target = (await client.post("/job-targets", json={"text": "Senior engineer at Acme"})).json()
    resp = await create(client, target["job_target"]["id"])
    assert resp.status_code == 409


def test_session_status_values_are_known() -> None:
    assert {s.value for s in sessions_router.OPEN} == {"created", "in_progress", "interrupted"}
    assert SessionStatus.SCORING not in sessions_router.OPEN
