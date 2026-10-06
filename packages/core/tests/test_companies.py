"""IN-5 and spec 'Companies outside the 20': company name keys and the request log."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_core.companies import (
    most_requested_uncurated,
    normalize_company_name,
    record_company_request,
)
from strong_core.db.models import Base, CompanyRequest


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Stripe", "stripe"),
        ("Stripe, Inc.", "stripe"),
        ("  The Stripe Company (US) ", "stripe"),
        ("Meta Platforms, Inc.", "meta"),
        ("salesforce.com", "salesforce com"),
        ("Société Générale", "societe generale"),
        ("Harbor Robotics Labs LLC", "harbor robotics"),
        ("Inc.", ""),
    ],
)
def test_in5_normalize_company_name(name: str, key: str) -> None:
    assert normalize_company_name(name) == key


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """SQLite with only the company_requests table. SQLite does not enforce the foreign keys."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[Base.metadata.tables["company_requests"]]
        )
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def test_record_company_request_stores_name_key_and_host(db: AsyncSession) -> None:
    org_id, user_id, target_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await record_company_request(
        db,
        org_id=org_id,
        user_id=user_id,
        job_target_id=target_id,
        company_name="  Harbor Robotics, Inc. ",
        matched_company_id=None,
        source_host="harborrobotics.example",
    )
    await db.commit()

    row = await db.scalar(select(CompanyRequest))
    assert row is not None
    assert row.company_name == "Harbor Robotics, Inc."
    assert row.normalized_name == "harbor robotics"
    assert (row.org_id, row.user_id, row.job_target_id) == (org_id, user_id, target_id)
    assert row.matched_company_id is None
    assert row.source_host == "harborrobotics.example"


async def test_most_requested_uncurated_counts_distinct_users(db: AsyncSession) -> None:
    """The most-requested companies outside the curated list come first."""
    org = uuid.uuid4()
    alice, bob, carol = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    curated = uuid.uuid4()
    requests = [
        (alice, "Harbor Robotics", None),
        (alice, "Harbor Robotics, Inc.", None),  # same user again: counts once
        (bob, "harbor robotics", None),
        (carol, "Northwind Logistics", None),
        (bob, "Stripe", curated),  # curated: not in the report
        (carol, "Inc.", None),  # empty key: not in the report
    ]
    for user, name, matched in requests:
        await record_company_request(
            db, org_id=org, user_id=user, company_name=name, matched_company_id=matched
        )
    await db.commit()

    assert await most_requested_uncurated(db) == [
        ("harbor robotics", 2),
        ("northwind logistics", 1),
    ]
    assert await most_requested_uncurated(db, limit=1) == [("harbor robotics", 2)]
