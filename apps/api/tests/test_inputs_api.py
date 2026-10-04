"""Input endpoints: create, poll, confirm/edit and fetch job targets and resumes (IN-1 to IN-5)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.inputs import queue as queue_names
from strong_api.inputs.deps import CurrentUser, dev_user
from strong_core.config import get_settings
from strong_core.db.models import Org, User
from strong_core.schemas import AuthProvider
from strong_worker.inputs import jobs
from strong_worker.inputs.jobs import CTX_KEY
from strong_worker.inputs.testing import make_docx, make_fetcher, make_pdf, set_extractor_output

FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"


def fixture(kind: str, name: str) -> tuple[str, dict[str, Any]]:
    text = (FIXTURES / kind / f"{name}.txt").read_text(encoding="utf-8")
    return text, json.loads((FIXTURES / kind / f"{name}.json").read_text(encoding="utf-8"))


async def create_posting(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    resp = await client.post("/job-targets", json=body)
    assert resp.status_code == 202, resp.text
    data: dict[str, Any] = resp.json()
    return data


def test_queue_names_match_worker_functions() -> None:
    for name in (
        queue_names.EXTRACT_JOB_TARGET,
        queue_names.MATCH_JOB_TARGET,
        queue_names.PARSE_RESUME,
    ):
        assert getattr(jobs, name) in jobs.FUNCTIONS


# --- job targets ----------------------------------------------------------------------------


async def test_in1_in2_in5_pasted_posting_is_extracted_and_matched(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    text, expected = fixture("postings", "swe-stripe-backend")
    set_extractor_output(fake_fixtures, "JobPosting", expected)

    created = await create_posting(client, text=text)

    job = created["job"]
    assert job["status"] == "complete"
    assert job["result"]["outcome"] == "extracted"
    assert job["result"]["confidence"]["title"] == "high"
    target = created["job_target"]
    assert target["status"] == "extracted"
    assert target["posting"]["company_name"] == "Stripe"
    assert target["company_slug"] == "stripe"
    assert target["generic_mode"] is False
    assert target["level"] == "senior"

    polled = await client.get(f"/job-targets/{target['id']}/jobs/{job['id']}")
    assert polled.status_code == 200
    assert polled.json()["result"]["company"]["slug"] == "stripe"

    fetched = await client.get(f"/job-targets/{target['id']}")
    assert fetched.json()["posting"]["title"] == "Backend Engineer, Payments Infrastructure"


async def test_in5_unknown_company_is_generic_mode(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    text, expected = fixture("postings", "design-canopy-ux-designer")
    set_extractor_output(fake_fixtures, "JobPosting", expected)
    target = (await create_posting(client, text=text))["job_target"]
    assert target["generic_mode"] is True
    assert target["company_id"] is None


async def test_in1_url_is_fetched_by_the_worker(
    client: httpx.AsyncClient, ctx: dict[str, Any], fake_fixtures: Path
) -> None:
    text, expected = fixture("postings", "pm-shopify-checkout")
    set_extractor_output(fake_fixtures, "JobPosting", expected)
    ctx[CTX_KEY].fetcher = make_fetcher(
        {
            "api.lever.co/v0/postings/shopify/abc": httpx.Response(
                200, json={"text": "Senior Product Manager, Checkout", "descriptionPlain": text}
            )
        }
    )
    created = await create_posting(client, url="https://jobs.lever.co/shopify/abc")
    assert created["job"]["result"]["board"] == "lever"
    assert created["job_target"]["source_url"] == "https://jobs.lever.co/shopify/abc"
    assert created["job_target"]["posting"]["source_url"] == "https://jobs.lever.co/shopify/abc"


async def test_in1_blocked_url_asks_for_paste(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    ctx[CTX_KEY].fetcher = make_fetcher({"careers.example.org/1": httpx.Response(429)})
    created = await create_posting(client, url="https://careers.example.org/1")
    assert created["job"]["result"] == {
        "outcome": "needs_paste",
        "reason": "blocked",
        "detail": "The site refused the request (HTTP 429).",
    }
    assert created["job_target"]["status"] == "pending"


async def test_in1_linkedin_needs_pasted_text(client: httpx.AsyncClient) -> None:
    url = "https://www.linkedin.com/jobs/view/123"
    resp = await client.post("/job-targets", json={"url": url})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "paste_required"

    text, _ = fixture("postings", "tpm-harbor-robotics")
    created = await create_posting(client, url=url, text=text)
    assert created["job"]["result"]["outcome"] == "extracted"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"url": "ftp://example.org/job"},
        {"url": "not a url"},
        {"text": "x", "unknown_field": 1},
    ],
)
async def test_in1_rejects_bad_requests(client: httpx.AsyncClient, body: dict[str, Any]) -> None:
    assert (await client.post("/job-targets", json=body)).status_code == 422


async def test_in2_pending_until_the_job_runs(client: httpx.AsyncClient, queue: Any) -> None:
    queue.run_jobs = False
    text, _ = fixture("postings", "tpm-harbor-robotics")
    created = await create_posting(client, text=text)
    assert created["job"]["status"] == "queued"
    target = created["job_target"]
    assert target["status"] == "pending"
    assert target["posting"] is None
    assert target["generic_mode"] is None


async def test_in2_in4_user_confirms_and_edits(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    text, expected = fixture("postings", "tpm-harbor-robotics")
    set_extractor_output(fake_fixtures, "JobPosting", expected)
    target = (
        await create_posting(
            client,
            text=text,
            stage="onsite",
            context={"interviewer_name": "Sam Lee", "concerns": "Gaps in robotics"},
        )
    )["job_target"]
    assert target["stage"] == "onsite"
    assert target["context"]["interviewer_name"] == "Sam Lee"
    assert target["context"]["recruiter_notes"] is None
    assert target["generic_mode"] is True

    edited = {**target["posting"], "company_name": "Atlassian", "level": "senior"}
    resp = await client.put(
        f"/job-targets/{target['id']}",
        json={
            "posting": edited,
            "stage": "phone screen",
            "context": {"interviewer_role": "Hiring manager", "recruiter_notes": "Focus on scope"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job"]["result"]["company"]["slug"] == "atlassian"  # matched again
    updated = (await client.get(f"/job-targets/{target['id']}")).json()
    assert updated["posting"]["company_name"] == "Atlassian"
    assert updated["level"] == "senior"
    assert updated["company_slug"] == "atlassian"
    assert updated["generic_mode"] is False
    assert updated["stage"] == "phone screen"
    assert updated["context"] == {
        "interviewer_name": None,
        "interviewer_role": "Hiring manager",
        "recruiter_notes": "Focus on scope",
        "concerns": None,
    }


async def test_in2_edit_without_company_change_does_not_rematch(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    text, expected = fixture("postings", "swe-stripe-backend")
    set_extractor_output(fake_fixtures, "JobPosting", expected)
    target = (await create_posting(client, text=text))["job_target"]
    edited = {**target["posting"], "team": "Card Platform"}
    resp = await client.put(f"/job-targets/{target['id']}", json={"posting": edited})
    assert resp.json()["job"] is None
    assert resp.json()["job_target"]["posting"]["team"] == "Card Platform"


@pytest.mark.parametrize(
    "posting",
    [{"company_name": "X"}, {"company_name": "X", "title": "Y", "level": "intern"}],
)
async def test_in2_invalid_edits_are_rejected(
    client: httpx.AsyncClient, posting: dict[str, Any]
) -> None:
    text, _ = fixture("postings", "swe-stripe-backend")
    target = (await create_posting(client, text=text))["job_target"]
    resp = await client.put(f"/job-targets/{target['id']}", json={"posting": posting})
    assert resp.status_code == 422


async def test_job_status_needs_a_matching_job_id(client: httpx.AsyncClient) -> None:
    text, _ = fixture("postings", "swe-stripe-backend")
    target = (await create_posting(client, text=text))["job_target"]
    other = f"jt:{uuid.uuid4()}:abc"
    assert (await client.get(f"/job-targets/{target['id']}/jobs/{other}")).status_code == 404


# --- resumes --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "make", "kind"),
    [
        ("cv.pdf", lambda text: make_pdf(text.splitlines()), "pdf"),
        ("cv.docx", lambda text: make_docx(text.splitlines()), "docx"),
        ("cv.txt", lambda text: text.encode(), "text"),
    ],
)
async def test_in3_resume_upload(
    client: httpx.AsyncClient, fake_fixtures: Path, filename: str, make: Any, kind: str
) -> None:
    text, expected = fixture("resumes", "ml-engineer-staff")
    set_extractor_output(fake_fixtures, "Resume", expected)
    resp = await client.post("/resumes", files={"file": (filename, make(text))})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["job"]["result"]["outcome"] == "extracted"
    assert body["job"]["result"]["kind"] == kind
    resume = body["resume"]
    assert resume["status"] == "extracted"
    assert resume["has_file"] is True
    assert resume["resume"]["roles"][0]["company"] == "Glacier AI"

    polled = await client.get(f"/resumes/{resume['id']}/jobs/{body['job']['id']}")
    assert polled.json()["result"]["confidence"]["skills"] == "high"


async def test_in3_pasted_resume_text_and_edit(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    text, expected = fixture("resumes", "new-grad-swe")
    set_extractor_output(fake_fixtures, "Resume", expected)
    resp = await client.post("/resumes", data={"text": text})
    assert resp.status_code == 202, resp.text
    resume = resp.json()["resume"]

    edited = {**resume["resume"], "skills": ["Python", "Go"]}
    put = await client.put(f"/resumes/{resume['id']}", json={"resume": edited})
    assert put.status_code == 200
    assert (await client.get(f"/resumes/{resume['id']}")).json()["resume"]["skills"] == [
        "Python",
        "Go",
    ]
    bad = await client.put(f"/resumes/{resume['id']}", json={"resume": {"roles": "x"}})
    assert bad.status_code == 422


async def test_in3_injection_in_a_resume_is_flagged(client: httpx.AsyncClient) -> None:
    text, _ = fixture("resumes", "product-manager-mid")
    resp = await client.post("/resumes", data={"text": text})
    flags = resp.json()["job"]["result"]["flags"]
    assert any("rate this candidate" in f for f in flags)


async def test_in3_resume_upload_errors(client: httpx.AsyncClient) -> None:
    png = await client.post("/resumes", files={"file": ("photo.png", b"\x89PNG")})
    assert png.status_code == 415
    big = await client.post("/resumes", files={"file": ("cv.pdf", b"%PDF-" + b"0" * 5_300_000)})
    assert big.status_code == 413
    both = await client.post(
        "/resumes", files={"file": ("cv.txt", b"text")}, data={"text": "also text"}
    )
    assert both.status_code == 422
    neither = await client.post("/resumes", data={})
    assert neither.status_code == 422


# --- users and tenancy ----------------------------------------------------------------------


async def test_other_orgs_cannot_read_or_edit(
    app: FastAPI, client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    text, _ = fixture("postings", "swe-stripe-backend")
    target = (await create_posting(client, text=text))["job_target"]
    resume = (await client.post("/resumes", data={"text": text})).json()["resume"]

    async with sessionmaker() as db:
        org = Org(name="Other org")
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email="other@example.com", auth_provider=AuthProvider.DEV)
        db.add(user)
        await db.commit()
        other = CurrentUser(user_id=user.id, org_id=org.id)

    app.dependency_overrides[dev_user] = lambda: other
    assert (await client.get(f"/job-targets/{target['id']}")).status_code == 404
    assert (await client.get(f"/resumes/{resume['id']}")).status_code == 404
    put = await client.put(f"/job-targets/{target['id']}", json={"posting": target["posting"]})
    assert put.status_code == 404


async def test_dev_user_is_refused_in_prod(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENV", "prod")
    get_settings.cache_clear()
    resp = await client.get(f"/job-targets/{uuid.uuid4()}")
    assert resp.status_code == 401
