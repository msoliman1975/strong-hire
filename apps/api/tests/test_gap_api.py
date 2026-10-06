"""Gap analysis endpoints (GA-1 to GA-4), job and resume lists, and recompute on change."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.gap.service import TIMED_OUT
from strong_api.gap.settings import GapSettings, get_gap_settings
from strong_api.inputs import queue as queue_names
from strong_core.config import get_settings
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import InterviewSession, JobTarget, Subscription, UsageEvent
from strong_core.db.models import Resume as ResumeRow
from strong_core.schemas import Difficulty, InterviewType, Mode
from strong_worker.gap import jobs as gap_jobs
from strong_worker.inputs.testing import set_extractor_output

from .conftest import sign_in

FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"


def fixture(kind: str, name: str) -> tuple[str, dict[str, Any]]:
    text = (FIXTURES / kind / f"{name}.txt").read_text(encoding="utf-8")
    return text, json.loads((FIXTURES / kind / f"{name}.json").read_text(encoding="utf-8"))


async def job_and_resume(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    posting_text, posting = fixture("postings", "swe-stripe-backend")
    resume_text, resume = fixture("resumes", "backend-senior")
    set_extractor_output(fake_fixtures, "JobPosting", posting)
    set_extractor_output(fake_fixtures, "Resume", resume)
    target = (await client.post("/job-targets", json={"text": posting_text})).json()["job_target"]
    resume_out = (await client.post("/resumes", data={"text": resume_text})).json()["resume"]
    resume_out = (await client.get(f"/resumes/{resume_out['id']}")).json()
    assert target["status"] == "extracted" and resume_out["status"] == "extracted"
    return target, resume_out


def limits(app: FastAPI, **values: int) -> None:
    app.dependency_overrides[get_gap_settings] = lambda: GapSettings(**values)


def test_queue_names_match_worker_functions() -> None:
    for name in (queue_names.RUN_GAP_ANALYSIS, queue_names.BUILD_INTERVIEWER_BRIEF):
        assert getattr(gap_jobs, name) in gap_jobs.FUNCTIONS


async def test_ga1_ga2_ga3_start_and_read(client: httpx.AsyncClient, fake_fixtures: Path) -> None:
    """GA-1 to GA-3: start with a resume, then read the score, breakdown, gaps and plan."""
    target, resume = await job_and_resume(client, fake_fixtures)
    url = f"/job-targets/{target['id']}/gap-analysis"
    assert (await client.get(url)).status_code == 404

    started = await client.post(url, json={"resume_id": resume["id"]})
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["status"] == "ready"
    assert body["resume_id"] == resume["id"] and body["stale"] is False
    assert body["generic_mode"] is True  # no profile is published in the test database
    analysis = body["analysis"]
    assert 0 <= analysis["match_score"] <= 100
    assert analysis["requirement_breakdown"] and analysis["competency_breakdown"]
    assert all(s["evidence"] for s in analysis["strengths"])
    assert all(g["severity"] in ("low", "medium", "high") for g in analysis["gaps"])
    assert analysis["probe_areas"]
    assert analysis["session_plan"][0]["priority"] == 1

    fetched = await client.get(url)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
    assert fetched.json()["analysis"] == analysis


async def test_generic_mode_flag_follows_the_profile(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Any
) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    body = (
        await client.post(
            f"/job-targets/{target['id']}/gap-analysis", json={"resume_id": resume["id"]}
        )
    ).json()
    # No profile is published for Stripe in this test database, so the analysis used generic
    # mode: no profile version.
    assert body["profile_version"] is None
    async with sessionmaker() as db:
        row = await db.get(GapRow, uuid.UUID(body["id"]))
        assert row.profile_version is None


async def test_start_errors(client: httpx.AsyncClient, fake_fixtures: Path, queue: Any) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    url = f"/job-targets/{target['id']}/gap-analysis"
    assert (await client.post(url, json={})).status_code == 422  # no resume, no earlier run
    assert (await client.post(url, json={"resume_id": str(uuid.uuid4())})).status_code == 404
    other = f"/job-targets/{uuid.uuid4()}/gap-analysis"
    assert (await client.post(other, json={"resume_id": resume["id"]})).status_code == 404
    assert (await client.post(url, json={"resume_id": resume["id"], "x": 1})).status_code == 422

    queue.run_jobs = False
    text, _ = fixture("postings", "swe-stripe-backend")
    pending = (await client.post("/job-targets", json={"text": text})).json()["job_target"]
    resp = await client.post(
        f"/job-targets/{pending['id']}/gap-analysis", json={"resume_id": resume["id"]}
    )
    assert resp.status_code == 409


async def test_run_again_without_a_resume_id(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    url = f"/job-targets/{target['id']}/gap-analysis"
    first = (await client.post(url, json={"resume_id": resume["id"]})).json()
    again = await client.post(url, json={})
    assert again.status_code == 202
    assert again.json()["id"] != first["id"] and again.json()["resume_id"] == resume["id"]


async def test_running_analysis_is_not_started_twice(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any
) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    queue.run_jobs = False
    url = f"/job-targets/{target['id']}/gap-analysis"
    first = (await client.post(url, json={"resume_id": resume["id"]})).json()
    second = (await client.post(url, json={"resume_id": resume["id"]})).json()
    assert first["status"] == "running" and first["analysis"] is None
    assert second["id"] == first["id"]
    assert [f for f, _, _ in queue.enqueued].count(queue_names.RUN_GAP_ANALYSIS) == 1


async def test_ga4_rate_limited_per_user(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """GA-4, BL-2: gap analyses are free but rate limited; over the limit the API says 429."""
    target, resume = await job_and_resume(client, fake_fixtures)
    limits(app, gap_rate_limit_per_hour=2, gap_rate_limit_per_day=5)
    url = f"/job-targets/{target['id']}/gap-analysis"
    for _ in range(2):
        assert (await client.post(url, json={"resume_id": resume["id"]})).status_code == 202
    limited = await client.post(url, json={"resume_id": resume["id"]})
    assert limited.status_code == 429
    detail = limited.json()["detail"]
    assert detail["code"] == "rate_limited" and detail["retry_after_s"] > 0
    assert int(limited.headers["Retry-After"]) == detail["retry_after_s"]
    # The latest ready analysis is still there.
    assert (await client.get(url)).json()["status"] == "ready"


async def test_ga4_limit_is_per_user(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    limits(app, gap_rate_limit_per_hour=1, gap_rate_limit_per_day=5)
    url = f"/job-targets/{target['id']}/gap-analysis"
    assert (await client.post(url, json={"resume_id": resume["id"]})).status_code == 202
    assert (await client.post(url, json={"resume_id": resume["id"]})).status_code == 429

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await sign_in(other, "other@example.com")
        target2, resume2 = await job_and_resume(other, fake_fixtures)
        resp = await other.post(
            f"/job-targets/{target2['id']}/gap-analysis", json={"resume_id": resume2["id"]}
        )
        assert resp.status_code == 202
        # Other users cannot see this user's analysis.
        assert (await other.get(url)).status_code == 404


async def test_ga4_free_and_no_minutes_used(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """GA-4: gap analysis works on the free plan and never touches plan minutes or usage."""
    target, resume = await job_and_resume(client, fake_fixtures)
    resp = await client.post(
        f"/job-targets/{target['id']}/gap-analysis", json={"resume_id": resume["id"]}
    )
    assert resp.json()["status"] == "ready"
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count(Subscription.id))) == 0
        assert await db.scalar(select(func.count(UsageEvent.id))) == 0


# --- recompute when the resume or the job changes --------------------------------------------


async def test_resume_edit_starts_a_new_analysis(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any
) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    url = f"/job-targets/{target['id']}/gap-analysis"
    first = (await client.post(url, json={"resume_id": resume["id"]})).json()

    # Saving the same resume changes nothing: no new run.
    await client.put(f"/resumes/{resume['id']}", json={"resume": resume["resume"]})
    assert (await client.get(url)).json()["id"] == first["id"]

    edited = resume["resume"] | {"skills": [*resume["resume"]["skills"], "Rust"]}
    assert (
        await client.put(f"/resumes/{resume['id']}", json={"resume": edited})
    ).status_code == 200
    latest = (await client.get(url)).json()
    assert latest["id"] != first["id"]
    assert latest["status"] == "ready" and latest["stale"] is False


async def test_job_edit_starts_a_new_analysis(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    url = f"/job-targets/{target['id']}/gap-analysis"
    first = (await client.post(url, json={"resume_id": resume["id"]})).json()
    posting = target["posting"] | {"must_have_skills": ["Go", "Kubernetes"]}
    resp = await client.put(
        f"/job-targets/{target['id']}", json={"posting": posting, "stage": "Phone screen"}
    )
    assert resp.status_code == 200
    latest = (await client.get(url)).json()
    assert latest["id"] != first["id"]
    reqs = [r["requirement"] for r in latest["analysis"]["requirement_breakdown"]]
    assert reqs[:2] == ["Go", "Kubernetes"]


async def test_edit_over_the_limit_marks_the_analysis_stale(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    target, resume = await job_and_resume(client, fake_fixtures)
    limits(app, gap_rate_limit_per_hour=1, gap_rate_limit_per_day=5)
    url = f"/job-targets/{target['id']}/gap-analysis"
    first = (await client.post(url, json={"resume_id": resume["id"]})).json()
    edited = resume["resume"] | {"summary": "Backend engineer, now also on call lead."}
    await client.put(f"/resumes/{resume['id']}", json={"resume": edited})
    latest = (await client.get(url)).json()
    assert latest["id"] == first["id"]
    assert latest["stale"] is True


async def test_stuck_run_shows_as_failed(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A run the worker never finished shows as failed after the timeout, and can restart."""
    target, resume = await job_and_resume(client, fake_fixtures)
    queue.run_jobs = False
    url = f"/job-targets/{target['id']}/gap-analysis"
    first = (await client.post(url, json={"resume_id": resume["id"]})).json()
    async with sessionmaker() as db:
        row = await db.get(GapRow, uuid.UUID(first["id"]))
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()
    body = (await client.get(url)).json()
    assert body["status"] == "failed" and body["error"] == TIMED_OUT
    restarted = (await client.post(url, json={"resume_id": resume["id"]})).json()
    assert restarted["id"] != first["id"] and restarted["status"] == "running"


