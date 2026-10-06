"""The Arq jobs end to end, on SQLite with the fake model: IN-1, IN-2, IN-3, IN-5."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import get_settings
from strong_core.db.models import AuditLog, Company, JobTarget
from strong_core.db.models import Resume as ResumeRow
from strong_worker.inputs import jobs
from strong_worker.inputs.jobs import CTX_KEY
from strong_worker.inputs.testing import make_docx, make_fetcher, make_pdf, set_extractor_output
from strong_worker.main import WorkerSettings

FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"
Account = tuple[uuid.UUID, uuid.UUID]


def posting(name: str) -> tuple[str, dict[str, Any]]:
    text = (FIXTURES / "postings" / f"{name}.txt").read_text(encoding="utf-8")
    return text, json.loads((FIXTURES / "postings" / f"{name}.json").read_text(encoding="utf-8"))


async def new_job_target(
    maker: async_sessionmaker[AsyncSession], account: Account, **values: Any
) -> JobTarget:
    org_id, user_id = account
    async with maker() as db:
        target = JobTarget(org_id=org_id, user_id=user_id, **values)
        db.add(target)
        await db.commit()
        return target


async def reload(maker: async_sessionmaker[AsyncSession], target_id: uuid.UUID) -> JobTarget:
    async with maker() as db:
        found = await db.get(JobTarget, target_id)
        assert found is not None
        return found


def test_jobs_are_registered_with_the_worker() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert {"extract_job_target", "match_job_target", "parse_resume"} <= names


async def test_in2_in5_extracts_pasted_posting_and_matches_company(
    ctx: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    account: Account,
    fake_fixtures: Path,
) -> None:
    text, expected = posting("swe-stripe-backend")
    set_extractor_output(fake_fixtures, "JobPosting", expected)
    target = await new_job_target(sessionmaker, account, raw_text=text)

    result = await jobs.extract_job_target(ctx, str(target.id), str(account[0]))

    assert result["outcome"] == "extracted"
    assert result["company"]["slug"] == "stripe"
    assert result["company"]["generic_mode"] is False
    assert result["confidence"]["company_name"] == "high"
    saved = await reload(sessionmaker, target.id)
    assert saved.parsed_json is not None
    assert saved.parsed_json["title"] == "Backend Engineer, Payments Infrastructure"
    assert saved.level is not None and saved.level.value == "senior"
    async with sessionmaker() as db:
        stripe = await db.scalar(select(Company).where(Company.slug == "stripe"))
    assert stripe is not None and saved.company_id == stripe.id


async def test_in5_unknown_company_runs_generic_mode_and_is_logged(
    ctx: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    account: Account,
    fake_fixtures: Path,
) -> None:
    text, expected = posting("tpm-harbor-robotics")
    set_extractor_output(fake_fixtures, "JobPosting", expected)
    target = await new_job_target(sessionmaker, account, raw_text=text)

    result = await jobs.extract_job_target(ctx, str(target.id), str(account[0]))

    assert result["company"]["generic_mode"] is True
    assert (await reload(sessionmaker, target.id)).company_id is None
    async with sessionmaker() as db:
        log = await db.scalar(select(AuditLog))
    assert log is not None and log.details_json is not None
    assert log.details_json["company_name"] == "Harbor Robotics"


async def test_in1_fetches_a_url_then_extracts(
    ctx: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    account: Account,
    fake_fixtures: Path,
) -> None:
    text, expected = posting("data-databricks-ml-serving")
    set_extractor_output(fake_fixtures, "JobPosting", expected)
    ctx[CTX_KEY].fetcher = make_fetcher(
        {
            "boards-api.greenhouse.io/v1/boards/databricks/jobs/77": httpx.Response(
                200, json={"title": "Staff ML Engineer", "content": text.replace("\n", "<br>")}
            )
        }
    )
    url = "https://boards.greenhouse.io/databricks/jobs/77"
    target = await new_job_target(sessionmaker, account, source_url=url)

    result = await jobs.extract_job_target(ctx, str(target.id), str(account[0]))

    assert result["outcome"] == "extracted"
    assert result["board"] == "greenhouse"
    saved = await reload(sessionmaker, target.id)
    assert saved.raw_text is not None and "Model Serving" in saved.raw_text
    assert saved.parsed_json is not None and saved.parsed_json["source_url"] == url


async def test_in1_linkedin_url_asks_for_paste(
    ctx: dict[str, Any], sessionmaker: async_sessionmaker[AsyncSession], account: Account
) -> None:
    target = await new_job_target(
        sessionmaker, account, source_url="https://www.linkedin.com/jobs/view/42"
    )
    result = await jobs.extract_job_target(ctx, str(target.id), str(account[0]))
    assert result["outcome"] == "needs_paste"
    assert result["reason"] == "linkedin"
    assert (await reload(sessionmaker, target.id)).parsed_json is None


async def test_job_targets_of_another_org_are_not_visible(
    ctx: dict[str, Any], sessionmaker: async_sessionmaker[AsyncSession], account: Account
) -> None:
    target = await new_job_target(sessionmaker, account, raw_text="x" * 200)
    result = await jobs.extract_job_target(ctx, str(target.id), str(uuid.uuid4()))
    assert result == {"outcome": "failed", "reason": "job target not found"}


async def test_in5_match_again_after_an_edit(
    ctx: dict[str, Any], sessionmaker: async_sessionmaker[AsyncSession], account: Account
) -> None:
    _, expected = posting("tpm-harbor-robotics")
    target = await new_job_target(
        sessionmaker, account, raw_text="x", parsed_json={**expected, "company_name": "Atlassian"}
    )
    result = await jobs.match_job_target(ctx, str(target.id), str(account[0]))
    assert result["company"]["slug"] == "atlassian"
    assert (await reload(sessionmaker, target.id)).company_id is not None


async def new_resume(maker: async_sessionmaker[AsyncSession], account: Account) -> ResumeRow:
    async with maker() as db:
        row = ResumeRow(org_id=account[0], user_id=account[1])
        db.add(row)
        await db.commit()
        return row


async def test_in3_parses_a_pdf_and_stores_it_encrypted(
    ctx: dict[str, Any], sessionmaker: async_sessionmaker[AsyncSession], account: Account
) -> None:
    row = await new_resume(sessionmaker, account)
    lines = (FIXTURES / "resumes/backend-senior.txt").read_text(encoding="utf-8").splitlines()
    pdf = make_pdf(lines)

    result = await jobs.parse_resume(ctx, str(row.id), str(account[0]), pdf, "cv.pdf")

    assert result["outcome"] == "extracted"
    assert result["kind"] == "pdf"
    async with sessionmaker() as db:
        saved = await db.get(ResumeRow, row.id)
    assert saved is not None and saved.parsed_json is not None
    assert saved.file_ref == f"local:resumes/{account[0]}/{row.id}.pdf"
    store = ctx[CTX_KEY].store
    assert await store.get(saved.file_ref) == pdf
    assert pdf not in (store.root / f"resumes/{account[0]}/{row.id}.pdf.enc").read_bytes()


async def test_in3_parses_docx_and_text(
    ctx: dict[str, Any], sessionmaker: async_sessionmaker[AsyncSession], account: Account
) -> None:
    text = (FIXTURES / "resumes/tpm-career-changer.txt").read_text(encoding="utf-8")
    for data, name, kind in (
        (make_docx(text.splitlines()), "cv.docx", "docx"),
        (text.encode(), "pasted.txt", "text"),
    ):
        row = await new_resume(sessionmaker, account)
        result = await jobs.parse_resume(ctx, str(row.id), str(account[0]), data, name)
        assert result["outcome"] == "extracted", result
        assert result["kind"] == kind


async def test_in3_unreadable_file_fails_with_a_reason(
    ctx: dict[str, Any], sessionmaker: async_sessionmaker[AsyncSession], account: Account
) -> None:
    row = await new_resume(sessionmaker, account)
    result = await jobs.parse_resume(ctx, str(row.id), str(account[0]), b"\x89PNG\x00\xff", "a.pdf")
    assert result["outcome"] == "failed"
    assert "Unsupported file type" in result["reason"]
