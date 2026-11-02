"""Resume comparison endpoints (RC-1 to RC-8), with the fake model and the inline worker."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.gap.settings import GapSettings, get_gap_settings
from strong_api.inputs import queue as queue_names
from strong_core.config import get_settings
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import ResumeComparison, TargetInterview
from strong_core.schemas import GapPurpose, GapStatus
from strong_worker.gap import jobs as gap_jobs
from strong_worker.inputs.testing import set_extractor_output

from .conftest import sign_in

FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"


def fixture(kind: str, name: str) -> tuple[str, dict[str, Any]]:
    text = (FIXTURES / kind / f"{name}.txt").read_text(encoding="utf-8")
    return text, json.loads((FIXTURES / kind / f"{name}.json").read_text(encoding="utf-8"))


async def add_job(client: httpx.AsyncClient, fake_fixtures: Path) -> dict[str, Any]:
    text, posting = fixture("postings", "swe-stripe-backend")
    set_extractor_output(fake_fixtures, "JobPosting", posting)
    target = (await client.post("/job-targets", json={"text": text})).json()["job_target"]
    assert target["status"] == "extracted"
    return target


async def add_resume(client: httpx.AsyncClient, fake_fixtures: Path, name: str) -> dict[str, Any]:
    text, parsed = fixture("resumes", name)
    set_extractor_output(fake_fixtures, "Resume", parsed)
    out = (await client.post("/resumes", data={"text": text})).json()["resume"]
    out = (await client.get(f"/resumes/{out['id']}")).json()
    assert out["status"] == "extracted"
    return out


def url(target: dict[str, Any]) -> str:
    return f"/roles/{target['id']}/resume-comparison"


def limits(app: FastAPI, **values: int) -> None:
    app.dependency_overrides[get_gap_settings] = lambda: GapSettings(**values)


async def test_rc1_needs_two_resumes_and_runs_only_on_request(
    client: httpx.AsyncClient, fake_fixtures: Path, queue: Any
) -> None:
    """RC-1: nothing runs until asked; with one resume the API says too_few_resumes."""
    target = await add_job(client, fake_fixtures)
    await add_resume(client, fake_fixtures, "backend-senior")
    assert (await client.get(url(target))).status_code == 404
    resp = await client.post(url(target))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "too_few_resumes"
    assert not [j for j in queue.enqueued if j[0] == queue_names.RUN_GAP_ANALYSIS]
    assert (await client.post(f"/roles/{uuid.uuid4()}/resume-comparison")).status_code == 404


async def test_rc2_rc3_compares_every_resume_and_recommends_one(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RC-2, RC-3: each resume gets a gap analysis; code ranks them, explains the pick and
    shows the rule-based must-have counts."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    grad = await add_resume(client, fake_fixtures, "new-grad-swe")
    started = await client.post(url(target))
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["status"] == "ready" and body["new_runs"] == 2
    assert [r["rank"] for r in body["resumes"]] == [1, 2]
    by_id = {r["resume_id"]: r for r in body["resumes"]}
    assert set(by_id) == {senior["id"], grad["id"]}
    assert body["recommended_resume_id"] == senior["id"]
    assert by_id[senior["id"]]["match_score"] > by_id[grad["id"]]["match_score"]
    assert all(r["must_haves_total"] == 5 for r in body["resumes"])
    assert all(not r["reused"] and r["status"] == "ready" for r in body["resumes"])
    assert body["reason"].startswith(f"{senior['name']} fits best")
    assert body["focus_resume_id"] == senior["id"]
    assert body["gaps"] and body["gaps"][0]["severity"] == "high"
    assert body["out_of_date"] is False
    assert (await client.get(url(target))).json()["id"] == body["id"]


async def test_rc2_reuses_unchanged_analyses_and_rc8_compare_again_is_free(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path, queue: Any
) -> None:
    """RC-2: an analysis of the same job and resume is reused. RC-8: comparing again with
    nothing changed starts nothing and does not count (RC-7)."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    await add_resume(client, fake_fixtures, "new-grad-swe")
    role_gap = await client.post(
        f"/job-targets/{target['id']}/gap-analysis", json={"resume_id": senior["id"]}
    )
    first = (await client.post(url(target))).json()
    assert first["new_runs"] == 1
    reused = {r["resume_id"]: r["reused"] for r in first["resumes"]}
    assert reused[senior["id"]] is True
    by_id = {r["resume_id"]: r for r in first["resumes"]}
    assert by_id[senior["id"]]["gap_analysis_id"] == role_gap.json()["id"]

    runs = len(queue.enqueued)
    limits(app, gap_rate_limit_per_hour=1, gap_rate_limit_per_day=40)  # already used up
    again = await client.post(url(target))
    assert again.status_code == 202
    assert again.json()["new_runs"] == 0
    assert all(r["reused"] for r in again.json()["resumes"])
    assert len(queue.enqueued) == runs