# --- lists (dashboard and resume reuse) ------------------------------------------------------


async def test_list_job_targets_for_the_dashboard(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    assert (await client.get("/job-targets")).json() == []
    target, resume = await job_and_resume(client, fake_fixtures)
    listed = (await client.get("/job-targets")).json()
    assert len(listed) == 1
    assert listed[0]["job_target"]["id"] == target["id"]
    assert listed[0]["match_score"] is None and listed[0]["gap_status"] is None
    assert listed[0]["sessions_count"] == 0 and listed[0]["last_session_at"] is None

    gap = (
        await client.post(
            f"/job-targets/{target['id']}/gap-analysis", json={"resume_id": resume["id"]}
        )
    ).json()
    async with sessionmaker() as db:
        row = await db.get(JobTarget, uuid.UUID(target["id"]))
        assert row is not None
        db.add(
            InterviewSession(
                org_id=row.org_id,
                job_target_id=row.id,
                type=InterviewType.BEHAVIORAL,
                difficulty=Difficulty.REALISTIC,
                mode=Mode.REALISTIC,
                duration_min=30,
            )
        )
        await db.commit()
    listed = (await client.get("/job-targets")).json()
    assert listed[0]["match_score"] == gap["analysis"]["match_score"]
    assert listed[0]["gap_status"] == "ready"
    assert listed[0]["sessions_count"] == 1


async def test_list_resumes_newest_first_and_own_only(
    app: FastAPI,
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    _, first = await job_and_resume(client, fake_fixtures)
    text, _ = fixture("resumes", "new-grad-swe")
    second = (await client.post("/resumes", data={"text": text})).json()["resume"]
    async with sessionmaker() as db:  # SQLite keeps whole seconds; make the order clear
        row = await db.get(ResumeRow, uuid.UUID(first["id"]))
        assert row is not None
        row.uploaded_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
    listed = (await client.get("/resumes")).json()
    assert [r["id"] for r in listed] == [second["id"], first["id"]]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await sign_in(other, "other@example.com")
        assert (await other.get("/resumes")).json() == []
        assert (await other.get("/job-targets")).json() == []


@pytest.mark.parametrize("path", ["/job-targets", "/resumes"])
async def test_lists_need_sign_in(anon_client: httpx.AsyncClient, path: str) -> None:
    assert (await anon_client.get(path)).status_code == 401
