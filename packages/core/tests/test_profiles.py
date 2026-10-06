"""Profile lookups and the generic default profile (IV-5, IN-5, AD-1), and the database rule that
one company has at most one Published profile version (AD-1).

The lookups run on SQLite. The one-Published rule also runs on Postgres 16 when
STRONG_TEST_POSTGRES_URL points at a database migrated to head (CI: the migrations job).
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from strong_core.config import find_repo_root
from strong_core.db.models import Base, Company, InterviewSession, JobTarget, Org, User
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.profiles import (
    GENERIC_PERSONA,
    ProfileError,
    ProfileFileError,
    generic_profile,
    get_published_profile,
    parse_profile,
    profile_for_session,
    resolve_profile,
    row_profile,
    use_profile_for_session,
)
from strong_core.schemas import (
    AuthProvider,
    Competency,
    Difficulty,
    InterviewType,
    Mode,
    ProfileStatus,
)

EXAMPLE = find_repo_root() / "profiles/examples/example-corp.json"
POSTGRES_URL = os.environ.get("STRONG_TEST_POSTGRES_URL")


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_: Any, compiler: Any, **kw: Any) -> str:
    return "JSON"


def example_data(slug: str = "google", name: str = "Google") -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["company_slug"] = slug
    data["company_name"] = name
    return data


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Company(slug="google", name="Google"))
        await session.commit()
        yield session
    await engine.dispose()


async def _company(db: AsyncSession, slug: str = "google") -> Company:
    company = await db.scalar(select(Company).where(Company.slug == slug))
    if company is None:
        company = Company(slug=slug, name=slug.title())
        db.add(company)
        await db.flush()
    return company


async def _add_version(
    db: AsyncSession,
    company: Company,
    version: int,
    status: ProfileStatus,
    data: dict[str, Any] | None = None,
) -> ProfileRow:
    profile = copy.deepcopy(data or example_data(company.slug, company.name))
    profile["meta"].update(version=version, status=status.value)
    row = ProfileRow(
        company_id=company.id,
        version=version,
        status=status,
        profile_json=profile,
        sources_json=profile["sources"],
    )
    db.add(row)
    await db.flush()
    return row


async def _session_for(db: AsyncSession, company_id: uuid.UUID | None) -> InterviewSession:
    org = Org(name="o")
    db.add(org)
    await db.flush()
    user = User(org_id=org.id, email=f"{uuid.uuid4()}@x.test", auth_provider=AuthProvider.DEV)
    db.add(user)
    await db.flush()
    target = JobTarget(org_id=org.id, user_id=user.id, company_id=company_id)
    db.add(target)
    await db.flush()
    session = InterviewSession(
        org_id=org.id,
        job_target_id=target.id,
        type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=30,
    )
    db.add(session)
    await db.flush()
    return session


# --- lookups (moved from apps/api with the code) ---------------------------------------------


async def test_iv5_generic_fallback_and_weights(db: AsyncSession) -> None:
    generic = await resolve_profile(db, None)
    assert generic.generic and generic.version is None
    assert generic.persona == GENERIC_PERSONA
    assert {generic.weight(c) for c in Competency} == {1.0}

    company = await _company(db)
    no_profile = await resolve_profile(db, company.id)
    assert no_profile.generic and no_profile.company_name == "Google"
    assert await get_published_profile(db, company.id) is None

    await _add_version(db, company, 1, ProfileStatus.DRAFT)
    draft_only = await resolve_profile(db, company.id)
    assert draft_only.generic, "a Draft is never used"

    await _add_version(db, company, 2, ProfileStatus.PUBLISHED)
    resolved = await resolve_profile(db, company.id)
    assert not resolved.generic and resolved.version == 2
    assert resolved.company_slug == "google"
    assert resolved.weight(Competency.OWNERSHIP) == 1.5
    assert resolved.weight(Competency.JUDGMENT) == 1.0
    assert resolved.values_framework is not None
    assert resolved.values_share == 0.25
    assert resolved.value_weights == {"Customer first": 1.0, "Own the outcome": 1.5}
    assert generic_profile().values_framework is None
    assert generic.values_share == 0.0 and generic.value_weights == {}


async def test_ad1_session_records_profile_version_and_keeps_it(db: AsyncSession) -> None:
    company = await _company(db)
    v1 = await _add_version(db, company, 1, ProfileStatus.PUBLISHED)

    session = await _session_for(db, company.id)
    used = await use_profile_for_session(db, session)
    await db.commit()
    assert used.version == 1 and session.profile_version == 1

    data = example_data()
    data["persona"]["tone"] = "Blunt"
    v1.status = ProfileStatus.ARCHIVED
    await db.flush()
    await _add_version(db, company, 2, ProfileStatus.PUBLISHED, data)
    await db.commit()
    published = await get_published_profile(db, company.id)
    assert published is not None and published.persona.tone == "Blunt"

    later = await profile_for_session(db, session)
    assert later.version == 1
    assert later.persona.tone == "Friendly and curious"

    generic_session = await _session_for(db, None)
    used = await use_profile_for_session(db, generic_session)
    assert used.generic and generic_session.profile_version is None
    assert (await profile_for_session(db, generic_session)).generic

    session.profile_version = 9
    with pytest.raises(ProfileError, match="used profile version 9"):
        await profile_for_session(db, session)


async def test_ad1_stored_profile_that_no_longer_validates_names_the_field(
    db: AsyncSession,
) -> None:
    company = await _company(db)
    data = example_data()
    del data["persona"]["tone"]
    row = await _add_version(db, company, 1, ProfileStatus.PUBLISHED, data)
    with pytest.raises(ProfileFileError) as err:
        row_profile(row)
    assert "persona.tone: Field required" in err.value.problems
    with pytest.raises(ProfileFileError):
        await get_published_profile(db, company.id)
    assert parse_profile(example_data()).company_slug == "google"


# --- one Published version per company (AD-1) ------------------------------------------------


async def test_ad1_second_published_version_for_a_company_fails(db: AsyncSession) -> None:
    company = await _company(db)
    await _add_version(db, company, 1, ProfileStatus.ARCHIVED)
    await _add_version(db, company, 2, ProfileStatus.ARCHIVED)
    await _add_version(db, company, 3, ProfileStatus.DRAFT)
    await _add_version(db, company, 4, ProfileStatus.PUBLISHED)
    other = await _company(db, "amazon")
    await _add_version(db, other, 1, ProfileStatus.PUBLISHED)
    await db.commit()

    with pytest.raises(
        IntegrityError, match=r"UNIQUE constraint failed: company_profiles\.company_id"
    ):
        await _add_version(db, company, 5, ProfileStatus.PUBLISHED)
    await db.rollback()

    company = await _company(db)
    draft = await _add_version(db, company, 5, ProfileStatus.DRAFT)
    await db.commit()
    draft.status = ProfileStatus.PUBLISHED
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


def _profile_values(company_id: uuid.UUID, version: int, status: ProfileStatus) -> dict[str, Any]:
    data = example_data()
    return {
        "id": uuid.uuid4(),
        "company_id": company_id,
        "version": version,
        "status": status,
        "profile_json": data,
        "sources_json": data["sources"],
    }


@pytest.mark.skipif(POSTGRES_URL is None, reason="needs STRONG_TEST_POSTGRES_URL (migrated)")
def test_ad1_postgres_migration_allows_one_published_version_per_company() -> None:
    """Runs on the migrated Postgres schema, so it checks migration 0003, not create_all."""
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    rows = ProfileRow.__table__
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            company_id = uuid.uuid4()
            conn.execute(
                insert(Company.__table__).values(
                    id=company_id, slug=f"t-{company_id.hex[:12]}", name="Test", active=False
                )
            )
            conn.execute(insert(rows).values(**_profile_values(company_id, 1, ProfileStatus.DRAFT)))
            conn.execute(
                insert(rows).values(**_profile_values(company_id, 2, ProfileStatus.PUBLISHED))
            )
            nested = conn.begin_nested()
            with pytest.raises(IntegrityError, match="uq_company_profiles_one_published"):
                conn.execute(
                    insert(rows).values(**_profile_values(company_id, 3, ProfileStatus.PUBLISHED))
                )
            nested.rollback()

            # Publish order: archive the old version, then publish the new one.
            conn.execute(
                rows.update()
                .where(rows.c.company_id == company_id, rows.c.version == 2)
                .values(status=ProfileStatus.ARCHIVED)
            )
            conn.execute(
                rows.update()
                .where(rows.c.company_id == company_id, rows.c.version == 1)
                .values(status=ProfileStatus.PUBLISHED)
            )
            published = conn.execute(
                rows.select().where(
                    rows.c.company_id == company_id, rows.c.status == ProfileStatus.PUBLISHED
                )
            ).all()
            assert [r.version for r in published] == [1]
            outer.rollback()
    finally:
        engine.dispose()
