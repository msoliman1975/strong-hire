"""Simulations in the admin api (docs/admin-spec.md, SM): the form, Start with its gates, the
queue, cancel, keep and delete, the runs list, the replay and the audio's Range support."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.auth.settings import get_auth_settings
from strong_api.main import create_app
from strong_core import runtime_settings as rs
from strong_core import sim as core_sim
from strong_core.config import get_settings
from strong_core.db.models import AuditLog, Scorecard, SimRun, UsageEvent, User
from strong_core.schemas import HireSignal, SessionStatus, UsageComponent
from strong_core.schemas.enums import SimRunStatus

from .accounts_support import add_session
from .conftest import InlineQueue, sign_in

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
SIM = "sim@getstronghire.com"
WRITE = {"X-Admin-Request": "1"}
RUN = {"persona": "backend-senior", "duration_min": 10, "channel": "voice"}


async def _ok() -> None:
    return None


@pytest.fixture
def results(tmp_path: Path) -> Path:
    folder = tmp_path / "sim"
    folder.mkdir()
    return folder


@pytest.fixture
def app(
    sessionmaker: Maker, queue: InlineQueue, monkeypatch: pytest.MonkeyPatch, results: Path
) -> Iterator[FastAPI]:
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    monkeypatch.setenv("SIM_ENABLED", "true")
    monkeypatch.setenv("SIM_TOKEN", "s" * 40)
    monkeypatch.setenv("SIM_RESULTS_DIR", str(results))
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    rs.clear_cache()
    yield create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    rs.clear_cache()


async def _client(app: FastAPI, email: str) -> httpx.AsyncClient:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    await sign_in(http, email)
    return http


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    http = await _client(app, ADMIN)
    yield http
    await http.aclose()


async def _start(admin: httpx.AsyncClient, **changes: Any) -> httpx.Response:
    return await admin.post("/admin/sim/runs", json={**RUN, **changes}, headers=WRITE)


async def _set(maker: Maker, run_id: str, **values: Any) -> None:
    async with maker() as db:
        run = await db.get(SimRun, uuid.UUID(run_id))
        assert run is not None
        for key, value in values.items():
            setattr(run, key, value)
        await db.commit()


async def _actions(maker: Maker, prefix: str) -> list[str]:
    async with maker() as db:
        return list(await db.scalars(select(AuditLog.action).where(AuditLog.action.like(prefix))))


async def _sim_user(maker: Maker) -> User:
    async with maker() as db:
        user = await db.scalar(select(User).where(User.email == SIM))
        assert user is not None
        return user


# --- the form and Start ------------------------------------------------------------------------


async def test_sm1_options_offer_the_personas_lengths_estimates_and_gate(
    app: FastAPI, admin: httpx.AsyncClient
) -> None:
    """SM-1: the 6 personas with their posting, choices, an estimate per length, the gate."""
    other = await _client(app, "dev@example.com")
    assert (await other.get("/admin/sim/options")).status_code == 404
    await other.aclose()

    body = (await admin.get("/admin/sim/options")).json()
    assert [p["id"] for p in body["personas"]] == list(core_sim.PERSONAS)
    assert body["personas"][0]["posting"] == "swe-stripe-backend"
    assert body["durations"] == [10, 30, 45]
    assert [e["duration_min"] for e in body["estimates"]] == [10, 30, 45]
    assert body["estimates"][0]["total_usd"] < body["estimates"][2]["total_usd"]
    voice_only = {b["id"] for b in body["behaviors"] if b["voice_only"]}
    assert voice_only == {"interrupts", "drops_connection"}
    assert body["channels"][0] == "voice"
    assert body["budget"] is None  # the fake gateway has no sim key
    assert body["gate"] == {"ok": True, "retry": False, "reason": None}
    assert body["queue"] == {"active": 0, "waiting": 0, "max_waiting": 5}


async def test_sm2_start_queues_a_valid_scenario_and_audits_it(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """SM-2: a queued row in the sim org, a scenario the sim service accepts, an audit row."""
    assert (await admin.post("/admin/sim/runs", json=RUN)).status_code == 403  # AA-5
    bad = await _start(admin, channel="text", behavior="interrupts")
    assert bad.status_code == 422 and "voice" in bad.text
    assert (await _start(admin, persona="nobody")).status_code == 422
    assert (await _start(admin, duration_min=15)).status_code == 422

    resp = await _start(admin, quality="strong", behavior="silent")
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["status"] == "queued" and run["source"] == "admin"
    assert run["created_by"] == ADMIN and run["planned_s"] == 600
    assert run["scenario"]["persona"] == "backend-senior"
    assert run["scenario"]["candidate_name"] in core_sim.NAMES

    sim_user = await _sim_user(sessionmaker)  # created by the first Start
    assert sim_user.training_consent is True
    async with sessionmaker() as db:
        row = await db.get(SimRun, uuid.UUID(run["id"]))
        assert row is not None and row.org_id == sim_user.org_id
        scenario = row.scenario_json
    strong_sim = pytest.importorskip("strong_sim.scenarios")
    parsed = strong_sim.Scenario.model_validate(scenario)
    parsed.check()
    assert parsed.channel == "voice" and parsed.duration_min == 10 and parsed.quality == "strong"
    assert await _actions(sessionmaker, "sim.%") == ["sim.run_started"]


async def test_sm3_start_is_refused_with_the_reason_when_a_gate_is_closed(
    app: FastAPI,
    admin: httpx.AsyncClient,
    sessionmaker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SM-3: paused, the live-sessions limit and the budget each give 409 with a reason."""
    paused = await admin.put(
        "/admin/ops/settings/sim_paused",
        json={"value": True, "reason": "load test"},
        headers=WRITE,
    )
    assert paused.status_code == 200
    resp = await _start(admin)
    assert resp.status_code == 409 and "paused" in resp.json()["detail"]
    gate = (await admin.get("/admin/sim/options")).json()["gate"]
    assert gate["ok"] is False and "paused" in gate["reason"]
    await admin.put(
        "/admin/ops/settings/sim_paused", json={"value": False, "reason": "done"}, headers=WRITE
    )
    rs.clear_cache()

    # Three real interviews live (the default limit is 3).
    dev = await _client(app, "dev@example.com")
    await dev.aclose()
    async with sessionmaker() as db:
        user = await db.scalar(select(User).where(User.email == "dev@example.com"))
        assert user is not None
        for _ in range(3):
            await add_session(db, user.org_id, user.id, status=SessionStatus.IN_PROGRESS, minutes=5)
    resp = await _start(admin)
    assert resp.status_code == 409 and "3 real interviews are live" in resp.json()["detail"]
    gate = (await admin.get("/admin/sim/options")).json()["gate"]
    assert gate["retry"] is True
    await admin.put(
        "/admin/ops/settings/sim_max_live_sessions",
        json={"value": 0, "reason": "no limit for the test"},
        headers=WRITE,
    )
    rs.clear_cache()

    # Today's sim budget is nearly gone.
    async def low(_: Any, timeout_s: float = 10.0) -> core_sim.KeyBudget:
        return core_sim.KeyBudget(spend_usd=4.99, max_budget_usd=5.0, resets_at=None)

    monkeypatch.setattr(core_sim, "sim_key_budget", low)
    resp = await _start(admin)
    assert resp.status_code == 409 and "budget has $0.01 left" in resp.json()["detail"]
    budget = (await admin.get("/admin/sim/options")).json()["budget"]
    assert budget["limit_usd"] == 5.0 and budget["left_usd"] == pytest.approx(0.01)
    monkeypatch.undo()

    # Off on this server.
    monkeypatch.setenv("SIM_ENABLED", "false")
    get_settings.cache_clear()
    resp = await _start(admin)
    assert resp.status_code == 409 and "SIM_ENABLED" in resp.json()["detail"]
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(SimRun)) == 0


