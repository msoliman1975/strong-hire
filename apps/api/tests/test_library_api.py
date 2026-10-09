"""R1: the library of saved job descriptions and CVs, soft delete, and the Reports page."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.inputs import queue as queue_names
from strong_core.config import get_settings
from strong_core.db.models import AuditLog, InterviewSession, JobTarget
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.schemas import (
    Difficulty,
    HireSignal,
    InterviewType,
    Mode,
    SessionStatus,
)
from strong_worker.gap import jobs as gap_jobs
from strong_worker.inputs import jobs
from strong_worker.inputs.jobs import CTX_KEY
from strong_worker.inputs.testing import set_extractor_output

from .conftest import sign_in

Maker = async_sessionmaker[AsyncSession]
FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"
TODAY = datetime.now(UTC).date().isoformat()
SCORECARD = (
    get_settings().repo_root
    / "packages/core/src/strong_core/gateway/fixtures/scorer/Scorecard.json"
)


def fixture(kind: str, name: str) -> tuple[str, dict[str, Any]]:
    text = (FIXTURES / kind / f"{name}.txt").read_text(encoding="utf-8")
    return text, json.loads((FIXTURES / kind / f"{name}.json").read_text(encoding="utf-8"))


async def add_job(client: httpx.AsyncClient, fake_fixtures: Path, **body: Any) -> dict[str, Any]:
    text, posting = fixture("postings", "swe-stripe-backend")
    set_extractor_output(fake_fixtures, "JobPosting", posting)
    resp = await client.post("/job-targets", json={"text": text, **body})
    assert resp.status_code == 202, resp.text
    target: dict[str, Any] = resp.json()["job_target"]
    return target


async def add_resume(
    client: httpx.AsyncClient, fake_fixtures: Path, filename: str = "Ana Lopez CV.txt"
) -> dict[str, Any]:
    text, resume = fixture("resumes", "backend-senior")
    set_extractor_output(fake_fixtures, "Resume", resume)
    resp = await client.post("/resumes", files={"file": (filename, text.encode("utf-8"))})
    assert resp.status_code == 202, resp.text
    out: dict[str, Any] = (await client.get(f"/resumes/{resp.json()['resume']['id']}")).json()
    return out


async def gap_for(client: httpx.AsyncClient, job_id: str, resume_id: str, **extra: Any) -> Any:
    resp = await client.post(
        f"/job-targets/{job_id}/gap-analysis", json={"resume_id": resume_id, **extra}
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


@asynccontextmanager
async def other_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A second user, signed in."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, "other@example.com")
        yield http


def test_queue_name_matches_the_worker_function() -> None:
    assert getattr(jobs, queue_names.DELETE_RESUME_FILE) in jobs.FUNCTIONS


# --- names ----------------------------------------------------------------------------------


async def test_r1_default_names(client: httpx.AsyncClient, fake_fixtures: Path, queue: Any) -> None:
    job = await add_job(client, fake_fixtures)
    assert job["name"] == "Backend Engineer, Payments Infrastructure at Stripe"
    assert job["deleted"] is False
    cv = await add_resume(client, fake_fixtures, "Ana Lopez CV.pdf.txt")
    assert cv["name"] == "Ana Lopez CV.pdf"
    text, _ = fixture("resumes", "new-grad-swe")
    pasted = (await client.post("/resumes", data={"text": text})).json()["resume"]
    assert pasted["name"] == f"CV {TODAY}"

    queue.run_jobs = False  # not read yet: the link's host, else a dated name
    by_url = await client.post("/job-targets", json={"url": "https://www.boards.example/jobs/1"})
    assert by_url.json()["job_target"]["name"] == "boards.example"
    by_text = await client.post("/job-targets", json={"text": "A job. " * 30})
    assert by_text.json()["job_target"]["name"] == f"Job description {TODAY}"


async def test_r1_rename(app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path) -> None:
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    resp = await client.patch(f"/job-targets/{job['id']}", json={"name": "  Stripe   backend  "})
    assert resp.status_code == 200 and resp.json()["name"] == "Stripe backend"
    resp = await client.patch(f"/resumes/{cv['id']}", json={"name": "My CV 2026"})
    assert resp.status_code == 200 and resp.json()["name"] == "My CV 2026"
    assert (await client.get("/job-targets")).json()[0]["job_target"]["name"] == "Stripe backend"
    assert (await client.get("/resumes")).json()[0]["name"] == "My CV 2026"

    for bad in ("", "   ", "x" * 121):
        assert (await client.patch(f"/resumes/{cv['id']}", json={"name": bad})).status_code == 422
    assert (await client.patch(f"/resumes/{cv['id']}", json={"name": "x" * 120})).status_code == 200

    async with other_client(app) as other:
        assert (
            await other.patch(f"/job-targets/{job['id']}", json={"name": "x"})
        ).status_code == 404
        assert (await other.patch(f"/resumes/{cv['id']}", json={"name": "x"})).status_code == 404
        assert (await other.delete(f"/job-targets/{job['id']}")).status_code == 404
        assert (await other.delete(f"/resumes/{cv['id']}")).status_code == 404
        assert (await other.get(f"/job-targets/{job['id']}")).status_code == 404

    assert (await client.delete(f"/job-targets/{job['id']}")).status_code == 204
    assert (await client.patch(f"/job-targets/{job['id']}", json={"name": "x"})).status_code == 404


async def test_r1_lists_are_the_users_own(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """GET /job-targets and GET /resumes filter by the signed-in user."""
    await add_job(client, fake_fixtures)
    await add_resume(client, fake_fixtures)
    async with other_client(app) as other:
        assert (await other.get("/job-targets")).json() == []
        assert (await other.get("/resumes")).json() == []
        assert (await other.get("/reports")).json() == []


# --- match ----------------------------------------------------------------------------------


async def test_r1_pasted_job_matches_a_saved_one(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    text, _ = fixture("postings", "swe-stripe-backend")
    assert (await client.post("/job-targets/match", json={"text": text})).json() == {
        "job_target": None
    }
    job = await add_job(client, fake_fixtures, url="https://jobs.example.com/stripe/42/")

    messy = "\n\n  " + text.upper().replace(" ", "   ") + "  "
    found = (await client.post("/job-targets/match", json={"text": messy})).json()
    assert found["job_target"]["id"] == job["id"]
    assert found["job_target"]["name"] == job["name"]
    by_url = await client.post(
        "/job-targets/match", json={"url": "HTTPS://www.jobs.example.com/stripe/42#apply"}
    )
    assert by_url.json()["job_target"]["id"] == job["id"]
    other_text = await client.post("/job-targets/match", json={"text": "Another job. " * 20})
    assert other_text.json()["job_target"] is None

    async with other_client(app) as other:
        assert (await other.post("/job-targets/match", json={"text": text})).json() == {
            "job_target": None
        }

    await client.delete(f"/job-targets/{job['id']}")
    assert (await client.post("/job-targets/match", json={"text": text})).json() == {
        "job_target": None
    }


async def test_r1_sim_flow_pasted_job_is_still_created(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """POST /job-targets with no library choice still creates a new job target (the P13 sim
    client). A saved match does not block it or change the 202 response."""
    first = await add_job(client, fake_fixtures, stage="sim:swe-stripe-backend")
    text, _ = fixture("postings", "swe-stripe-backend")
    resp = await client.post("/job-targets", json={"text": text, "stage": "sim:swe-stripe-backend"})
    assert resp.status_code == 202
    body = resp.json()
    assert set(body) == {"job_target", "job"}
    assert body["job_target"]["id"] != first["id"]
    assert body["job_target"]["stage"] == "sim:swe-stripe-backend"
    assert body["job"]["result"]["outcome"] == "extracted"
    listed = (await client.get("/job-targets")).json()
    assert len(listed) == 2
    assert {"job_target", "match_score", "gap_status", "sessions_count", "last_session_at"} <= set(
        listed[0]
    )
    assert listed[0]["job_target"]["stage"] == "sim:swe-stripe-backend"
    pasted = await client.post("/resumes", data={"text": "Engineer. " * 20})
    assert pasted.status_code == 202


async def test_r1_cv_with_the_same_content_matches(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    text, _ = fixture("resumes", "backend-senior")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert (await client.post("/resumes/match", json={"sha256": digest})).json() == {"resume": None}
    cv = await add_resume(client, fake_fixtures)
    found = (await client.post("/resumes/match", json={"sha256": digest})).json()
    assert found["resume"]["id"] == cv["id"]
    assert found["resume"]["name"] == "Ana Lopez CV"
    # Pasted text matches by the hash of its UTF-8 bytes.
    pasted_text = ("Pasted CV. " * 20).strip()
    pasted = (await client.post("/resumes", data={"text": pasted_text})).json()["resume"]
    pasted_digest = hashlib.sha256(pasted_text.encode("utf-8")).hexdigest()
    found = (await client.post("/resumes/match", json={"sha256": pasted_digest})).json()
    assert found["resume"]["id"] == pasted["id"]
    assert (await client.post("/resumes/match", json={"sha256": "x"})).status_code == 422

    async with other_client(app) as other:
        assert (await other.post("/resumes/match", json={"sha256": digest})).json() == {
            "resume": None
        }
    await client.delete(f"/resumes/{cv['id']}")
    assert (await client.post("/resumes/match", json={"sha256": digest})).json() == {"resume": None}


async def test_r1_picking_a_saved_job_and_cv_again_reuses_the_report(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any
) -> None:
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    first = await gap_for(client, job["id"], cv["id"])
    again = await gap_for(client, job["id"], cv["id"], reuse_ready=True)
    assert again["id"] == first["id"] and again["status"] == "ready"
    runs = [f for f, _, _ in queue.enqueued].count(queue_names.RUN_GAP_ANALYSIS)
    assert runs == 1
    # Without reuse_ready a new run starts, as before (run the analysis again).
    fresh = await gap_for(client, job["id"], cv["id"])
    assert fresh["id"] != first["id"]
    # A different CV is a new analysis even with reuse_ready.
    other_cv = await add_resume(client, fake_fixtures, "second.txt")
    third = await gap_for(client, job["id"], other_cv["id"], reuse_ready=True)
    assert third["id"] != fresh["id"]


# --- delete ---------------------------------------------------------------------------------


async def _add_debrief(maker: Maker, job_id: str, *, ago_min: int = 0) -> uuid.UUID:
    async with maker() as db:
        target = await db.get(JobTarget, uuid.UUID(job_id))
        assert target is not None
        end = datetime.now(UTC) - timedelta(minutes=ago_min)
        session = InterviewSession(
            org_id=target.org_id,
            job_target_id=target.id,
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.REALISTIC,
            mode=Mode.REALISTIC,
            duration_min=30,
            status=SessionStatus.COMPLETED,
            started_at=end - timedelta(minutes=30),
            ended_at=end,
        )
        db.add(session)
        await db.flush()
        card = json.loads(SCORECARD.read_text(encoding="utf-8"))
        db.add(
            ScorecardRow(
                org_id=target.org_id,
                session_id=session.id,
                hire_signal=HireSignal.HIRE,
                rationale=card["rationale"],
                competency_scores_json=card["competency_scores"],
                value_scores_json=card["value_scores"],
                per_question_json=card["per_question"],
                scorer_model=card["scorer_model"],
                rubric_version=card["rubric_version"],
            )
        )
        await db.commit()
        return session.id


SESSION_CONFIG = {
    "interview_type": "behavioral",
    "difficulty": "realistic",
    "mode": "realistic",
    "duration_min": 30,
    "level": "senior",
}


async def test_lb2_delete_unused_job_clears_its_content(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """LB-2, R1: a job description with no gap report and no session can be deleted."""
    job = await add_job(client, fake_fixtures, url="https://jobs.example.com/1")
    listed = (await client.get("/job-targets")).json()
    assert [(r["job_target"]["id"], r["in_use"]) for r in listed] == [(job["id"], False)]

    assert (await client.delete(f"/job-targets/{job['id']}")).status_code == 204
    assert (await client.delete(f"/job-targets/{job['id']}")).status_code == 204  # twice is fine

    async with sessionmaker() as db:
        row = await db.get(JobTarget, uuid.UUID(job["id"]))
        assert row is not None and row.deleted_at is not None
        assert row.raw_text is None and row.parsed_json is None and row.source_url is None
        assert row.text_hash is None and row.name is None and row.context_notes is None
        logs = await db.scalars(select(AuditLog).where(AuditLog.action == "library.job_deleted"))
        assert [log.entity for log in logs] == [f"job_target:{job['id']}"]

    assert (await client.get("/job-targets")).json() == []
    shown = (await client.get(f"/job-targets/{job['id']}")).json()
    assert shown["deleted"] is True and shown["name"] is None and shown["posting"] is None

    # A deleted job cannot be picked again.
    cv = await add_resume(client, fake_fixtures)
    url = f"/job-targets/{job['id']}/gap-analysis"
    assert (await client.post(url, json={"resume_id": cv["id"]})).status_code == 404
    _, posting = fixture("postings", "swe-stripe-backend")
    edit = await client.put(f"/job-targets/{job['id']}", json={"posting": posting})
    assert edit.status_code == 404
    body = {"job_target_id": job["id"], "config": SESSION_CONFIG}
    assert (await client.post("/sessions", json=body)).status_code == 404
    assert (await client.post(f"/job-targets/{job['id']}/archive")).status_code == 404


async def test_lb2_job_with_reports_is_archived_not_deleted(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """LB-2: a job description with reports answers 409 to delete; archive and restore work."""
    job = await add_job(client, fake_fixtures, url="https://jobs.example.com/1")
    cv = await add_resume(client, fake_fixtures)
    await gap_for(client, job["id"], cv["id"])
    await _add_debrief(sessionmaker, job["id"])

    refused = await client.delete(f"/job-targets/{job['id']}")
    assert refused.status_code == 409 and "Archive it" in refused.json()["detail"]
    [summary] = (await client.get("/job-targets")).json()
    assert summary["in_use"] is True and summary["job_target"]["archived_at"] is None

    archived = await client.post(f"/job-targets/{job['id']}/archive")
    assert archived.status_code == 200 and archived.json()["archived_at"] is not None
    again = await client.post(f"/job-targets/{job['id']}/archive")  # twice is fine
    assert again.json()["archived_at"] == archived.json()["archived_at"]
    assert (await client.get("/job-targets")).json() == []
    with_archived = (await client.get("/job-targets", params={"include_archived": True})).json()
    assert [r["job_target"]["id"] for r in with_archived] == [job["id"]]
    reports = (await client.get("/reports", params={"job_target_id": job["id"]})).json()
    assert {r["type"] for r in reports} == {"gap_report", "interview_debrief"}

    restored = await client.post(f"/job-targets/{job['id']}/restore")
    assert restored.status_code == 200 and restored.json()["archived_at"] is None
    assert [r["job_target"]["id"] for r in (await client.get("/job-targets")).json()] == [job["id"]]

    async with sessionmaker() as db:
        actions = [
            log.action
            for log in await db.scalars(
                select(AuditLog)
                .where(AuditLog.action.like("library.job_%"))
                .order_by(AuditLog.at, AuditLog.id)
            )
        ]
    assert sorted(actions) == ["library.job_archived", "library.job_restored"]


async def test_r1_reports_of_a_deleted_job_stay(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """R1: a job deleted before LB-2 keeps its gap report, debrief and progress."""
    job = await add_job(client, fake_fixtures, url="https://jobs.example.com/1")
    cv = await add_resume(client, fake_fixtures)
    gap = await gap_for(client, job["id"], cv["id"])
    session_id = await _add_debrief(sessionmaker, job["id"])
    async with sessionmaker() as db:  # the R1 soft delete, as it ran before LB-2
        row = await db.get(JobTarget, uuid.UUID(job["id"]))
        assert row is not None
        row.deleted_at = datetime.now(UTC)
        row.name = row.raw_text = row.parsed_json = row.source_url = None
        row.context_notes = row.text_hash = None
        await db.commit()

    assert (await client.get("/job-targets")).json() == []
    report = (await client.get(f"/gap-analyses/{gap['id']}")).json()
    assert report["job_deleted"] is True and report["stale"] is False
    assert report["analysis"]["match_score"] == gap["analysis"]["match_score"]
    debrief = await client.get(f"/sessions/{session_id}/debrief")
    assert debrief.status_code == 200 and debrief.json()["status"] == "ready"
    assert (await client.get(f"/job-targets/{job['id']}/progress")).status_code == 200

    reports = (await client.get("/reports")).json()
    assert {(r["type"], r["job_deleted"], r["job_name"]) for r in reports} == {
        ("gap_report", True, None),
        ("interview_debrief", True, None),
    }


async def test_r1_delete_cv_removes_its_file_and_keeps_reports(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker, ctx: dict[str, Any]
) -> None:
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    gap = await gap_for(client, job["id"], cv["id"])
    async with sessionmaker() as db:
        row = await db.get(ResumeRow, uuid.UUID(cv["id"]))
        assert row is not None and row.file_ref is not None
        ref = row.file_ref
    store = ctx[CTX_KEY].store
    assert await store.get(ref)

    assert (await client.delete(f"/resumes/{cv['id']}")).status_code == 204
    with pytest.raises(OSError):
        await store.get(ref)
    async with sessionmaker() as db:
        row = await db.get(ResumeRow, uuid.UUID(cv["id"]))
        assert row is not None and row.deleted_at is not None
        assert row.parsed_json is None and row.file_ref is None and row.content_hash is None
        assert await db.get(GapRow, uuid.UUID(gap["id"])) is not None

    assert (await client.get("/resumes")).json() == []
    assert (await client.get(f"/resumes/{cv['id']}")).json()["deleted"] is True
    latest = (await client.get(f"/job-targets/{job['id']}/gap-analysis")).json()
    assert latest["resume_deleted"] is True and latest["resume_name"] is None
    assert latest["stale"] is False and latest["status"] == "ready"
    url = f"/job-targets/{job['id']}/gap-analysis"
    assert (await client.post(url, json={"resume_id": cv["id"]})).status_code == 404
    assert (await client.post(url, json={})).status_code == 404  # "run again" used that CV
    resume_body = {"resume": {"summary": "x"}}
    assert (await client.put(f"/resumes/{cv['id']}", json=resume_body)).status_code == 404
    [report] = (await client.get("/reports")).json()
    assert report["resume_deleted"] is True and report["job_deleted"] is False
    assert report["job_name"] == job["name"]


async def test_r1_resume_deleted_while_it_is_read_keeps_no_file(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any, ctx: dict[str, Any]
) -> None:
    queue.run_jobs = False
    resp = await client.post("/resumes", files={"file": ("cv.txt", b"Engineer at Acme. " * 10)})
    resume_id = resp.json()["resume"]["id"]
    assert (await client.delete(f"/resumes/{resume_id}")).status_code == 204
    [(function, _, kwargs)] = queue.enqueued  # no file yet, so no file delete job
    assert function == "parse_resume"
    result = await jobs.parse_resume(ctx, **kwargs)
    assert result == {"outcome": "failed", "reason": "resume not found"}
    root = Path(ctx[CTX_KEY].store.root)
    assert await asyncio.to_thread(lambda: list(root.rglob("*.enc"))) == []


async def test_r1_delete_file_job_retries_on_storage_errors(ctx: dict[str, Any]) -> None:
    from arq import Retry

    class BrokenStore:
        async def delete(self, ref: str) -> None:
            raise OSError("disk is busy")

    inputs = ctx[CTX_KEY]
    broken = {CTX_KEY: type(inputs)(inputs.sessionmaker, inputs.gateway, BrokenStore(), None)}  # type: ignore[arg-type]
    with pytest.raises(Retry):
        await jobs.delete_resume_file({**broken, "job_try": 1}, "o", "r", "local:x/y")
    with pytest.raises(OSError):
        await jobs.delete_resume_file(
            {**broken, "job_try": jobs.DELETE_FILE_MAX_TRIES}, "o", "r", "local:x/y"
        )


# --- reports --------------------------------------------------------------------------------


async def test_r1_reports_newest_first_with_filters(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    assert (await client.get("/reports")).json() == []
    job = await add_job(client, fake_fixtures)
    second_job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    gap = await gap_for(client, job["id"], cv["id"])
    async with sessionmaker() as db:  # SQLite keeps whole seconds; make the order clear
        row = await db.get(GapRow, uuid.UUID(gap["id"]))
        assert row is not None
        row.created_at = row.updated_at = datetime.now(UTC) - timedelta(hours=2)
        await db.commit()
    old_debrief = await _add_debrief(sessionmaker, job["id"], ago_min=60)
    new_debrief = await _add_debrief(sessionmaker, second_job["id"], ago_min=1)
    async with sessionmaker() as db:  # never started: no debrief
        target = await db.get(JobTarget, uuid.UUID(job["id"]))
        assert target is not None
        db.add(
            InterviewSession(
                org_id=target.org_id,
                job_target_id=target.id,
                type=InterviewType.BEHAVIORAL,
                difficulty=Difficulty.REALISTIC,
                mode=Mode.REALISTIC,
                duration_min=30,
                status=SessionStatus.FAILED,
            )
        )
        await db.commit()

    reports = (await client.get("/reports")).json()
    assert [r["id"] for r in reports] == [str(new_debrief), str(old_debrief), gap["id"]]
    assert reports[0]["type"] == "interview_debrief" and reports[0]["hire_signal"] == "Hire"
    assert reports[0]["status"] == "ready" and reports[0]["interview_type"] == "behavioral"
    assert reports[2]["type"] == "gap_report"
    assert reports[2]["match_score"] == gap["analysis"]["match_score"]
    assert reports[2]["resume_name"] == "Ana Lopez CV"

    by_job = (await client.get("/reports", params={"job_target_id": job["id"]})).json()
    assert [r["id"] for r in by_job] == [str(old_debrief), gap["id"]]
    gaps_only = (await client.get("/reports", params={"type": "gap_report"})).json()
    assert [r["id"] for r in gaps_only] == [gap["id"]]
    debriefs = (await client.get("/reports", params={"type": "interview_debrief"})).json()
    assert len(debriefs) == 2
    assert (await client.get("/reports", params={"type": "other"})).status_code == 422

    async with other_client(app) as other:
        assert (await other.get("/reports", params={"job_target_id": job["id"]})).json() == []
        assert (await other.get(f"/gap-analyses/{gap['id']}")).status_code == 404
    assert (await client.get(f"/gap-analyses/{uuid.uuid4()}")).status_code == 404


async def test_r1_routes_need_sign_in(anon_client: httpx.AsyncClient) -> None:
    some = uuid.uuid4()
    assert (await anon_client.get("/reports")).status_code == 401
    assert (await anon_client.post("/job-targets/match", json={"text": "x"})).status_code == 401
    assert (await anon_client.post("/resumes/match", json={"sha256": "0" * 64})).status_code == 401
    assert (await anon_client.delete(f"/resumes/{some}")).status_code == 401
    assert (await anon_client.patch(f"/job-targets/{some}", json={"name": "x"})).status_code == 401


# --- rehearsals: one job and CV pair (PR-3) -------------------------------------------------


async def test_pr3_a_session_records_its_cv_and_reports_filter_by_cv(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PR-3: a session keeps the CV it was created with; GET /reports can filter by that CV."""
    job = await add_job(client, fake_fixtures)
    first = await add_resume(client, fake_fixtures, filename="First CV.txt")
    second = await add_resume(client, fake_fixtures, filename="Second CV.txt")
    unused = await add_resume(client, fake_fixtures, filename="Unused CV.txt")
    gap_first = await gap_for(client, job["id"], first["id"])
    await gap_for(client, job["id"], second["id"])
    mini = {**SESSION_CONFIG, "duration_min": 10}

    def body(resume_id: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"job_target_id": job["id"], "config": mini}
        if resume_id is not None:
            out["resume_id"] = resume_id
        return out

    chosen = await client.post("/sessions", json=body(first["id"]))
    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["resume_id"] == first["id"]
    default = await client.post("/sessions", json=body())
    assert default.json()["resume_id"] == second["id"]  # the job's latest ready gap analysis
    no_gap = await client.post("/sessions", json=body(unused["id"]))
    assert no_gap.status_code == 409

    # The worker builds the brief from the chosen CV's gap analysis.
    async with sessionmaker() as db:
        picked = await gap_jobs.latest_ready_gap(db, uuid.UUID(job["id"]), uuid.UUID(first["id"]))
        assert picked is not None and str(picked.id) == gap_first["id"]

    async with sessionmaker() as db:  # end the first session so it has a debrief
        row = await db.get(InterviewSession, uuid.UUID(chosen.json()["id"]))
        assert row is not None
        row.status = SessionStatus.COMPLETED
        row.started_at = datetime.now(UTC) - timedelta(minutes=10)
        row.ended_at = datetime.now(UTC)
        await db.commit()

    params = {"job_target_id": job["id"], "resume_id": first["id"]}
    reports = (await client.get("/reports", params=params)).json()
    assert {(r["type"], r["resume_id"], r["resume_name"]) for r in reports} == {
        ("gap_report", first["id"], "First CV"),
        ("interview_debrief", first["id"], "First CV"),
    }
    other = (await client.get("/reports", params={**params, "resume_id": second["id"]})).json()
    assert [r["type"] for r in other] == ["gap_report"]
