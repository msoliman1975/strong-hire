"""Debrief and progress endpoints (FB-1, FB-2, FB-3, PR-1, PR-2)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.inputs.queue import JobInfo
from strong_api.main import create_app
from strong_api.scoring import SCORE_SESSION
from strong_api.scoring.progress import competency_trends, recommend_next_session
from strong_core.config import find_repo_root
from strong_core.db.models import Company, InterviewSession, JobTarget, Org, User
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import Turn as TurnRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import (
    AuthProvider,
    Competency,
    Difficulty,
    InterviewType,
    Mode,
    PlannedSession,
    ProfileStatus,
    ProgressSnapshot,
    SessionStatus,
)
from strong_worker.scoring import jobs
from strong_worker.scoring.testing import RATIONALE, ScriptedBackend, load_scripted, scorecard_reply

from .conftest import sign_in

C = Competency
DEV_USER_EMAIL = "dev@example.com"  # the user sign_in() creates
EXAMPLE_PROFILE = find_repo_root() / "profiles" / "examples" / "example-corp.json"
GAP_FIXTURE = (
    find_repo_root() / "packages/core/src/strong_core/gateway/fixtures/planner/GapAnalysis.json"
)


class ScoringQueue:
    """Runs the real scoring job in the test, with a scripted fake model."""

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self.maker = maker
        self.replies: list[dict[str, Any] | str] = []
        self.run_jobs = True
        self.enqueued: list[tuple[str, str, dict[str, Any]]] = []
        self.results: dict[str, dict[str, Any]] = {}

    async def enqueue(self, function: str, job_id: str, **kwargs: Any) -> None:
        self.enqueued.append((function, job_id, kwargs))
        if self.run_jobs:
            gw = ModelGateway(fake_models_config(), fake=ScriptedBackend(self.replies))
            ctx = {jobs.CTX_KEY: jobs.ScoringContext(sessionmaker=self.maker, gateway=gw)}
            self.results[job_id] = await getattr(jobs, function)(ctx, **kwargs)

    async def info(self, job_id: str) -> JobInfo:
        return JobInfo(job_id, "complete", result=self.results.get(job_id))

    async def close(self) -> None:
        return None


@pytest.fixture
def squeue(sessionmaker: async_sessionmaker[AsyncSession]) -> ScoringQueue:
    return ScoringQueue(sessionmaker)


@pytest.fixture
async def sclient(
    sessionmaker: async_sessionmaker[AsyncSession], squeue: ScoringQueue
) -> AsyncIterator[httpx.AsyncClient]:
    async def ok() -> None:
        return None

    app: FastAPI = create_app({"database": ok}, sessionmaker=sessionmaker, queue=squeue)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, DEV_USER_EMAIL)
        yield http


async def dev_account(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as db:
        user = await db.scalar(select(User).where(User.email == DEV_USER_EMAIL))
        if user is None:
            org = Org(name="Dev org")
            db.add(org)
            await db.flush()
            user = User(org_id=org.id, email=DEV_USER_EMAIL, auth_provider=AuthProvider.DEV)
            db.add(user)
            await db.commit()
        return user.org_id, user.id


async def make_target(
    maker: async_sessionmaker[AsyncSession], company: bool = False, gap: bool = False
) -> uuid.UUID:
    org_id, user_id = await dev_account(maker)
    async with maker() as db:
        company_id = None
        if company:
            company_id = await db.scalar(select(Company.id).where(Company.slug == "stripe"))
            data = json.loads(EXAMPLE_PROFILE.read_text(encoding="utf-8"))
            db.add(
                ProfileRow(
                    company_id=company_id,
                    version=1,
                    status=ProfileStatus.PUBLISHED,
                    profile_json=data,
                    sources_json=data["sources"],
                )
            )
        target = JobTarget(org_id=org_id, user_id=user_id, company_id=company_id)
        db.add(target)
        await db.flush()
        if gap:
            analysis = json.loads(GAP_FIXTURE.read_text(encoding="utf-8"))
            db.add(
                GapRow(
                    org_id=org_id,
                    job_target_id=target.id,
                    resume_id=await _resume(db, org_id, user_id),
                    match_score=analysis["match_score"],
                    breakdown_json=analysis,
                    session_plan_json=analysis["session_plan"],
                    model_version="fake",
                )
            )
        await db.commit()
        return target.id


async def _resume(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    from strong_core.db.models import Resume

    row = Resume(org_id=org_id, user_id=user_id)
    db.add(row)
    await db.flush()
    return row.id


async def make_session(
    maker: async_sessionmaker[AsyncSession],
    target_id: uuid.UUID,
    transcript: str = "beh-01",
    mode: Mode = Mode.REALISTIC,
    status: SessionStatus = SessionStatus.SCORING,
    ended_minutes_ago: float = 0,
    duration_min: int = 30,
) -> uuid.UUID:
    org_id, _ = await dev_account(maker)
    brief, turns = load_scripted(transcript)
    session_config = brief.session.model_copy(update={"mode": mode, "duration_min": duration_min})
    brief = brief.model_copy(update={"session": session_config})
    if duration_min == 10:  # a mini brief: no curveball, 1 probe, the 10-minute plan
        brief = brief.model_copy(
            update={"curveball": None, "max_probes_per_question": 1, "time_plan": []}
        )
    async with maker() as db:
        target = await db.get(JobTarget, target_id)
        assert target is not None
        ended = datetime.now(UTC) - timedelta(minutes=ended_minutes_ago)
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target_id,
            type=brief.session.interview_type,
            difficulty=brief.session.difficulty,
            mode=mode,
            duration_min=duration_min,
            profile_version=1 if target.company_id else None,
            brief_json=brief.model_dump(mode="json"),
            status=status,
            started_at=ended - timedelta(minutes=30),
            ended_at=None if status == SessionStatus.IN_PROGRESS else ended,
            minutes_billed=30,
        )
        db.add(session)
        await db.flush()
        db.add_all(TurnRow(org_id=org_id, session_id=session.id, **t.model_dump()) for t in turns)
        await db.commit()
        return session.id


def replies(transcript: str = "beh-01", scores: dict[str, int] | int = 3) -> list[Any]:
    brief, turns = load_scripted(transcript)
    return [scorecard_reply(brief, turns, scores), RATIONALE]


def test_queue_name_matches_the_worker_job() -> None:
    assert SCORE_SESSION in {f.__name__ for f in jobs.FUNCTIONS}


async def test_fb1_fb2_fb3_debrief_after_scoring(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], squeue: ScoringQueue
) -> None:
    target = await make_target(sessionmaker, gap=True)
    sid = await make_session(sessionmaker, target)
    squeue.replies = replies(scores={"collaboration": 2})

    resp = await sclient.post(f"/sessions/{sid}/scoring")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    result = squeue.results[job_id]
    assert result["outcome"] == "scored"
    assert result["ready_after_s"] < 60  # FB-3

    debrief = (await sclient.get(f"/sessions/{sid}/debrief")).json()
    assert debrief["status"] == "ready"
    card = debrief["scorecard"]
    assert card["hire_signal"] in {"Hire", "Lean Hire"}  # FB-1
    assert card["rationale"] == RATIONALE
    assert card["per_question"] and all(q["scores"] for q in card["per_question"])  # FB-2
    assert card["value_scores"] == []
    assert debrief["generic_mode"] is True
    assert debrief["values_framework"] is None
    assert debrief["session"]["config"]["interview_type"] == "behavioral"
    nxt = debrief["next_session"]  # PR-2
    assert nxt["interview_type"] == "behavioral"
    assert "Collaboration" in nxt["focus_topics"]

    again = await sclient.post(f"/sessions/{sid}/scoring")
    assert again.status_code == 409


async def test_debrief_states_scoring_and_failed(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], squeue: ScoringQueue
) -> None:
    target = await make_target(sessionmaker)
    sid = await make_session(sessionmaker, target)
    debrief = (await sclient.get(f"/sessions/{sid}/debrief")).json()
    assert debrief["status"] == "scoring"
    assert debrief["scorecard"] is None and debrief["next_session"] is None

    brief, turns = load_scripted("beh-01")
    squeue.replies = [scorecard_reply(brief, turns, 3, quote="Never said this at all")]
    assert (await sclient.post(f"/sessions/{sid}/scoring")).status_code == 202
    assert (await sclient.get(f"/sessions/{sid}/debrief")).json()["status"] == "failed"

    # A retry after the failure works.
    squeue.replies = replies()
    assert (await sclient.post(f"/sessions/{sid}/scoring")).status_code == 202
    assert (await sclient.get(f"/sessions/{sid}/debrief")).json()["status"] == "ready"


async def test_scoring_needs_an_ended_session(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    target = await make_target(sessionmaker)
    sid = await make_session(sessionmaker, target, status=SessionStatus.IN_PROGRESS)
    assert (await sclient.post(f"/sessions/{sid}/scoring")).status_code == 409
    # Not ended yet, so the debrief says so instead of "scoring" (the web app stops polling).
    for open_status in (
        SessionStatus.CREATED,
        SessionStatus.IN_PROGRESS,
        SessionStatus.INTERRUPTED,
    ):
        open_sid = await make_session(sessionmaker, target, status=open_status)
        debrief = (await sclient.get(f"/sessions/{open_sid}/debrief")).json()
        assert debrief["status"] == "not_ended" and debrief["scorecard"] is None
    assert (await sclient.get(f"/sessions/{uuid.uuid4()}/debrief")).status_code == 404
    assert (await sclient.get(f"/job-targets/{uuid.uuid4()}/progress")).status_code == 404


async def test_company_debrief_shows_values(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], squeue: ScoringQueue
) -> None:
    target = await make_target(sessionmaker, company=True)
    sid = await make_session(sessionmaker, target, "beh-03")
    squeue.replies = replies("beh-03")
    await sclient.post(f"/sessions/{sid}/scoring")
    debrief = (await sclient.get(f"/sessions/{sid}/debrief")).json()
    assert debrief["generic_mode"] is False
    assert debrief["values_framework"] == "Example Values"
    names = {v["value"] for v in debrief["scorecard"]["value_scores"]}
    assert names == {"Customer first", "Own the outcome"}


async def test_pr1_progress_counts_realistic_sessions_only(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], squeue: ScoringQueue
) -> None:
    target = await make_target(sessionmaker, gap=True)
    first = await make_session(sessionmaker, target, ended_minutes_ago=60)
    coach = await make_session(sessionmaker, target, mode=Mode.COACH, ended_minutes_ago=30)
    second = await make_session(sessionmaker, target)
    for sid, score in ((first, 2), (coach, 4), (second, 3)):
        squeue.replies = replies(scores=score)
        assert (await sclient.post(f"/sessions/{sid}/scoring")).status_code == 202

    progress = (await sclient.get(f"/job-targets/{target}/progress")).json()
    sessions = {s["session_id"] for s in progress["snapshots"]}
    assert sessions == {str(first), str(second)}  # the Coach session is not in the trends
    ownership = next(t for t in progress["trends"] if t["competency"] == "ownership")
    assert ownership == {
        "competency": "ownership",
        "sessions": 2,
        "first": 2.0,
        "latest": 3.0,
        "change": 1.0,
        "average": 2.5,
        "direction": "up",
    }
    # All competencies now meet the bar; the plan's technical session is not done yet.
    nxt = progress["next_session"]
    assert nxt["interview_type"] == "technical_qa"
    assert "not done it yet" in nxt["reason"]


async def test_pr1_mini_sessions_get_a_debrief_but_stay_out_of_progress(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], squeue: ScoringQueue
) -> None:
    """A 10-minute mini gets its own debrief and advice, but no snapshots and no trend points."""
    target = await make_target(sessionmaker, gap=True)
    first = await make_session(sessionmaker, target, ended_minutes_ago=60)
    mini = await make_session(sessionmaker, target, ended_minutes_ago=30, duration_min=10)
    for sid, score in ((first, 3), (mini, 1)):
        squeue.replies = replies(scores=score)
        assert (await sclient.post(f"/sessions/{sid}/scoring")).status_code == 202

    debrief = (await sclient.get(f"/sessions/{mini}/debrief")).json()
    assert debrief["status"] == "ready"
    assert debrief["session"]["config"]["duration_min"] == 10
    assert debrief["scorecard"]["per_question"]
    # The advice uses the mini's own low scores, as it has no snapshots.
    assert "under the bar" in debrief["next_session"]["reason"]

    progress = (await sclient.get(f"/job-targets/{target}/progress")).json()
    assert {s["session_id"] for s in progress["snapshots"]} == {str(first)}
    assert all(t["sessions"] == 1 and t["latest"] == 3.0 for t in progress["trends"])
    # The mini does not count as practice of the planned behavioral session either.
    assert progress["next_session"]["interview_type"] in {"behavioral", "technical_qa"}


async def test_pr1_old_mini_snapshots_are_ignored(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], squeue: ScoringQueue
) -> None:
    """Snapshot rows of a mini (for example written before this rule) are not in the trends."""
    from strong_core.db.models import ProgressSnapshot as SnapshotRow

    target = await make_target(sessionmaker)
    mini = await make_session(sessionmaker, target, duration_min=10)
    org_id, _ = await dev_account(sessionmaker)
    async with sessionmaker() as db:
        db.add(
            SnapshotRow(
                org_id=org_id,
                job_target_id=target,
                session_id=mini,
                competency=Competency.OWNERSHIP,
                score=2,
                at=datetime.now(UTC),
            )
        )
        await db.commit()
    progress = (await sclient.get(f"/job-targets/{target}/progress")).json()
    assert progress["snapshots"] == [] and progress["trends"] == []


async def test_session_config_keeps_10_minutes_without_a_brief(
    sclient: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Before, any length other than 45 was shown as 30."""
    target = await make_target(sessionmaker)
    sid = await make_session(sessionmaker, target, duration_min=10)
    async with sessionmaker() as db:
        row = await db.get(InterviewSession, sid)
        assert row is not None
        row.brief_json = None
        await db.commit()
    debrief = (await sclient.get(f"/sessions/{sid}/debrief")).json()
    assert debrief["session"]["config"]["duration_min"] == 10