async def test_sm2_at_most_five_runs_wait_in_line(admin: httpx.AsyncClient) -> None:
    """SM-2: one active run and up to 5 more in line."""
    for _ in range(5):
        assert (await _start(admin)).status_code == 201
    resp = await _start(admin)
    assert resp.status_code == 409 and "5 runs are already waiting" in resp.json()["detail"]
    queue = (await admin.get("/admin/sim/options")).json()["queue"]
    assert queue == {"active": 0, "waiting": 5, "max_waiting": 5}


# --- cancel, keep, delete ----------------------------------------------------------------------


async def test_sm5_cancel_a_queued_run_now_and_an_active_one_through_the_service(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """SM-5: queued -> cancelled at once; active -> cancel_requested_at for the sim service."""
    queued = (await _start(admin)).json()
    assert (await admin.post(f"/admin/sim/runs/{queued['id']}/cancel", json={})).status_code == 403
    resp = await admin.post(f"/admin/sim/runs/{queued['id']}/cancel", json={}, headers=WRITE)
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    assert resp.json()["finished_at"] is not None
    again = await admin.post(f"/admin/sim/runs/{queued['id']}/cancel", json={}, headers=WRITE)
    assert again.status_code == 409

    active = (await _start(admin)).json()
    await _set(sessionmaker, active["id"], status=SimRunStatus.INTERVIEWING)
    resp = await admin.post(
        f"/admin/sim/runs/{active['id']}/cancel", json={"reason": "wrong persona"}, headers=WRITE
    )
    assert resp.json()["status"] == "interviewing"  # the sim service ends it
    async with sessionmaker() as db:
        row = await db.get(SimRun, uuid.UUID(active["id"]))
        assert row is not None and row.cancel_requested_at is not None
    assert (await _actions(sessionmaker, "sim.run_cancelled")) == ["sim.run_cancelled"] * 2


async def test_sm13_keep_and_delete_leave_a_stub_and_are_audited(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """SM-13: Keep flips the flag; Delete needs a finished run and a reason, keeps the row."""
    run = (await _start(admin)).json()
    path = f"/admin/sim/runs/{run['id']}"
    early = await admin.request("DELETE", path, json={"reason": "not needed"}, headers=WRITE)
    assert early.status_code == 409  # cancel it first
    await _set(sessionmaker, run["id"], status=SimRunStatus.DONE, run_dir="20261018-1-admin-ab")

    kept = await admin.patch(path, json={"keep": True}, headers=WRITE)
    assert kept.status_code == 200 and kept.json()["keep"] is True
    no_reason = await admin.request("DELETE", path, json={}, headers=WRITE)
    assert no_reason.status_code == 422
    gone = await admin.request("DELETE", path, json={"reason": "bad audio"}, headers=WRITE)
    assert gone.status_code == 200
    body = gone.json()
    assert body["deleted_by"] == ADMIN and body["delete_reason"] == "bad audio"
    assert body["deleted_at"] is not None
    assert (
        await admin.request("DELETE", path, json={"reason": "x" * 5}, headers=WRITE)
    ).status_code == 409
    assert (await admin.patch(path, json={"keep": False}, headers=WRITE)).status_code == 409
    listed = (await admin.get("/admin/sim/runs")).json()["runs"]
    assert [r["id"] for r in listed] == [run["id"]] and listed[0]["deleted_at"] is not None
    assert await _actions(sessionmaker, "sim.run_%") == [
        "sim.run_started",
        "sim.run_keep",
        "sim.run_deleted",
    ]


# --- the runs list (SM-4, SM-12) ---------------------------------------------------------------


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _report_row(sid: uuid.UUID, **changes: Any) -> dict[str, Any]:
    return {
        "scenario_id": "beh-strong",
        "session_id": str(sid),
        "channel": "text",
        "interview_type": "behavioral",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 10,
        "resume": "new-grad-swe",
        "quality": "strong",
        "behavior": "normal",
        "status": "ok",
        "failed_rules": ["tone"],
        "problems": 1,
        "hire_signal": "Hire",
        "session_s": 612.0,
        "latency_p50_ms": 640.0,
        "sim_cost_usd": 0.05,
        **changes,
    }


async def test_sm12_list_shows_admin_and_suite_runs_with_costs_and_filters(
    admin: httpx.AsyncClient, sessionmaker: Maker, results: Path
) -> None:
    """SM-12 and SM-4: both sources, cost = sim side + app side, filters, poll while running."""
    first = (await _start(admin)).json()
    second = (await _start(admin, channel="text")).json()
    sim_user = await _sim_user(sessionmaker)
    async with sessionmaker() as db:
        session = await add_session(db, sim_user.org_id, sim_user.id)
        db.add(
            UsageEvent(
                org_id=sim_user.org_id,
                session_id=session.id,
                component=UsageComponent.LLM,
                units=Decimal(1000),
                cost_usd=Decimal("0.03"),
            )
        )
        await db.commit()
    await _set(
        sessionmaker,
        first["id"],
        status=SimRunStatus.DONE,
        run_dir="20261018-100000-admin-aaaa",
        session_id=session.id,
        cost_sim_usd=Decimal("0.0400"),
        progress_s=590,
    )
    _write(
        results / "20261018-100000-admin-aaaa" / "report.json",
        {"summary": {"suite": "admin"}, "sessions": [_report_row(session.id, channel="voice")]},
    )
    suite_sid = uuid.uuid4()
    _write(
        results / "20261001-090000-text-smoke-bbbb" / "report.json",
        {
            "summary": {"suite": "text-smoke", "started_at": "2026-10-01T09:00:00+00:00"},
            "sessions": [_report_row(suite_sid, status="error", error="provider down")],
        },
    )

    body = (await admin.get("/admin/sim/runs")).json()
    assert body["any_unfinished"] is True  # the second run is still queued
    runs = {r["id"]: r for r in body["runs"]}
    done = runs[first["id"]]
    assert done["files"] is True and done["progress_s"] == 590
    assert done["failed_rules"] == ["tone"] and done["latency_p50_ms"] == 640.0
    assert done["cost_sim_usd"] == 0.04 and done["cost_app_usd"] == 0.03
    assert done["cost_total_usd"] == pytest.approx(0.07)
    suite = runs["20261001-090000-text-smoke-bbbb/beh-strong"]
    assert suite["source"] == "suite" and suite["suite"] == "text-smoke"
    assert suite["status"] == "failed" and suite["status_reason"] == "provider down"
    assert suite["session_id"] == str(suite_sid) and suite["scenario"]["persona"] == "new-grad-swe"
    assert [r["id"] for r in body["runs"]][-1] == suite["id"]  # newest first

    only_suite = (await admin.get("/admin/sim/runs", params={"source": "suite"})).json()["runs"]
    assert [r["id"] for r in only_suite] == [suite["id"]]
    queued = (await admin.get("/admin/sim/runs", params={"status": "queued"})).json()["runs"]
    assert [r["id"] for r in queued] == [second["id"]]
    text = (await admin.get("/admin/sim/runs", params={"channel": "text"})).json()["runs"]
    assert {r["id"] for r in text} == {second["id"], suite["id"]}
    one = (await admin.get(f"/admin/sim/runs/{first['id']}")).json()
    assert one["hire_signal"] == "Hire" and one["cost_app_usd"] == 0.03
    assert (await admin.get(f"/admin/sim/runs/{uuid.uuid4()}")).status_code == 404


# --- replay and audio (SM-6..SM-11, SM-16) -----------------------------------------------------


async def _sim_session(app: FastAPI, sessionmaker: Maker, results: Path) -> uuid.UUID:
    """A finished sim voice session with a full run folder and a scorecard."""
    sim = await _client(app, "unused@example.com")
    assert (await sim.post("/auth/sim-login", headers={"X-Sim-Token": "s" * 40})).status_code == 204
    await sim.aclose()
    user = await _sim_user(sessionmaker)
    async with sessionmaker() as db:
        session = await add_session(db, user.org_id, user.id)
        db.add(
            Scorecard(
                org_id=user.org_id,
                session_id=session.id,
                hire_signal=HireSignal.LEAN_HIRE,
                rationale="Clear ownership.",
                competency_scores_json=[
                    {
                        "competency": "ownership",
                        "score": 3,
                        "justification": "Led the migration.",
                        "quotes": ["I led it."],
                    }
                ],
                value_scores_json=[],
                per_question_json=[],
                scorer_model="scorer:test",
                rubric_version="scorer/scorecard.v1",
            )
        )
        await db.commit()
        sid = session.id
    folder = results / "20261018-110000-admin-cccc" / str(sid)
    _write(
        folder / "transcript.json",
        [
            {"speaker": "interviewer", "text": "Hi.", "start_ms": 1000, "end_ms": 3000},
            {"speaker": "candidate", "text": "Hello.", "start_ms": 3500, "end_ms": 5000},
            {
                "speaker": "interviewer",
                "text": "Tell me more.",
                "start_ms": 5600,
                "end_ms": 8000,
                "latency_ms": 600,
                "phase": "core",
            },
            {"speaker": "candidate", "text": "Sure.", "start_ms": 8200, "end_ms": 9000},
            {
                "speaker": "interviewer",
                "text": "Why?",
                "start_ms": 11000,
                "end_ms": 12000,
                "latency_ms": 2000,
            },
        ],
    )
    _write(
        folder / "judge.json",
        {
            "rubric": "judge/transcript.v1",
            "model": "sim-judge",
            "rules": [
                {"rule": "tone", "verdict": "fail", "reason": "Curt at 00:11."},
                {"rule": "phases", "verdict": "pass", "reason": "All phases."},
            ],
            "problems": [{"at": "00:11", "problem": "Curt reply"}, {"at": "late", "problem": "x"}],
        },
    )
    _write(
        folder / "meta.json",
        {
            "timing": "audio",
            "scenario": {"channel": "voice", "resume": "backend-senior", "duration_min": 10},
        },
    )
    (folder / "audio.ogg").write_bytes(b"OggS0123456789")
    return sid


async def test_sm7_to_sm11_replay_returns_lines_latency_judge_scorecard_and_audio(
    app: FastAPI, admin: httpx.AsyncClient, sessionmaker: Maker, results: Path
) -> None:
    """SM-8 lines on the audio clock, SM-9 p50/p90 and slow turns, SM-10 judge with times,
    SM-11 scorecard, SM-7 audio info; SM-16 the interview page links to it."""
    sid = await _sim_session(app, sessionmaker, results)
    resp = await admin.get(f"/admin/sessions/{sid}/replay")
    assert resp.status_code == 200, resp.text
    replay = resp.json()
    assert replay["timing"] == "audio" and replay["run_dir"] == "20261018-110000-admin-cccc"
    assert [x["speaker"] for x in replay["lines"]][:2] == ["interviewer", "candidate"]
    assert replay["lines"][2]["latency_ms"] == 600 and replay["lines"][2]["phase"] == "core"
    assert replay["latency"] == {
        "n": 2,
        "p50_ms": 600,
        "p90_ms": 2000,
        "slow_turns": 1,
        "ok_ms": 800,
        "slow_ms": 1500,
    }
    judge = replay["judge"]
    assert [r["verdict"] for r in judge["rules"]] == ["fail", "pass"]
    assert judge["problems"][0] == {"at": "00:11", "at_ms": 11000, "problem": "Curt reply"}
    assert judge["problems"][1]["at_ms"] is None
    assert replay["scorecard"]["hire_signal"] == "Lean Hire"
    assert replay["audio"] == {"available": True, "bytes": 14}
    assert replay["scenario"]["persona"] == "backend-senior"
    detail = (await admin.get(f"/admin/sessions/{sid}")).json()
    assert detail["replay_available"] is True
    assert await _actions(sessionmaker, "admin.replay_viewed") == ["admin.replay_viewed"]


async def test_sm8_replay_without_audio_times_falls_back_and_is_only_for_the_sim_user(
    app: FastAPI, admin: httpx.AsyncClient, sessionmaker: Maker, results: Path
) -> None:
    """SM-8: an older run (no "timing": "audio") is approximate; a real user's session is 404."""
    sid = await _sim_session(app, sessionmaker, results)
    meta = results / "20261018-110000-admin-cccc" / str(sid) / "meta.json"
    _write(meta, {"timing": "server"})
    assert (await admin.get(f"/admin/sessions/{sid}/replay")).json()["timing"] == "approximate"

    dev = await _client(app, "dev@example.com")
    await dev.put("/account/consent", json={"training_consent": True})
    await dev.aclose()
    async with sessionmaker() as db:
        user = await db.scalar(select(User).where(User.email == "dev@example.com"))
        assert user is not None
        real = await add_session(db, user.org_id, user.id)
    assert (await admin.get(f"/admin/sessions/{real.id}/replay")).status_code == 404
    assert (await admin.get(f"/admin/sessions/{real.id}")).json()["replay_available"] is False
    other = await _client(app, "dev@example.com")
    assert (await other.get(f"/admin/sessions/{sid}/replay")).status_code == 404
    await other.aclose()


async def test_sm7_audio_answers_range_requests_and_audits_once(
    app: FastAPI, admin: httpx.AsyncClient, sessionmaker: Maker, results: Path
) -> None:
    """SM-7: 206 with the asked bytes, so the player seeks without downloading the file."""
    sid = await _sim_session(app, sessionmaker, results)
    url = f"/admin/sessions/{sid}/audio"
    first = await admin.get(url, headers={"Range": "bytes=0-"})
    assert first.status_code == 206 and first.content == b"OggS0123456789"
    seek = await admin.get(url, headers={"Range": "bytes=4-7"})
    assert seek.status_code == 206 and seek.content == b"0123"
    assert seek.headers["content-range"] == "bytes 4-7/14"
    assert seek.headers["accept-ranges"] == "bytes"
    whole = await admin.get(url)
    assert whole.status_code == 200 and whole.content == b"OggS0123456789"
    assert await _actions(sessionmaker, "admin.audio_downloaded") == ["admin.audio_downloaded"] * 2


async def test_sm4_list_stops_polling_when_every_run_has_ended(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """SM-4: the list polls only while a run is not finished; the reason shows."""
    run = (await _start(admin)).json()
    await _set(
        sessionmaker,
        run["id"],
        status=SimRunStatus.FAILED,
        status_reason="waited 30 min",
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    body = (await admin.get("/admin/sim/runs")).json()
    assert body["any_unfinished"] is False
    assert body["runs"][0]["status_reason"] == "waited 30 min"
