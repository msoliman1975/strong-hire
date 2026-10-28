"""RD-1, RD-2, RD-3: practice readiness per skill and the day plan of the interview plan page."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.plan import day_plan, readiness
from strong_api.plan.day_plan import build_day_plan, get_story_fit_reader, story_gaps
from strong_api.plan.readiness import (
    MIN_SESSIONS,
    SkillPoint,
    compute_readiness,
    counts_for_readiness,
    to_score,
)
from strong_core.db.models import InterviewSession, JobTarget, ProgressSnapshot, Story
from strong_core.schemas import (
    Competency,
    Difficulty,
    InterviewType,
    Mode,
    PlannedSession,
    ReadinessStatus,
    SessionStatus,
    StoryFit,
    StoryFitItem,
    StoryFitStrength,
)
from strong_worker.gap.story_fit import story_fit_key as worker_story_fit_key

from .test_library_api import add_job, add_resume, gap_for

Maker = async_sessionmaker[AsyncSession]
JOB = uuid.uuid4()
CV = uuid.uuid4()
TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def plan(itype: InterviewType, priority: int = 1, difficulty: Difficulty = Difficulty.REALISTIC):
    return PlannedSession(
        priority=priority,
        interview_type=itype,
        difficulty=difficulty,
        focus_topics=["Topic"],
        reason="Because.",
    )


# --- RD-1 rules --------------------------------------------------------------------------------


def test_rd1_only_realistic_full_real_profile_sessions_count() -> None:
    """RD-1: Coach mode, the mini interview and dev profiles (fake, tiny, local) never count."""
    assert counts_for_readiness(Mode.REALISTIC, 30, "hosted")
    assert counts_for_readiness(Mode.REALISTIC, 45, "claude")
    assert not counts_for_readiness(Mode.COACH, 30, "hosted")
    assert not counts_for_readiness(Mode.REALISTIC, 10, "hosted")  # mini
    for dev in ("fake", "tiny", "local"):
        assert not counts_for_readiness(Mode.REALISTIC, 30, dev)
    assert not counts_for_readiness(Mode.REALISTIC, 30, None)


def test_rd1_not_enough_data_below_the_minimum() -> None:
    """RD-1: fewer than MIN_SESSIONS sessions for a skill gives not_enough_data and no score."""
    c = Competency.OWNERSHIP
    points = [SkillPoint(c, 3.0, NOW - timedelta(days=i)) for i in range(MIN_SESSIONS - 1)]
    out = compute_readiness(JOB, [c, Competency.COMMUNICATION], points, TODAY)
    assert [s.competency for s in out.skills] == [c, Competency.COMMUNICATION]
    assert all(s.status == ReadinessStatus.NOT_ENOUGH_DATA and s.score is None for s in out.skills)
    assert out.skills[0].sessions_counted == MIN_SESSIONS - 1
    assert out.kind == "practice_estimate"  # RD-3


def test_rd1_recent_sessions_weigh_more() -> None:
    """RD-1: the newest session weighs more, so improving lands above the plain average."""
    c = Competency.OWNERSHIP
    rising = [SkillPoint(c, 2.0, NOW - timedelta(days=2)), SkillPoint(c, 4.0, NOW)]
    falling = [SkillPoint(c, 4.0, NOW - timedelta(days=2)), SkillPoint(c, 2.0, NOW)]
    up = compute_readiness(JOB, [c], rising, TODAY).skills[0]
    down = compute_readiness(JOB, [c], falling, TODAY).skills[0]
    assert up.status == ReadinessStatus.SCORED
    assert up.score is not None and down.score is not None
    assert up.score > to_score(3.0) > down.score
    assert to_score(1.0) == 0 and to_score(4.0) == 100


# --- RD-2 rules --------------------------------------------------------------------------------


def _build(interview_date: date | None, stories=(), practiced=frozenset()):
    return build_day_plan(
        job_target_id=JOB,
        resume_id=CV,
        today=TODAY,
        interview_date=interview_date,
        rehearsals=[plan(InterviewType.BEHAVIORAL), plan(InterviewType.TECHNICAL_QA, 2)],
        stories=list(stories),
        practiced=set(practiced),
    )


def _gap(c: Competency, strength=StoryFitStrength.MISSING) -> StoryFitItem:
    sid = None if strength == StoryFitStrength.MISSING else uuid.uuid4()
    return StoryFitItem(competency=c, story_id=sid, strength=strength, reason="Thin on results.")


def test_rd2_one_or_two_items_each_day_to_the_interview() -> None:
    """RD-2: one entry per day from today to the day before; a dress rehearsal last."""
    stories = [
        _gap(Competency.OWNERSHIP),
        _gap(Competency.CONFLICT_HANDLING, StoryFitStrength.THIN),
    ]
    out = _build(TODAY + timedelta(days=5), stories=stories)
    assert out.kind == "by_day" and out.next_steps == []
    assert [d.day for d in out.days] == [TODAY + timedelta(days=i) for i in range(5)]
    assert all(1 <= len(d.items) <= 2 for d in out.days)
    first = out.days[0].items
    assert first[0].kind == "rehearsal" and first[0].mode == Mode.COACH  # untried type
    assert first[1].kind == "story" and first[1].competency == Competency.OWNERSHIP
    kinds = [i.kind for d in out.days for i in d.items]
    assert kinds.count("story") == 2
    last = out.days[-1].items
    assert len(last) == 1 and last[0].mode == Mode.REALISTIC
    assert last[0].interview_type == InterviewType.BEHAVIORAL
    # A type shows in Coach mode once; the next time it is Realistic.
    behavioral = [
        i.mode for d in out.days for i in d.items if i.interview_type == InterviewType.BEHAVIORAL
    ]
    assert behavioral[0] == Mode.COACH and set(behavioral[1:]) == {Mode.REALISTIC}


def test_rd2_practiced_types_start_in_realistic_mode() -> None:
    out = _build(TODAY + timedelta(days=3), practiced={InterviewType.BEHAVIORAL})
    assert out.days[0].items[0].mode == Mode.REALISTIC


def test_rd2_interview_today_and_far_away() -> None:
    """RD-2: today is one warm-up; a far date lists MAX_DAYS days and counts the rest."""
    today = _build(TODAY)
    assert len(today.days) == 1 and today.days[0].items[0].difficulty == Difficulty.FRIENDLY
    far = _build(TODAY + timedelta(days=day_plan.MAX_DAYS + 12))
    assert len(far.days) == day_plan.MAX_DAYS
    assert far.days_not_shown == 12


def test_rd2_without_a_date_shows_the_next_three_steps() -> None:
    """RD-2: no date (or a past one): the next three steps, a rehearsal and a story in turn."""
    for when in (None, TODAY - timedelta(days=2)):
        out = _build(when, stories=[_gap(Competency.OWNERSHIP)])
        assert out.kind == "next_steps" and out.days == []
        assert [i.kind for i in out.next_steps] == ["rehearsal", "story", "rehearsal"]


def test_rd2_story_gaps_missing_first_and_deleted_story_is_missing() -> None:
    thin = _gap(Competency.CONFLICT_HANDLING, StoryFitStrength.THIN)
    strong = StoryFitItem(
        competency=Competency.OWNERSHIP,
        story_id=uuid.uuid4(),
        strength=StoryFitStrength.STRONG,
        reason="Good.",
    )
    missing = _gap(Competency.COMMUNICATION)
    fit = StoryFit(items=[thin, strong, missing])
    assert [i.competency for i in story_gaps(fit, {thin.story_id, strong.story_id})] == [
        Competency.COMMUNICATION,
        Competency.CONFLICT_HANDLING,
    ]
    gone = story_gaps(fit, {strong.story_id})  # the thin story was deleted
    assert all(i.strength == StoryFitStrength.MISSING for i in gone)
    assert story_gaps(None, set()) == []


def test_rd2_story_fit_key_matches_the_worker() -> None:
    org, job = uuid.uuid4(), uuid.uuid4()
    assert day_plan.story_fit_key(org, job) == worker_story_fit_key(org, job)


# --- API ---------------------------------------------------------------------------------------


async def _session(
    sessionmaker: Maker,
    job_id: str,
    cv_id: str,
    *,
    mode: Mode = Mode.REALISTIC,
    profile: str | None = "hosted",
    duration: int = 30,
    scores: dict[Competency, float],
    ago_days: int = 0,
) -> None:
    async with sessionmaker() as db:
        job = await db.get(JobTarget, uuid.UUID(job_id))
        assert job is not None
        at = datetime.now(UTC) - timedelta(days=ago_days)
        row = InterviewSession(
            org_id=job.org_id,
            job_target_id=job.id,
            resume_id=uuid.UUID(cv_id),
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.REALISTIC,
            mode=mode,
            duration_min=duration,
            model_profile=profile,
            status=SessionStatus.COMPLETED,
            started_at=at,
            ended_at=at,
            created_at=at,
        )
        db.add(row)
        await db.flush()
        for c, s in scores.items():
            db.add(
                ProgressSnapshot(
                    org_id=row.org_id,
                    job_target_id=row.job_target_id,
                    session_id=row.id,
                    competency=c,
                    score=Decimal(str(s)),
                    at=at,
                )
            )
        await db.commit()


async def test_rd1_api_counts_only_the_pairs_realistic_real_sessions(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RD-1: per tested skill, from this pair's Realistic sessions on a real profile only."""
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    other = await add_resume(client, fake_fixtures, filename="Other CV.txt")
    c = Competency.OWNERSHIP
    j, r = job["id"], cv["id"]
    await _session(sessionmaker, j, r, scores={c: 3.0}, ago_days=3)
    await _session(sessionmaker, j, r, scores={c: 3.5}, ago_days=1)
    await _session(sessionmaker, j, r, mode=Mode.COACH, scores={c: 1.0}, ago_days=2)
    await _session(sessionmaker, j, r, profile="fake", scores={c: 1.0}, ago_days=2)
    await _session(sessionmaker, j, r, duration=10, scores={c: 1.0}, ago_days=2)
    await _session(sessionmaker, j, other["id"], scores={c: 1.0})

    resp = await client.get(f"/plan/{j}/{r}/readiness")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "practice_estimate"  # RD-3
    skills = {s["competency"]: s for s in body["skills"]}
    assert skills["ownership"]["sessions_counted"] == 2
    assert skills["ownership"]["status"] == "scored"
    assert skills["ownership"]["score"] > to_score(3.0)
    assert skills["communication"]["status"] == "not_enough_data"

    # The Home badge reads the pair of the job's newest session (the other CV here).
    home = (await client.get(f"/readiness/{j}")).json()
    assert {s["competency"]: s["sessions_counted"] for s in home["skills"]}["ownership"] == 1
    assert (await client.get(f"/readiness/{uuid.uuid4()}")).status_code == 404