def _snap(c: Competency, score: float, day: int) -> ProgressSnapshot:
    return ProgressSnapshot(
        job_target_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        competency=c,
        score=score,
        at=datetime(2026, 10, day, tzinfo=UTC),
    )


def test_pr1_trends() -> None:
    trends = competency_trends(
        [
            _snap(C.OWNERSHIP, 2.0, 1),
            _snap(C.OWNERSHIP, 3.5, 3),
            _snap(C.IMPACT, 3.0, 1),
            _snap(C.IMPACT, 3.1, 3),
            _snap(C.COLLABORATION, 2.5, 3),
        ]
    )
    by = {t.competency: t for t in trends}
    assert by[C.OWNERSHIP].direction == "up" and by[C.OWNERSHIP].change == 1.5
    assert by[C.IMPACT].direction == "flat"
    assert by[C.COLLABORATION].direction == "single"
    assert trends[0].competency == C.COLLABORATION  # weakest latest score first


PLAN = [
    PlannedSession(
        priority=1,
        interview_type=InterviewType.BEHAVIORAL,
        focus_topics=["Leading without authority"],
        reason="Largest gap is scope at senior level",
    ),
    PlannedSession(
        priority=2,
        interview_type=InterviewType.TECHNICAL_QA,
        focus_topics=["Idempotency"],
        reason="Core to the role",
    ),
]


