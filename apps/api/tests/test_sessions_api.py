"""Sessions API (P7): create, read, end, and the text channel (IV-7, IV-8, PL-7, BL-2, FB-3)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.billing.entitlements import count_free_interviews_used
from strong_api.sessions import router as sessions_router  # the module
from strong_api.sessions.failure import BRIEF_STALE_AFTER
from strong_core.config import get_settings
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Turn as TurnRow
from strong_core.schemas import Phase, SessionStatus, Speaker
from strong_worker.gap import jobs as gap_jobs
from strong_worker.gap.brief import BriefError
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
    # 10 minutes: the test accounts are on the free plan, which allows mini interviews only.
    base = {
        "interview_type": "behavioral",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 10,
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


async def test_bl2_free_plan_allows_two_started_mini_interviews(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    job = await ready_job(client, fake_fixtures)
    for _ in range(2):
        record = (await create(client, job["id"], channel="text")).json()
        await client.post(f"/sessions/{record['id']}/text/open")  # started: a free interview
    blocked = await create(client, job["id"])
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "upgrade_required"
    async with sessionmaker() as db:
        count = await db.scalar(select(func.count()).select_from(InterviewSession))
    assert count == 2


@pytest.mark.parametrize("minutes", [30, 45])
async def test_bl2_free_plan_cannot_create_a_full_interview(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
    minutes: int,
) -> None:
    job = await ready_job(client, fake_fixtures)
    blocked = await create(client, job["id"], duration_min=minutes)
    assert blocked.status_code == 402
    detail = blocked.json()["detail"]
    assert detail["code"] == "full_interview_requires_plan"
    assert "mini interviews" in detail["message"]
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(InterviewSession)) == 0
    assert (await create(client, job["id"], duration_min=10)).status_code == 201


async def test_a_paid_30_minute_text_session_has_candidate_questions(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full session still runs small talk and candidate questions; a mini skips both."""

    async def allow(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(sessions_router, "ensure_can_start_session", allow)  # as a paid plan
    job = await ready_job(client, fake_fixtures)
    seen: dict[int, set[str]] = {}
    for minutes in (30, 10):
        record = (await create(client, job["id"], channel="text", duration_min=minutes)).json()
        assert record["config"]["duration_min"] == minutes
        sid = record["id"]
        await client.post(f"/sessions/{sid}/text/open")
        queue.run_jobs = False  # the scorer job is not run here
        phases: set[str] = set()
        for _ in range(80):
            out = (await client.post(f"/sessions/{sid}/text/turn", json={"text": "No."})).json()
            phases.update(t["phase"] for t in out["turns"])
            if out["ended"]:
                break
        seen[minutes] = phases
        queue.run_jobs = True  # the next session's brief job runs inline
    assert {"small_talk", "candidate_questions"} <= seen[30]
    assert not {"small_talk", "candidate_questions"} & seen[10]


async def test_text_channel_rules(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = await ready_job(client, fake_fixtures)
    voice = (await create(client, job["id"])).json()["id"]
    assert (await client.post(f"/sessions/{voice}/text/open")).status_code == 409
    text = (await create(client, job["id"], channel="text")).json()["id"]
    turn = await client.post(f"/sessions/{text}/text/turn", json={"text": "Hi"})
    assert turn.status_code == 409  # not open yet

    async def never(*_: Any) -> bool:
        return False

    monkeypatch.setattr(sessions_router, "_text_allowed", never)
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


async def test_voice_join_starts_the_session_and_returns_a_room_token(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """The first join starts the session; a second join (reconnect) keeps the same room."""
    from livekit import api as livekit_api

    job = await ready_job(client, fake_fixtures)
    sid = (await create(client, job["id"])).json()["id"]
    resp = await client.post(f"/sessions/{sid}/voice/join")
    assert resp.status_code == 200, resp.text
    join = resp.json()
    assert join["room"] == f"session-{sid}" and join["identity"].startswith("candidate-")
    claims = livekit_api.TokenVerifier("devkey", "secret").verify(join["token"])
    assert claims.video is not None and claims.video.room == join["room"]
    assert claims.video.room_join and claims.video.can_publish_data
    record = (await client.get(f"/sessions/{sid}")).json()
    assert record["status"] == "in_progress" and record["started_at"] is not None
    again = (await client.post(f"/sessions/{sid}/voice/join")).json()
    assert again["room"] == join["room"]
    started = (await client.get(f"/sessions/{sid}")).json()["started_at"]
    assert started == record["started_at"]


async def test_voice_join_rules(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def always(*_: Any) -> bool:
        return True

    monkeypatch.setattr(sessions_router, "_text_allowed", always)
    job = await ready_job(client, fake_fixtures)
    text = (await create(client, job["id"], channel="text")).json()["id"]
    assert (await client.post(f"/sessions/{text}/voice/join")).status_code == 409
    voice = (await create(client, job["id"])).json()["id"]
    await client.post(f"/sessions/{voice}/end")
    assert (await client.post(f"/sessions/{voice}/voice/join")).status_code == 409


async def test_internal_end_needs_the_shared_token(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any
) -> None:
    """The voice agent ends a started session: it is billed and scored. Others get 403."""
    job = await ready_job(client, fake_fixtures)
    sid = (await create(client, job["id"])).json()["id"]
    await client.post(f"/sessions/{sid}/voice/join")
    url = f"/internal/sessions/{sid}/end"
    assert (await client.post(url, json={})).status_code == 403
    wrong = {"X-Internal-Token": "guess"}
    assert (await client.post(url, json={}, headers=wrong)).status_code == 403
    queue.run_jobs = False
    token = {"X-Internal-Token": "dev-internal-token"}
    resp = await client.post(url, json={"interrupted": True}, headers=token)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "scoring"
    assert [name for name, _, _ in queue.enqueued][-1] == "score_session"
    missing = await client.post(
        f"/internal/sessions/{__import__('uuid').uuid4()}/end", json={}, headers=token
    )
    assert missing.status_code == 404
    assert (
        "/internal/sessions/{session_id}/end"
        not in (await client.get("/openapi.json")).json()["paths"]
    )


async def test_brief_failure_fails_the_session_with_a_plain_reason(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The brief job fails for good: the session is failed before it started, with a reason,
    the debrief says it did not start, and no free interview or minutes are used (BL-2)."""

    async def fails(*_: object, **__: object) -> Any:
        raise BriefError("Brief failed after 2 attempts: credit balance too low")

    monkeypatch.setattr(gap_jobs, "build_brief", fails)
    queue.ctx["job_try"] = gap_jobs.BRIEF_MAX_TRIES  # the last try
    job = await ready_job(client, fake_fixtures)
    record = (await create(client, job["id"])).json()
    assert record["status"] == "failed" and record["brief_ready"] is False
    assert record["started_at"] is None and record["minutes_billed"] == 0
    assert "could not prepare your interviewer" in record["failure_reason"]
    fetched = (await client.get(f"/sessions/{record['id']}")).json()
    assert fetched["failure_reason"] == record["failure_reason"]

    debrief = (await client.get(f"/sessions/{record['id']}/debrief")).json()
    assert debrief["status"] == "not_started"
    assert debrief["session"]["failure_reason"] == record["failure_reason"]
    scoring = await client.post(f"/sessions/{record['id']}/scoring")
    assert scoring.status_code == 409
    assert (await client.post(f"/sessions/{record['id']}/voice/join")).status_code == 409

    async with sessionmaker() as db:
        row = await db.get(InterviewSession, uuid.UUID(record["id"]))
        assert row is not None
        assert await count_free_interviews_used(db, row.org_id) == 0
    del queue.ctx["job_try"]
    monkeypatch.undo()
    assert (await create(client, job["id"])).status_code == 201  # "Try again" works


async def test_ended_before_start_has_its_own_reason(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    job = await ready_job(client, fake_fixtures)
    sid = (await create(client, job["id"])).json()["id"]
    ended = (await client.post(f"/sessions/{sid}/end")).json()
    assert ended["failure_reason"].startswith("This interview was ended before it started")
    debrief = (await client.get(f"/sessions/{sid}/debrief")).json()
    assert debrief["status"] == "not_started"


async def test_a_lost_brief_job_fails_the_session_after_a_while(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """If the worker job is lost, the page polling GET /sessions/{id} still stops waiting."""
    job = await ready_job(client, fake_fixtures)
    queue.run_jobs = False  # the brief job never runs
    sid = (await create(client, job["id"])).json()["id"]
    waiting = (await client.get(f"/sessions/{sid}")).json()
    assert waiting["status"] == "created" and waiting["failure_reason"] is None
    async with sessionmaker() as db:
        row = await db.get(InterviewSession, uuid.UUID(sid))
        assert row is not None
        row.created_at = datetime.now(UTC) - BRIEF_STALE_AFTER * 2
        await db.commit()
    failed = (await client.get(f"/sessions/{sid}")).json()
    assert failed["status"] == "failed"
    assert "could not prepare your interviewer" in failed["failure_reason"]


async def test_text_turn_while_the_interviewer_is_replying_is_refused(
    client: httpx.AsyncClient, fake_fixtures: Path, app: Any
) -> None:
    """Bug 4: a second turn for the same answer must not get a second reply."""
    job = await ready_job(client, fake_fixtures)
    sid = (await create(client, job["id"], channel="text")).json()["id"]
    await client.post(f"/sessions/{sid}/text/open")
    runner = app.state.text_runners[uuid.UUID(sid)]
    async with runner._lock:  # a reply is being prepared
        busy = await client.post(f"/sessions/{sid}/text/turn", json={"text": "Hello"})
    assert busy.status_code == 409
    assert busy.json()["detail"] == "The interviewer is still replying."
    ok = await client.post(f"/sessions/{sid}/text/turn", json={"text": "Hello"})
    assert ok.status_code == 200