async def test_rd2_api_day_plan_with_and_without_a_date(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RD-2: the plan uses GA-3 and the story fit gaps; without a date it lists three steps."""
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    await gap_for(client, job["id"], cv["id"])

    async def fit(_org: uuid.UUID, _job: uuid.UUID) -> StoryFit:
        return StoryFit(items=[_gap(Competency.OWNERSHIP)])

    app.dependency_overrides[get_story_fit_reader] = lambda: fit
    url = f"/plan/{job['id']}/{cv['id']}/day-plan"
    try:
        steps = (await client.get(url)).json()
        assert steps["kind"] == "next_steps"
        assert [i["kind"] for i in steps["next_steps"]] == ["rehearsal", "story", "rehearsal"]

        when = (date.today() + timedelta(days=4)).isoformat()
        put = await client.put(f"/plan/{job['id']}/interview-date", json={"interview_date": when})
        assert put.status_code == 200, put.text
        dated = (await client.get(url)).json()
        assert dated["kind"] == "by_day"
        assert 3 <= len(dated["days"]) <= 5  # UTC today may differ from the local date
        assert any(i["kind"] == "story" for d in dated["days"] for i in d["items"])
    finally:
        app.dependency_overrides.pop(get_story_fit_reader, None)


async def test_rd2_deleted_story_reads_as_missing(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    thin = _gap(Competency.CONFLICT_HANDLING, StoryFitStrength.THIN)

    async def fit(_org: uuid.UUID, _job: uuid.UUID) -> StoryFit:
        return StoryFit(items=[thin])

    app.dependency_overrides[get_story_fit_reader] = lambda: fit
    try:
        out = (await client.get(f"/plan/{job['id']}/{cv['id']}/day-plan")).json()
    finally:
        app.dependency_overrides.pop(get_story_fit_reader, None)
    story = next(i for i in out["next_steps"] if i["kind"] == "story")
    assert story["strength"] == "missing" and story["story_id"] is None
    async with sessionmaker() as db:
        assert await db.get(Story, thin.story_id) is None


async def test_rd_endpoints_are_owner_only(
    client: httpx.AsyncClient, fake_fixtures: Path, anon_client: httpx.AsyncClient
) -> None:
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    for path in ("readiness", "day-plan"):
        assert (await anon_client.get(f"/plan/{job['id']}/{cv['id']}/{path}")).status_code == 401
        missing = await client.get(f"/plan/{uuid.uuid4()}/{cv['id']}/{path}")
        assert missing.status_code == 404


def test_modules_document_their_formula() -> None:
    assert readiness.__doc__ and "weighted mean" in readiness.__doc__
    assert day_plan.__doc__ and "dress rehearsal" in day_plan.__doc__