def test_pr2_first_session_follows_the_plan() -> None:
    nxt = recommend_next_session({}, PLAN, [])
    assert nxt is not None
    assert nxt.interview_type == InterviewType.BEHAVIORAL
    assert nxt.focus_topics == ["Leading without authority"]


def test_pr2_weakest_competencies_win_over_the_plan() -> None:
    scores = {C.TRADE_OFFS: 1.5, C.ACCURACY: 2.0, C.OWNERSHIP: 3.0}
    nxt = recommend_next_session(scores, PLAN, [InterviewType.BEHAVIORAL])
    assert nxt is not None
    assert nxt.interview_type == InterviewType.TECHNICAL_QA
    assert nxt.focus_topics[:2] == ["Trade offs", "Accuracy"]
    assert "trade offs (1.5)" in nxt.reason


def test_pr2_all_at_the_bar_moves_to_tough() -> None:
    scores = {C.OWNERSHIP: 3.0, C.IMPACT: 3.5, C.TECHNICAL_DEPTH: 3.8}
    done = [InterviewType.BEHAVIORAL, InterviewType.TECHNICAL_QA]
    nxt = recommend_next_session(scores, PLAN, done)
    assert nxt is not None
    assert nxt.difficulty == Difficulty.TOUGH
    assert nxt.interview_type == InterviewType.BEHAVIORAL


def test_pr2_nothing_to_go_on() -> None:
    assert recommend_next_session({}, [], []) is None
