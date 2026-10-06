"""IN-5: match the posting to one of the 20 curated companies, else generic mode."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.companies import most_requested_uncurated, normalize_company_name
from strong_core.db.models import CompanyRequest
from strong_core.db.seed import LAUNCH_COMPANIES
from strong_worker.inputs.matching import (
    CompanyRef,
    board_token,
    match_and_log,
    match_company,
)

COMPANIES = [CompanyRef(uuid.uuid4(), slug, name) for slug, name in LAUNCH_COMPANIES]


def slug_of(name: str | None, url: str | None = None) -> str | None:
    found = match_company(COMPANIES, name, url)
    return found.company.slug if found.company else None


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Stripe", "stripe"),
        ("Stripe, Inc.", "stripe"),
        ("Meta Platforms, Inc.", "meta"),
        ("Facebook", "meta"),
        ("Amazon Web Services (AWS)", "amazon"),
        ("Google LLC", "google"),
        ("Google DeepMind", "google"),
        ("salesforce.com", "salesforce"),
        ("NVIDIA Corporation", "nvidia"),
        ("The Atlassian Group", "atlassian"),
        ("OpenAI", "openai"),
    ],
)
def test_in5_matches_by_name(name: str, slug: str) -> None:
    assert slug_of(name) == slug
    assert match_company(COMPANIES, name, None).method == "name"


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://careers.google.com/jobs/results/123", "google"),
        ("https://www.amazon.jobs/en/jobs/2876543", "amazon"),
        ("https://www.metacareers.com/jobs/1", "meta"),
        ("https://boards.greenhouse.io/databricks/jobs/77", "databricks"),
        ("https://job-boards.greenhouse.io/anthropic/jobs/5", "anthropic"),
        ("https://jobs.ashbyhq.com/openai/abc", "openai"),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/External/job/X/Y_1", "nvidia"),
        ("https://careers.linkedin.com/jobs/1", "linkedin"),
    ],
)
def test_in5_matches_by_domain_when_the_name_is_unknown(url: str, slug: str) -> None:
    found = match_company(COMPANIES, "Unknown", url)
    assert found.company is not None and found.company.slug == slug
    assert found.method == "domain"


def test_in5_linkedin_job_board_is_not_the_linkedin_company() -> None:
    assert slug_of("Unknown", "https://www.linkedin.com/jobs/view/123") is None


def test_in5_name_wins_over_a_job_board_domain() -> None:
    assert slug_of("Shopify", "https://boards.greenhouse.io/stripe/jobs/1") == "shopify"


@pytest.mark.parametrize(
    "name", ["Northwind Logistics", "Applied Robotics", "Metaview", "Unknown", "", None]
)
def test_in5_unknown_companies_run_generic_mode(name: str | None) -> None:
    found = match_company(COMPANIES, name, "https://careers.example.org/jobs/1")
    assert found.generic_mode
    assert found.summary() == {
        "company_id": None,
        "slug": None,
        "method": "none",
        "generic_mode": True,
    }


def test_inactive_companies_are_not_offered() -> None:
    assert match_company([], "Stripe", None).generic_mode


def test_helpers() -> None:
    assert normalize_company_name("  The Stripe Company (US) ") == "stripe"
    assert board_token("https://jobs.lever.co/acme/1") == "acme"
    assert board_token("https://example.org/jobs") is None


async def test_in5_company_requests_are_logged(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Every company name is logged; unknown ones have no matched company (spec: request
    this company)."""
    org_id, user_id = account
    job_target_id = uuid.uuid4()
    async with sessionmaker() as db:
        known = await match_and_log(
            db,
            org_id=org_id,
            user_id=user_id,
            job_target_id=job_target_id,
            company_name="Uber",
            source_url=None,
        )
        unknown = await match_and_log(
            db,
            org_id=org_id,
            user_id=user_id,
            job_target_id=job_target_id,
            company_name="Harbor Robotics, Inc.",
            source_url="https://www.harborrobotics.example/careers/9",
        )
        await db.commit()
        rows = {r.company_name: r for r in await db.scalars(select(CompanyRequest))}
        report = await most_requested_uncurated(db)

    assert known.company is not None and known.company.slug == "uber"
    assert unknown.generic_mode
    assert set(rows) == {"Uber", "Harbor Robotics, Inc."}
    assert rows["Uber"].matched_company_id == known.company.id
    harbor = rows["Harbor Robotics, Inc."]
    assert harbor.matched_company_id is None
    assert harbor.normalized_name == "harbor robotics"
    assert harbor.source_host == "harborrobotics.example"
    assert (harbor.org_id, harbor.user_id) == (org_id, user_id)
    assert report == [("harbor robotics", 1)]