async def test_rc7_comparison_rows_never_become_the_roles_analysis(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """RC-7: the role's analysis, its match score and the reports ignore comparison rows."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    grad = await add_resume(client, fake_fixtures, "new-grad-swe")
    gap_url = f"/job-targets/{target['id']}/gap-analysis"
    role_gap = (await client.post(gap_url, json={"resume_id": grad["id"]})).json()
    await client.post(url(target))
    async with sessionmaker() as db:
        purposes = list(
            await db.scalars(
                select(GapRow.purpose).where(GapRow.job_target_id == uuid.UUID(target["id"]))
            )
        )
        # The interviewer brief (worker) uses the role's analysis, never a comparison row.
        job_id = uuid.UUID(target["id"])
        brief_gap = await gap_jobs.latest_ready_gap(db, job_id)
        assert brief_gap is not None and str(brief_gap.id) == role_gap["id"]
        assert await gap_jobs.latest_ready_gap(db, job_id, uuid.UUID(senior["id"])) is None
    assert sorted(purposes) == [GapPurpose.COMPARISON, GapPurpose.ROLE]
    latest = (await client.get(gap_url)).json()
    assert latest["id"] == role_gap["id"] and latest["resume_id"] == grad["id"]
    listed = (await client.get("/job-targets")).json()
    assert listed[0]["match_score"] == role_gap["analysis"]["match_score"]
    reports = (await client.get("/reports")).json()
    gap_reports = [r for r in reports if r["type"] == "gap_report"]
    assert [r["id"] for r in gap_reports] == [role_gap["id"]]
    assert senior["id"] not in {r.get("resume_id") for r in gap_reports}


async def test_rc7_a_comparison_counts_as_one_run(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RC-7: two new analyses in one comparison use one run of the hourly limit."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    await add_resume(client, fake_fixtures, "new-grad-swe")
    limits(app, gap_rate_limit_per_hour=2, gap_rate_limit_per_day=40)
    assert (await client.post(url(target))).status_code == 202  # 2 analyses, 1 run
    gap_url = f"/job-targets/{target['id']}/gap-analysis"
    assert (await client.post(gap_url, json={"resume_id": senior["id"]})).status_code == 202
    limited = await client.post(gap_url, json={"resume_id": senior["id"]})
    assert limited.status_code == 429

    # A comparison that needs a new analysis is refused over the limit too.
    put = await client.get(f"/resumes/{senior['id']}")
    changed = put.json()["resume"]
    changed["skills"] = [*changed["skills"], "Rust"]
    assert (await client.put(f"/resumes/{senior['id']}", json={"resume": changed})).is_success
    refused = await client.post(url(target))
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "rate_limited"


async def test_rc8_out_of_date_when_a_resume_changes_or_is_added(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RC-8: the saved comparison says when it no longer matches; compare again reruns only
    the changed pair."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    await add_resume(client, fake_fixtures, "new-grad-swe")
    await client.post(url(target))
    resume = (await client.get(f"/resumes/{senior['id']}")).json()["resume"]
    resume["skills"] = [*resume["skills"], "Rust"]
    assert (await client.put(f"/resumes/{senior['id']}", json={"resume": resume})).is_success
    body = (await client.get(url(target))).json()
    assert body["out_of_date"] is True
    assert senior["name"] in body["out_of_date_reason"]
    again = (await client.post(url(target))).json()
    assert again["new_runs"] == 1 and again["out_of_date"] is False

    await add_resume(client, fake_fixtures, "ml-engineer-staff")
    body = (await client.get(url(target))).json()
    assert body["out_of_date"] is True
    assert body["out_of_date_reason"] == "You added a resume since this comparison."
    third = (await client.post(url(target))).json()
    assert len(third["resumes"]) == 3 and third["new_runs"] == 1


async def test_rc6_use_this_one_moves_the_role_to_the_resume(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """RC-6: Use this one moves the role's interviews to the resume and copies its analysis into
    the role's own analysis, with no new run. Nothing switches before that."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    grad = await add_resume(client, fake_fixtures, "new-grad-swe")
    made = await client.post(
        f"/roles/{target['id']}/interviews",
        json={"resume_id": grad["id"], "interview_types": ["behavioral", "technical_qa"]},
    )
    assert made.status_code == 201, made.text
    body = (await client.post(url(target))).json()
    assert body["role_resume_id"] == grad["id"]
    assert body["recommended_resume_id"] == senior["id"]
    assert body["chosen_resume_id"] is None

    use = f"/resume-comparisons/{body['id']}/use"
    assert (await client.post(use, json={"resume_id": str(uuid.uuid4())})).status_code == 404
    used = await client.post(use, json={"resume_id": senior["id"]})
    assert used.status_code == 200, used.text
    out = used.json()
    assert out["chosen_resume_id"] == senior["id"] and out["role_resume_id"] == senior["id"]
    interviews = (await client.get(f"/roles/{target['id']}/interviews")).json()
    assert {i["interview"]["resume_id"] for i in interviews} == {senior["id"]}
    assert [i["interview"]["interview_type"] for i in interviews] == ["behavioral", "technical_qa"]

    gap = (await client.get(f"/job-targets/{target['id']}/gap-analysis")).json()
    assert gap["resume_id"] == senior["id"] and gap["status"] == "ready" and not gap["stale"]
    async with sessionmaker() as db:
        row = await db.get(GapRow, uuid.UUID(gap["id"]))
        assert row is not None and row.purpose == GapPurpose.ROLE
        source = next(r for r in body["resumes"] if r["resume_id"] == senior["id"])
        assert row.source_gap_id == uuid.UUID(source["gap_analysis_id"])
        archived = list(
            await db.scalars(
                select(TargetInterview).where(TargetInterview.archived_at.is_not(None))
            )
        )
        assert {a.resume_id for a in archived} == {uuid.UUID(grad["id"])}
    # Using it again changes nothing more.
    assert (await client.post(use, json={"resume_id": senior["id"]})).status_code == 200
    assert len((await client.get(f"/roles/{target['id']}/interviews")).json()) == 2


async def _comparison_with(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A comparison whose analyses are written by hand: the focus resume lacks Kafka, the other
    shows it as a skill; payments experience is covered by no resume."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    grad = await add_resume(client, fake_fixtures, "new-grad-swe")
    queue.run_jobs = False
    body = (await client.post(url(target))).json()
    assert body["status"] == "running" and body["recommended_resume_id"] is None
    plan = [{"priority": 1, "interview_type": "behavioral", "focus_topics": ["x"], "reason": "y"}]
    analyses = {
        grad["id"]: {
            "match_score": 80,
            "requirement_breakdown": [
                {"requirement": "Kafka", "kind": "must_have", "score": 0, "evidence": None}
            ],
            "gaps": [
                {"summary": "No Kafka", "severity": "medium", "related_requirement": "Kafka"},
                {"summary": "No payments", "severity": "high", "related_requirement": "Pay"},
            ],
            "session_plan": plan,
        },
        senior["id"]: {
            "match_score": 60,
            "requirement_breakdown": [
                {"requirement": "Kafka", "kind": "must_have", "score": 70, "evidence": "Kafka"}
            ],
            "session_plan": plan,
        },
    }
    async with sessionmaker() as db:
        for r in body["resumes"]:
            row = await db.get(GapRow, uuid.UUID(r["gap_analysis_id"]))
            assert row is not None
            row.status = GapStatus.READY
            row.breakdown_json = analyses[r["resume_id"]]
            row.match_score = analyses[r["resume_id"]]["match_score"]
        await db.commit()
    queue.run_jobs = True
    return target, senior, grad


async def test_rc4_add_to_resume_copies_the_line_and_dismiss_hides_it(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """RC-4: a gap another resume covers names it; Add to resume copies its line unchanged,
    with no model call; Dismiss hides a hint. Both persist."""
    target, senior, grad = await _comparison_with(client, fake_fixtures, queue, sessionmaker)
    body = (await client.get(url(target))).json()
    assert body["recommended_resume_id"] == grad["id"] == body["focus_resume_id"]
    high, medium = body["gaps"]
    assert high["severity"] == "high" and medium["severity"] == "medium"
    assert medium["source"] == {
        "resume_id": senior["id"],
        "resume_name": senior["name"],
        "line": "Kafka",
        "place": "skills",
        "company": None,
        "can_add": True,
    }
    comparison = body["id"]
    gap_runs = len([j for j in queue.enqueued if j[0] == queue_names.RUN_GAP_ANALYSIS])
    added = await client.post(f"/resume-comparisons/{comparison}/hints/{medium['key']}/add")
    assert added.status_code == 200, added.text
    hint = next(g for g in added.json()["gaps"] if g["key"] == medium["key"])
    assert hint["status"] == "added"
    resume = (await client.get(f"/resumes/{grad['id']}")).json()["resume"]
    assert resume["skills"][-1] == "Kafka"
    assert len([j for j in queue.enqueued if j[0] == queue_names.RUN_GAP_ANALYSIS]) == gap_runs
    again = await client.post(f"/resume-comparisons/{comparison}/hints/{medium['key']}/add")
    assert again.status_code == 409
    # The resume changed, so the comparison is out of date until the user compares again.
    assert added.json()["out_of_date"] is True

    dismissed = await client.post(f"/resume-comparisons/{comparison}/hints/{high['key']}/dismiss")
    assert dismissed.status_code == 200
    hint = next(g for g in dismissed.json()["gaps"] if g["key"] == high["key"])
    assert hint["status"] == "dismissed"
    missing = await client.post(f"/resume-comparisons/{comparison}/hints/nope/dismiss")
    assert missing.status_code == 404


async def test_rc5_a_gap_no_resume_covers_has_no_source(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """RC-5: no resume covers it, so there is nothing to add; the web offers Craft a story."""
    target, _, _ = await _comparison_with(client, fake_fixtures, queue, sessionmaker)
    body = (await client.get(url(target))).json()
    high = next(g for g in body["gaps"] if g["severity"] == "high")
    assert high["source"] is None and high["status"] == "open"
    add = await client.post(f"/resume-comparisons/{body['id']}/hints/{high['key']}/add")
    assert add.status_code == 409


async def test_comparisons_belong_to_one_user(
    app: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    target = await add_job(client, fake_fixtures)
    await add_resume(client, fake_fixtures, "backend-senior")
    await add_resume(client, fake_fixtures, "new-grad-swe")
    body = (await client.post(url(target))).json()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as other:
        await sign_in(other, "other@example.com")
        assert (await other.get(url(target))).status_code == 404
        first = body["resumes"][0]["resume_id"]
        use = await other.post(f"/resume-comparisons/{body['id']}/use", json={"resume_id": first})
        assert use.status_code == 404


async def test_rc8_comparison_is_saved_on_the_role(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    target = await add_job(client, fake_fixtures)
    await add_resume(client, fake_fixtures, "backend-senior")
    await add_resume(client, fake_fixtures, "new-grad-swe")
    body = (await client.post(url(target))).json()
    async with sessionmaker() as db:
        row = await db.get(ResumeComparison, uuid.UUID(body["id"]))
        assert row is not None
        assert row.job_target_id == uuid.UUID(target["id"])
        assert len(row.entries_json) == 2 and row.new_runs == 2


async def test_rc6_creating_the_role_after_comparing_copies_the_analysis(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """RC-6 on Add a target role: the role's first analysis (reuse_ready) is a copy of the
    comparison's analysis of the picked resume, so creating the role starts no new run."""
    target = await add_job(client, fake_fixtures)
    senior = await add_resume(client, fake_fixtures, "backend-senior")
    await add_resume(client, fake_fixtures, "new-grad-swe")
    body = (await client.post(url(target))).json()
    runs = len([j for j in queue.enqueued if j[0] == queue_names.RUN_GAP_ANALYSIS])
    started = await client.post(
        f"/job-targets/{target['id']}/gap-analysis",
        json={"resume_id": senior["id"], "reuse_ready": True},
    )
    assert started.status_code == 202 and started.json()["status"] == "ready"
    assert len([j for j in queue.enqueued if j[0] == queue_names.RUN_GAP_ANALYSIS]) == runs
    source = next(r for r in body["resumes"] if r["resume_id"] == senior["id"])
    async with sessionmaker() as db:
        row = await db.get(GapRow, uuid.UUID(started.json()["id"]))
        assert row is not None and row.purpose == GapPurpose.ROLE
        assert row.source_gap_id == uuid.UUID(source["gap_analysis_id"])
