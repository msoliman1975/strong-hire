"""RM-5: the API's rule-based resume check gives the same results as the web check.

Both implementations run the shared cases in tests/fixtures/resume_checks/cases.json (the web
runs them in apps/web/src/pages/onboarding/resumeChecks.shared.test.ts).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from strong_api.resume_checks.checks import KEY_MAX, check_resume, fit_key
from strong_core.schemas import JobPosting, Resume

from .conftest import sign_in
from .test_library_api import add_job, add_resume

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "resume_checks" / "cases.json").read_text("utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_rm5_shared_cases_match_the_web_check(case: dict[str, Any]) -> None:
    """RM-5: same keys, groups, severities, copy and targets as the web check, in order."""
    resume = Resume.model_validate(case["resume"])
    job = JobPosting.model_validate(case["job"]) if case["job"] else None
    issues = check_resume(resume, today=case["today"], job=job)
    got = [i.model_dump(mode="json", by_alias=True, exclude_none=True) for i in issues]
    assert got == case["expected"]


def test_rm5_shared_cases_cover_every_rule() -> None:
    """RM-5: the shared cases exercise every issue type, so a rule cannot drift unnoticed."""
    kinds = {i["key"].split(":")[0] for c in CASES for i in c["expected"]}
    assert kinds >= {
        "dates.end-before-start",
        "dates.future",
        "dates.year-only",
        "dates.missing-start",
        "dates.overlap",
        "dates.gap",
        "dates.current-not-marked",
        "detail.few-achievements",
        "detail.no-result",
        "detail.we-no-i",
        "detail.summary-missing",
        "detail.summary-short",
        "detail.summary-no-number",
        "level.no-scope",
        "consistency.skills-missing",
        "consistency.same-company",
        "job.must-have",
    }


def test_rm5_long_keys_are_cut_with_a_stable_hash() -> None:
    """RM-5: keys over 200 characters end in the same FNV-1a hash as the web check."""
    key = "consistency.skills-missing:" + ",".join(f"skill-{i}" for i in range(60))
    cut = fit_key(key)
    assert len(cut) == KEY_MAX
    assert cut == fit_key(key)
    assert cut != fit_key(key + "x")
    assert fit_key("short") == "short"


def test_rm5_today_must_be_a_month() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        check_resume(Resume.model_validate(CASES[0]["resume"]), today="soon")


async def test_rm5_issues_endpoint_splits_open_and_accepted(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RM-5: GET /resumes/{id}/issues runs the check; accepted keys (with a reason too) move an
    issue to accepted. With a job target, the must-haves the resume never shows are added."""
    await sign_in(client)
    resume = await add_resume(client, fake_fixtures)
    # Give it issues: no summary, and a role with one achievement.
    edited = dict(resume["resume"], summary=None)
    edited["roles"] = [dict(edited["roles"][0], achievements=["Wrote docs"]), *edited["roles"][1:]]
    put = await client.put(f"/resumes/{resume['id']}", json={"resume": edited})
    assert put.status_code == 200, put.text
    resume = put.json()
    data = (await client.get(f"/resumes/{resume['id']}/issues")).json()
    expected = check_resume(
        Resume.model_validate(resume["resume"]), today=datetime.now(UTC).strftime("%Y-%m")
    )
    assert [i["key"] for i in data["open"]] == [i.key for i in expected]
    assert data["accepted"] == [] and data["job_target_id"] is None
    assert expected, "the fixture resume has issues to accept"
    first = data["open"][0]
    assert {"fixLabel", "acceptLabel", "target", "severity"} <= first.keys()

    stored = f"{first['key']}|why=on-purpose"
    put = await client.put(
        f"/resumes/{resume['id']}/accepted-issues", json={"key": stored, "accepted": True}
    )
    assert put.status_code == 200, put.text
    data = (await client.get(f"/resumes/{resume['id']}/issues")).json()
    assert first["key"] not in [i["key"] for i in data["open"]]
    assert [(i["key"], i["reason"]) for i in data["accepted"]] == [(first["key"], "on-purpose")]
    assert data["accepted"][0]["acceptedAt"]

    job = await add_job(client, fake_fixtures)
    posting = JobPosting.model_validate(job["posting"])
    with_job = await client.get(
        f"/resumes/{resume['id']}/issues", params={"job_target_id": job["id"]}
    )
    assert with_job.status_code == 200, with_job.text
    expected_job = check_resume(
        Resume.model_validate(resume["resume"]),
        today=datetime.now(UTC).strftime("%Y-%m"),
        job=posting,
    )
    got = with_job.json()
    assert got["job_target_id"] == job["id"]
    assert sorted(i["key"] for i in got["open"] + got["accepted"]) == sorted(
        i.key for i in expected_job
    )


async def test_rm5_issues_endpoint_is_per_user(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    await sign_in(client)
    resume = await add_resume(client, fake_fixtures)
    await sign_in(client, "someone@example.com")
    assert (await client.get(f"/resumes/{resume['id']}/issues")).status_code == 404
