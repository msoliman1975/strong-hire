"""PP-1, PP-2, PP-4: the interview plan page's API for one job and CV pair."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.profiles import repository as repo
from strong_api.profiles.validation import load_profile_file
from strong_core.config import get_settings
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.schemas import SessionStatus

from .conftest import sign_in
from .test_library_api import SESSION_CONFIG, add_job, add_resume, gap_for

Maker = async_sessionmaker[AsyncSession]


async def publish_stripe(sessionmaker: Maker) -> None:
    profile = load_profile_file(get_settings().repo_root / "profiles/stripe.json")
    async with sessionmaker() as db:
        result = await repo.import_profile(db, profile, actor="tester")
        await db.commit()
        await repo.publish_profile(db, "stripe", result.version, reviewer="tester")
        await db.commit()


async def test_pp1_plan_view_aggregates_gap_reports_and_next_session(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PP-1: one read gives the job, the pair's gap analysis (probe areas, session plan), its
    reports, the PR-2 next session and the setup defaults (PP-4)."""
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    other = await add_resume(client, fake_fixtures, filename="Other CV.txt")
    gap = await gap_for(client, job["id"], cv["id"])
    await gap_for(client, job["id"], other["id"])  # the job's latest run, but another CV

    created = await client.post(
        "/sessions",
        json={"job_target_id": job["id"], "resume_id": cv["id"], "config": {**SESSION_CONFIG, "duration_min": 10}},
    )
    assert created.status_code == 201, created.text
    async with sessionmaker() as db:
        row = await db.get(InterviewSession, uuid.UUID(created.json()["id"]))
        assert row is not None
        row.status = SessionStatus.COMPLETED
        row.started_at = datetime.now(UTC) - timedelta(minutes=30)
        row.ended_at = datetime.now(UTC)
        await db.commit()

    resp = await client.get(f"/plan/{job['id']}/{cv['id']}")
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["job"]["id"] == job["id"]
    assert plan["resume"]["id"] == cv["id"]
    assert plan["gap"]["id"] == gap["id"]  # this pair's run, not the other CV's
    analysis = plan["gap"]["analysis"]
    assert analysis["probe_areas"] and analysis["session_plan"]
    assert {(r["type"], r["resume_id"]) for r in plan["reports"]} == {
        ("gap_report", cv["id"]),
        ("interview_debrief", cv["id"]),
    }
    assert plan["company_mode"] == "generic"  # no profile is published in the test database
    assert plan["values_framework"] is None
    # Generic mode: the four standard types, equal weights, none marked as in the loop.
    assert [t["interview_type"] for t in plan["tested"]] == [
        "behavioral",
        "hiring_manager",
        "technical_qa",
        "case",
    ]
    assert not any(t["in_loop"] for t in plan["tested"])
    assert {c["weight"] for t in plan["tested"] for c in t["competencies"]} == {1.0}

    first = min(analysis["session_plan"], key=lambda p: p["priority"])
    setup = plan["setup"]
    expected = plan["next_session"] or first
    assert setup["interview_type"] == expected["interview_type"]
    assert setup["difficulty"] == expected["difficulty"]
    assert setup["mode"] == "coach"
    assert setup["duration_min"] == 30
    assert setup["level"] == "senior"
    assert setup["tone"] == "neutral"  # TN-3: generic mode


async def test_pp1_plan_view_without_a_gap_analysis(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """PP-1: a pair with no gap analysis yet still has a plan page, with no gap and no reports."""
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    plan = (await client.get(f"/plan/{job['id']}/{cv['id']}")).json()
    assert plan["gap"] is None
    assert plan["reports"] == []
    assert plan["next_session"] is None
    assert plan["setup"]["interview_type"] == "behavioral"


async def test_pp1_curated_profile_weights_and_loop(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PP-1: with a published profile, "what they'll test" uses its weights and loop order."""
    await publish_stripe(sessionmaker)
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    plan = (await client.get(f"/plan/{job['id']}/{cv['id']}")).json()
    assert plan["company_mode"] == "curated"
    assert plan["company_name"] == "Stripe"
    assert plan["setup"]["tone"] == "as_company"
    tested = plan["tested"]
    in_loop = [t["interview_type"] for t in tested if t["in_loop"]]
    assert in_loop, "the Stripe loop for this role family has rounds"
    assert [t["interview_type"] for t in tested[: len(in_loop)]] == in_loop
    for t in tested:
        weights = [c["weight"] for c in t["competencies"]]
        assert weights == sorted(weights, reverse=True)
        assert abs(sum(c["share"] for c in t["competencies"]) - 1) < 0.01


async def test_pp1_plan_is_owner_only(
    client: httpx.AsyncClient, fake_fixtures: Path, anon_client: httpx.AsyncClient
) -> None:
    """PP-1: another user's job or CV is 404; signed out is 401."""
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    url = f"/plan/{job['id']}/{cv['id']}"
    assert (await anon_client.get(url)).status_code == 401
    assert (await client.get(f"/plan/{uuid.uuid4()}/{cv['id']}")).status_code == 404
    assert (await client.get(f"/plan/{job['id']}/{uuid.uuid4()}")).status_code == 404
    await sign_in(client, "someone-else@example.com")
    assert (await client.get(url)).status_code == 404


async def test_pp2_days_left_and_setting_the_interview_date(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PP-2: no date asks for one (null days left); setting it shows the days left."""
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    url = f"/plan/{job['id']}/{cv['id']}"
    plan = (await client.get(url)).json()
    assert plan["interview_date"] is None and plan["days_left"] is None

    day = (datetime.now(UTC).date() + timedelta(days=9)).isoformat()
    put = await client.put(f"/plan/{job['id']}/interview-date", json={"interview_date": day})
    assert put.status_code == 200, put.text
    assert put.json() == {"interview_date": day, "days_left": 9}
    plan = (await client.get(url)).json()
    assert plan["interview_date"] == day and plan["days_left"] == 9
    async with sessionmaker() as db:
        row = await db.get(JobTarget, uuid.UUID(job["id"]))
        assert row is not None and row.interview_date is not None

    past = (datetime.now(UTC).date() - timedelta(days=5)).isoformat()
    bad = await client.put(f"/plan/{job['id']}/interview-date", json={"interview_date": past})
    assert bad.status_code == 422

    cleared = await client.put(f"/plan/{job['id']}/interview-date", json={"interview_date": None})
    assert cleared.json() == {"interview_date": None, "days_left": None}
    assert (await client.get(url)).json()["days_left"] is None
