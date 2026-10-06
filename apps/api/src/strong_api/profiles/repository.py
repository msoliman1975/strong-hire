"""Company profile storage (AD-1) and lookups for the interviewer and scorer (IV-5, FB-1).

Versions: each import stores the next version number for the company as a Draft. Publishing a
version archives the version that was published before, so one version per company is active.
Old versions stay in the table and remain readable with get_profile_version().
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.profiles.diff import FieldChange, diff_profiles
from strong_api.profiles.resolved import ResolvedProfile, generic_profile
from strong_api.profiles.validation import parse_profile
from strong_core.db.models import AuditLog, Company, InterviewSession, JobTarget
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.schemas import CompanyProfile, ProfileStatus


class ProfileError(Exception):
    """A profile action cannot run. The message says why and what to do."""


@dataclass(frozen=True)
class ImportResult:
    company: Company
    row: ProfileRow
    published_version: int | None
    changes: list[FieldChange]
    file_version: int
    company_created: bool = False

    @property
    def version(self) -> int:
        return self.row.version


@dataclass(frozen=True)
class PublishResult:
    company: Company
    row: ProfileRow
    previous_version: int | None
    already_published: bool = False


@dataclass(frozen=True)
class CompanySummary:
    slug: str
    name: str
    active: bool
    published_version: int | None
    latest_version: int | None
    version_count: int
    statuses: dict[int, ProfileStatus] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(UTC)


def row_profile(row: ProfileRow) -> CompanyProfile:
    """The stored profile as the contract. Raises ProfileFileError if it no longer validates."""
    return parse_profile(row.profile_json)


async def get_company(db: AsyncSession, slug: str) -> Company | None:
    return await db.scalar(select(Company).where(Company.slug == slug))


async def require_company(db: AsyncSession, slug: str) -> Company:
    company = await get_company(db, slug)
    if company is None:
        raise ProfileError(
            f"Company '{slug}' is not in the companies table. Run the seed, check company_slug, "
            "or pass --create-company for a company outside the launch list."
        )
    return company


async def list_versions(db: AsyncSession, company_id: uuid.UUID) -> Sequence[ProfileRow]:
    rows = await db.scalars(
        select(ProfileRow).where(ProfileRow.company_id == company_id).order_by(ProfileRow.version)
    )
    return rows.all()


async def get_profile_version(
    db: AsyncSession, company_id: uuid.UUID, version: int
) -> ProfileRow | None:
    """Any version, in any status. Used to explain old sessions after a refresh."""
    return await db.scalar(
        select(ProfileRow).where(ProfileRow.company_id == company_id, ProfileRow.version == version)
    )


async def get_published_row(db: AsyncSession, company_id: uuid.UUID) -> ProfileRow | None:
    return await db.scalar(
        select(ProfileRow)
        .where(
            ProfileRow.company_id == company_id,
            ProfileRow.status == ProfileStatus.PUBLISHED,
        )
        .order_by(ProfileRow.version.desc())
        .limit(1)
    )


async def get_published_profile(db: AsyncSession, company_id: uuid.UUID) -> ResolvedProfile | None:
    """The active (Published) profile with its version number, or None if there is none."""
    row = await get_published_row(db, company_id)
    if row is None:
        return None
    return ResolvedProfile.from_profile(
        row_profile(row), company_id=company_id, version=row.version
    )


async def resolve_profile(db: AsyncSession, company_id: uuid.UUID | None) -> ResolvedProfile:
    """The published profile for the company, else the generic default profile (IN-5)."""
    if company_id is None:
        return generic_profile()
    published = await get_published_profile(db, company_id)
    if published is not None:
        return published
    company = await db.get(Company, company_id)
    return generic_profile(company_id, company.name if company else None)


async def use_profile_for_session(db: AsyncSession, session: InterviewSession) -> ResolvedProfile:
    """Pick the profile for a new session and record its version on the session.

    Generic mode stores NULL. The caller commits.
    """
    target = await db.get(JobTarget, session.job_target_id)
    resolved = await resolve_profile(db, target.company_id if target else None)
    session.profile_version = resolved.version
    return resolved


async def profile_for_session(db: AsyncSession, session: InterviewSession) -> ResolvedProfile:
    """The exact profile a session used, even if a newer version is published now."""
    target = await db.get(JobTarget, session.job_target_id)
    if session.profile_version is None or target is None or target.company_id is None:
        company_id = target.company_id if target else None
        company = await db.get(Company, company_id) if company_id else None
        return generic_profile(company_id, company.name if company else None)
    row = await get_profile_version(db, target.company_id, session.profile_version)
    if row is None:
        raise ProfileError(
            f"Session {session.id} used profile version {session.profile_version}, "
            "which is not in the database."
        )
    return ResolvedProfile.from_profile(
        row_profile(row), company_id=target.company_id, version=row.version
    )


async def import_profile(
    db: AsyncSession,
    profile: CompanyProfile,
    *,
    actor: str,
    create_company: bool = False,
    force: bool = False,
) -> ImportResult:
    """Store the profile as the next Draft version and diff it against the published version."""
    company = await get_company(db, profile.company_slug)
    created = False
    if company is None:
        if not create_company:
            await require_company(db, profile.company_slug)
        # Not active: company matching (IN-5) only uses active companies.
        company = Company(slug=profile.company_slug, name=profile.company_name, active=False)
        db.add(company)
        await db.flush()
        created = True

    latest = await db.scalar(
        select(ProfileRow)
        .where(ProfileRow.company_id == company.id)
        .order_by(ProfileRow.version.desc())
        .limit(1)
    )
    data = profile.model_dump(mode="json")
    if latest is not None and not force and not diff_profiles(latest.profile_json, data):
        raise ProfileError(
            f"The file has the same content as version {latest.version} of "
            f"'{company.slug}'. Nothing was stored. Pass --force to store it anyway."
        )

    version = (latest.version if latest else 0) + 1
    data["meta"].update(version=version, status=ProfileStatus.DRAFT.value, published_at=None)
    row = ProfileRow(
        company_id=company.id,
        version=version,
        status=ProfileStatus.DRAFT,
        profile_json=data,
        sources_json=data["sources"],
        reviewed_by=profile.meta.reviewed_by,
        imported_at=_now(),
    )
    db.add(row)

    published = await get_published_row(db, company.id)
    changes = diff_profiles(published.profile_json if published else None, data)
    db.add(
        AuditLog(
            actor=actor,
            action="profile.import",
            entity=f"company_profile:{company.slug}:v{version}",
            details_json={"changes": len(changes), "file_version": profile.meta.version},
        )
    )
    await db.flush()
    return ImportResult(
        company=company,
        row=row,
        published_version=published.version if published else None,
        changes=changes,
        file_version=profile.meta.version,
        company_created=created,
    )


async def publish_profile(
    db: AsyncSession, slug: str, version: int, *, reviewer: str
) -> PublishResult:
    """Make `version` the active profile. The previously published version becomes Archived."""
    company = await require_company(db, slug)
    row = await get_profile_version(db, company.id, version)
    if row is None:
        known = [r.version for r in await list_versions(db, company.id)]
        raise ProfileError(
            f"'{slug}' has no version {version}. Stored versions: "
            + (", ".join(map(str, known)) if known else "none")
        )
    row_profile(row)  # refuse to publish a stored profile that no longer validates
    previous = await get_published_row(db, company.id)
    if previous is not None and previous.id == row.id:
        return PublishResult(company, row, version, already_published=True)

    now = _now()
    if previous is not None:
        previous.status = ProfileStatus.ARCHIVED
        previous.profile_json = _with_meta(previous.profile_json, status=ProfileStatus.ARCHIVED)
    row.status = ProfileStatus.PUBLISHED
    row.published_at = now
    row.reviewed_by = reviewer
    row.profile_json = _with_meta(
        row.profile_json,
        status=ProfileStatus.PUBLISHED,
        published_at=now.isoformat(),
        reviewed_by=reviewer,
    )
    db.add(
        AuditLog(
            actor=reviewer,
            action="profile.publish",
            entity=f"company_profile:{slug}:v{version}",
            details_json={"previous_version": previous.version if previous else None},
        )
    )
    await db.flush()
    return PublishResult(company, row, previous.version if previous else None)


def _with_meta(profile_json: dict[str, Any], **meta: Any) -> dict[str, Any]:
    """A copy with meta fields replaced. A new dict, so SQLAlchemy sees the JSON change."""
    values = {k: v.value if isinstance(v, ProfileStatus) else v for k, v in meta.items()}
    return {**profile_json, "meta": {**profile_json.get("meta", {}), **values}}


async def list_companies(db: AsyncSession) -> list[CompanySummary]:
    companies = (await db.scalars(select(Company).order_by(Company.name))).all()
    rows = (
        await db.execute(
            select(ProfileRow.company_id, ProfileRow.version, ProfileRow.status).order_by(
                ProfileRow.version
            )
        )
    ).all()
    by_company: dict[uuid.UUID, dict[int, ProfileStatus]] = {}
    for company_id, version, status in rows:
        by_company.setdefault(company_id, {})[version] = status
    out = []
    for company in companies:
        statuses = by_company.get(company.id, {})
        published = [v for v, s in statuses.items() if s is ProfileStatus.PUBLISHED]
        out.append(
            CompanySummary(
                slug=company.slug,
                name=company.name,
                active=company.active,
                published_version=max(published) if published else None,
                latest_version=max(statuses) if statuses else None,
                version_count=len(statuses),
                statuses=statuses,
            )
        )
    return out
