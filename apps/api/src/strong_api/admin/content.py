"""Admin Content (AT-1..AT-5, AD-1): companies, profile versions and company requests.

    GET   /admin/companies                                    AT-1 list with versions and requests
    PATCH /admin/companies/{slug}                             AT-1 turn a company on or off
    GET   /admin/companies/{slug}/profiles                    AT-2 versions of one company
    GET   /admin/companies/{slug}/profiles/diff?a=&b=         AT-2 field diff of two versions
    GET   /admin/companies/{slug}/profiles/{version}          AT-2 the JSON and its sources
    POST  /admin/companies/{slug}/profiles                    AT-3 import a profile as a Draft
    POST  /admin/companies/{slug}/profiles/{version}/transition   AT-4 workflow step
    GET   /admin/company-requests                             AT-5 requests by normalized name
    PUT   /admin/company-requests/{normalized_name}/triage    AT-5 triage state

The profile work calls strong_api.profiles (validation, repository, diff), the same code as
strongctl, so a file that `strongctl profiles validate` accepts is accepted here and the other
way round. Writes follow AA-5/AA-6: `AdminWrite`, a reason, and one audit row in the same
transaction.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin
from strong_api.auth.deps import DbSession
from strong_api.profiles import repository as repo
from strong_api.profiles.diff import (
    DIFF_FIELDS,
    ChangeKind,
    FieldChange,
    diff_profiles,
    group_changes,
)
from strong_api.profiles.validation import (
    ProfileFileError,
    parse_profile,
    parse_profile_text,
    profile_summary,
)
from strong_core.companies import most_requested_uncurated
from strong_core.db.models import Company, CompanyRequest, CompanyRequestTriage
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.profiles import ProfileError, row_profile
from strong_core.schemas import ProfileStatus
from strong_core.schemas.enums import TriageState

REQUEST_GROUP_LIMIT = 500
UPLOAD_NAME = Path("upload.json")

router = APIRouter(prefix="/admin", tags=["admin"])


# --- response and request bodies ------------------------------------------------------------


class AdminCompany(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    active: bool
    published_version: int | None
    latest_version: int | None
    version_count: int
    draft_count: int
    in_review_count: int
    request_users: int = Field(description="Distinct users whose job setup matched the company")


class CompanyActiveIn(ActionIn):
    active: bool


class ProfileVersion(BaseModel):
    version: int
    status: ProfileStatus
    imported_at: datetime
    published_at: datetime | None
    reviewed_by: str | None
    source_count: int


class CompanyProfiles(BaseModel):
    company: AdminCompany
    versions: list[ProfileVersion]


class ProfileVersionDetail(ProfileVersion):
    profile: dict[str, Any]
    sources: list[Any]
    problems: list[str] = Field(
        description="Empty when the stored JSON still matches the CompanyProfile schema"
    )


class DiffChange(BaseModel):
    path: str
    kind: ChangeKind
    old: Any = None
    new: Any = None


class DiffField(BaseModel):
    field: str
    changes: list[DiffChange]


class ProfileDiff(BaseModel):
    a: int | None = Field(description="The old version. None means no old version")
    b: int
    total: int
    fields: list[DiffField] = Field(description="Every top-level field, changed or not")


class ProfileImportIn(ActionIn):
    """The file text (from a file picker or pasted) or the parsed JSON. Exactly one of them."""

    profile_text: str | None = Field(default=None, max_length=2_000_000)
    profile: dict[str, Any] | None = None
    create_company: bool = Field(
        default=False, description="Add the company (inactive) when the slug is new"
    )
    force: bool = Field(default=False, description="Store it even if nothing changed")

    @model_validator(mode="after")
    def _one_source(self) -> ProfileImportIn:
        if (self.profile_text is None) == (self.profile is None):
            raise ValueError("send exactly one of profile_text and profile")
        return self


class ProfileImportOut(BaseModel):
    company: AdminCompany
    version: ProfileVersion
    company_created: bool
    file_version: int
    summary: list[str]
    diff: ProfileDiff = Field(description="Against the published version, if there is one")


class TransitionIn(ActionIn):
    to: Literal["draft", "in_review", "published", "archived"]


class TransitionOut(BaseModel):
    version: ProfileVersion
    from_status: ProfileStatus
    archived_version: int | None = Field(
        description="On publish: the version published before, now archived"
    )


class TriageInfo(BaseModel):
    state: TriageState
    company_id: uuid.UUID | None
    company_slug: str | None
    note: str | None
    updated_by: str | None
    updated_at: datetime | None


class CompanyRequestGroup(BaseModel):
    normalized_name: str
    names: list[str] = Field(description="The names users typed, most common first")
    users: int
    requests: int
    first_requested: datetime
    last_requested: datetime
    source_hosts: list[str]
    triage: TriageInfo


class TriageIn(ActionIn):
    state: TriageState
    company_id: uuid.UUID | None = Field(default=None, description="Required when state is added")
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _company_only_when_added(self) -> TriageIn:
        if self.state is TriageState.ADDED and self.company_id is None:
            raise ValueError("company_id is required when state is added")
        if self.state is not TriageState.ADDED and self.company_id is not None:
            raise ValueError("company_id is only set when state is added")
        return self


# --- helpers --------------------------------------------------------------------------------


def _error(code: int, kind: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(code, {"code": kind, "message": message, **extra})


def _version(row: ProfileRow) -> ProfileVersion:
    return ProfileVersion(
        version=row.version,
        status=row.status,
        imported_at=row.imported_at,
        published_at=row.published_at,
        reviewed_by=row.reviewed_by,
        source_count=len(row.sources_json or []),
    )


def _diff(a: int | None, b: int, changes: list[FieldChange]) -> ProfileDiff:
    return ProfileDiff(
        a=a,
        b=b,
        total=len(changes),
        fields=[
            DiffField(
                field=name,
                changes=[DiffChange(path=c.path, kind=c.kind, old=c.old, new=c.new) for c in mine],
            )
            for name, mine in group_changes(changes, DIFF_FIELDS)
        ],
    )


async def _request_users(db: AsyncSession) -> dict[uuid.UUID, int]:
    users = func.count(func.distinct(CompanyRequest.user_id))
    rows = await db.execute(
        select(CompanyRequest.matched_company_id, users)
        .where(CompanyRequest.matched_company_id.is_not(None))
        .group_by(CompanyRequest.matched_company_id)
    )
    return {company_id: int(count) for company_id, count in rows if company_id is not None}


def _company_out(summary: repo.CompanySummary, request_users: dict[uuid.UUID, int]) -> AdminCompany:
    statuses = list(summary.statuses.values())
    return AdminCompany(
        id=summary.id,
        slug=summary.slug,
        name=summary.name,
        active=summary.active,
        published_version=summary.published_version,
        latest_version=summary.latest_version,
        version_count=summary.version_count,
        draft_count=statuses.count(ProfileStatus.DRAFT),
        in_review_count=statuses.count(ProfileStatus.IN_REVIEW),
        request_users=request_users.get(summary.id, 0),
    )


async def _companies(db: AsyncSession) -> list[AdminCompany]:
    request_users = await _request_users(db)
    return [_company_out(s, request_users) for s in await repo.list_companies(db)]


async def _company(db: AsyncSession, slug: str) -> AdminCompany:
    for company in await _companies(db):
        if company.slug == slug:
            return company
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")


async def _require_company(db: AsyncSession, slug: str) -> Company:
    company = await repo.get_company(db, slug)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company


async def _require_version(db: AsyncSession, company: Company, version: int) -> ProfileRow:
    try:
        return await repo.require_version(db, company, version)
    except ProfileError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# --- AT-1 companies -------------------------------------------------------------------------


@router.get("/companies", response_model=list[AdminCompany])
async def list_companies(_admin: Admin, db: DbSession) -> list[AdminCompany]:
    """AT-1: every company with its active flag, versions and request count."""
    return await _companies(db)


@router.patch("/companies/{slug}", response_model=AdminCompany)
async def set_company_active(
    slug: str, body: CompanyActiveIn, admin: AdminWrite, db: DbSession
) -> AdminCompany:
    """AT-1: turn a company on or off. Company matching (IN-5) only uses active companies."""
    company = await _require_company(db, slug)
    before = company.active
    company.active = body.active
    audit_action(
        db,
        admin,
        "company.set_active",
        f"company:{slug}",
        reason=body.reason,
        before={"active": before},
        after={"active": body.active},
    )
    await db.commit()
    return await _company(db, slug)


# --- AT-2 versions, JSON, diff --------------------------------------------------------------


@router.get("/companies/{slug}/profiles", response_model=CompanyProfiles)
async def list_profile_versions(slug: str, _admin: Admin, db: DbSession) -> CompanyProfiles:
    """AT-2: the stored versions of one company, oldest first."""
    company = await _require_company(db, slug)
    rows = await repo.list_versions(db, company.id)
    return CompanyProfiles(company=await _company(db, slug), versions=[_version(r) for r in rows])


@router.get("/companies/{slug}/profiles/diff", response_model=ProfileDiff)
async def diff_versions(
    slug: str,
    _admin: Admin,
    db: DbSession,
    a: int = Query(description="Old version"),
    b: int = Query(description="New version"),
) -> ProfileDiff:
    """AT-2: what changed from version a to version b (profiles/diff.py, meta ignored)."""
    company = await _require_company(db, slug)
    old = await _require_version(db, company, a)
    new = await _require_version(db, company, b)
    return _diff(a, b, diff_profiles(old.profile_json, new.profile_json))


@router.get("/companies/{slug}/profiles/{version}", response_model=ProfileVersionDetail)
async def get_profile_version(
    slug: str, version: int, _admin: Admin, db: DbSession
) -> ProfileVersionDetail:
    """AT-2: one version's stored JSON and its sources."""
    company = await _require_company(db, slug)
    row = await _require_version(db, company, version)
    try:
        row_profile(row)
        problems: list[str] = []
    except ProfileFileError as exc:
        problems = exc.problems
    return ProfileVersionDetail(
        **_version(row).model_dump(),
        profile=row.profile_json,
        sources=row.sources_json or [],
        problems=problems,
    )


# --- AT-3 import ----------------------------------------------------------------------------


@router.post(
    "/companies/{slug}/profiles",
    response_model=ProfileImportOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "The company is new and create_company is off"},
        409: {"description": "Same content as the latest version (detail.code 'unchanged')"},
        422: {"description": "detail.code 'invalid_profile' with detail.problems, or a bad body"},
    },
)
async def import_profile(
    slug: str, body: ProfileImportIn, admin: AdminWrite, db: DbSession
) -> ProfileImportOut:
    """AT-3: validate a profile like `strongctl profiles validate` and store it as a Draft.

    The slug in the URL must match the file's company_slug. With create_company, a new slug adds
    the company, inactive, as `strongctl profiles import --create-company` does."""
    try:
        if body.profile_text is not None:
            profile = parse_profile_text(body.profile_text, UPLOAD_NAME)
        else:
            profile = parse_profile(body.profile, UPLOAD_NAME)
    except ProfileFileError as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_profile",
            "The profile does not match the company profile schema.",
            problems=exc.problems,
        ) from exc
    if profile.company_slug != slug:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "slug_mismatch",
            f"The file is for '{profile.company_slug}', not '{slug}'.",
            problems=[f"company_slug: '{profile.company_slug}' does not match '{slug}'"],
        )
    if await repo.get_company(db, slug) is None and not body.create_company:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "unknown_company",
            f"'{slug}' is not a company yet. Tick 'Add the company' to add it (inactive).",
        )
    try:
        result = await repo.import_profile(
            db,
            profile,
            actor=admin.email,
            create_company=body.create_company,
            force=body.force,
            audit=False,
        )
    except ProfileError as exc:
        raise _error(
            status.HTTP_409_CONFLICT, "unchanged", str(exc).replace("--force", "force")
        ) from exc

    audit_action(
        db,
        admin,
        "profile.import",
        f"company_profile:{slug}:v{result.version}",
        reason=body.reason,
        before={"published_version": result.published_version},
        after={"version": result.version, "status": ProfileStatus.DRAFT.value},
        details={
            "changes": len(result.changes),
            "file_version": result.file_version,
            "company_created": result.company_created,
        },
    )
    await db.commit()
    return ProfileImportOut(
        company=await _company(db, slug),
        version=_version(result.row),
        company_created=result.company_created,
        file_version=result.file_version,
        summary=profile_summary(profile),
        diff=_diff(result.published_version, result.version, result.changes),
    )


# --- AT-4 workflow --------------------------------------------------------------------------


@router.post(
    "/companies/{slug}/profiles/{version}/transition",
    response_model=TransitionOut,
    responses={409: {"description": "The workflow does not allow it (detail.code)"}},
)
async def transition_profile(
    slug: str, version: int, body: TransitionIn, admin: AdminWrite, db: DbSession
) -> TransitionOut:
    """AT-4: draft -> in_review -> published -> archived, in_review -> draft, and archived ->
    published (rollback). Publishing records reviewed_by and archives the version published
    before, in one transaction."""
    company = await _require_company(db, slug)
    await _require_version(db, company, version)
    to = ProfileStatus(body.to)
    try:
        result = await repo.transition_profile(db, slug, version, to, actor=admin.email)
    except repo.TransitionError as exc:
        raise _error(status.HTTP_409_CONFLICT, "transition_not_allowed", str(exc)) from exc
    except (ProfileError, ProfileFileError) as exc:
        raise _error(status.HTTP_409_CONFLICT, "invalid_stored_profile", str(exc)) from exc

    audit_action(
        db,
        admin,
        f"profile.{to.value}",
        f"company_profile:{slug}:v{version}",
        reason=body.reason,
        before={"status": result.from_status.value},
        after={"status": to.value, "reviewed_by": result.row.reviewed_by},
        details={"archived_version": result.previous_version},
    )
    await db.commit()
    return TransitionOut(
        version=_version(result.row),
        from_status=result.from_status,
        archived_version=result.previous_version,
    )


# --- AT-5 company requests ------------------------------------------------------------------


def _triage(row: CompanyRequestTriage | None, slugs: dict[uuid.UUID, str]) -> TriageInfo:
    if row is None:
        return TriageInfo(
            state=TriageState.NEW,
            company_id=None,
            company_slug=None,
            note=None,
            updated_by=None,
            updated_at=None,
        )
    return TriageInfo(
        state=row.state,
        company_id=row.company_id,
        company_slug=slugs.get(row.company_id) if row.company_id else None,
        note=row.note,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _request_groups(db: AsyncSession, only: str | None = None) -> list[CompanyRequestGroup]:
    """Unmatched requests by normalized name, most distinct users first. The order and the user
    counts come from strong_core.companies.most_requested_uncurated (the research backlog)."""
    if only is None:
        ranked = await most_requested_uncurated(db, limit=REQUEST_GROUP_LIMIT)
    else:
        users = await db.scalar(
            select(func.count(func.distinct(CompanyRequest.user_id))).where(
                CompanyRequest.matched_company_id.is_(None),
                CompanyRequest.normalized_name == only,
            )
        )
        ranked = [(only, int(users))] if users else []
    names = [name for name, _ in ranked]
    if not names:
        return []
    unmatched = (
        CompanyRequest.matched_company_id.is_(None),
        CompanyRequest.normalized_name.in_(names),
    )
    stats = {
        name: (int(count), first, last)
        for name, count, first, last in (
            await db.execute(
                select(
                    CompanyRequest.normalized_name,
                    func.count(),
                    func.min(CompanyRequest.created_at),
                    func.max(CompanyRequest.created_at),
                )
                .where(*unmatched)
                .group_by(CompanyRequest.normalized_name)
            )
        )
    }
    typed: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for name, typed_name, count in await db.execute(
        select(CompanyRequest.normalized_name, CompanyRequest.company_name, func.count())
        .where(*unmatched)
        .group_by(CompanyRequest.normalized_name, CompanyRequest.company_name)
    ):
        typed[name].append((-int(count), typed_name))
    hosts: dict[str, list[str]] = defaultdict(list)
    for name, host in await db.execute(
        select(CompanyRequest.normalized_name, CompanyRequest.source_host)
        .where(*unmatched, CompanyRequest.source_host.is_not(None))
        .distinct()
    ):
        if host:
            hosts[name].append(host)
    triage = {
        row.normalized_name: row
        for row in await db.scalars(
            select(CompanyRequestTriage).where(CompanyRequestTriage.normalized_name.in_(names))
        )
    }
    slugs = {c.id: c.slug for c in await db.scalars(select(Company))}

    out = []
    for name, users in ranked:
        count, first, last = stats[name]
        out.append(
            CompanyRequestGroup(
                normalized_name=name,
                names=[n for _, n in sorted(typed[name])],
                users=users,
                requests=count,
                first_requested=_aware(first),
                last_requested=_aware(last),
                source_hosts=sorted(hosts[name]),
                triage=_triage(triage.get(name), slugs),
            )
        )
    return out


@router.get("/company-requests", response_model=list[CompanyRequestGroup])
async def list_company_requests(
    _admin: Admin, db: DbSession, state: TriageState | None = None
) -> list[CompanyRequestGroup]:
    """AT-5: names users asked for that are not curated, grouped by normalized name. Triage
    state 'new' when nobody has triaged the name yet."""
    groups = await _request_groups(db)
    return [g for g in groups if state is None or g.triage.state is state]


@router.put("/company-requests/{normalized_name}/triage", response_model=CompanyRequestGroup)
async def set_triage(
    normalized_name: str, body: TriageIn, admin: AdminWrite, db: DbSession
) -> CompanyRequestGroup:
    """AT-5: set the triage state of a requested name. company_requests rows are not edited."""
    exists = await db.scalar(
        select(CompanyRequest.id)
        .where(
            CompanyRequest.normalized_name == normalized_name,
            CompanyRequest.matched_company_id.is_(None),
        )
        .limit(1)
    )
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No unmatched requests with this name")
    if body.company_id is not None and await db.get(Company, body.company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")

    row = await db.get(CompanyRequestTriage, normalized_name)
    before = (
        {
            "state": row.state.value,
            "company_id": str(row.company_id) if row.company_id else None,
            "note": row.note,
        }
        if row
        else {"state": TriageState.NEW.value, "company_id": None, "note": None}
    )
    if row is None:
        row = CompanyRequestTriage(normalized_name=normalized_name, updated_by=admin.email)
        db.add(row)
    row.state = body.state
    row.company_id = body.company_id
    row.note = body.note
    row.updated_by = admin.email
    row.updated_at = datetime.now(UTC)
    audit_action(
        db,
        admin,
        "company_request.triage",
        f"company_request:{normalized_name}",
        reason=body.reason,
        before=before,
        after={
            "state": body.state.value,
            "company_id": str(body.company_id) if body.company_id else None,
            "note": body.note,
        },
    )
    await db.commit()
    return (await _request_groups(db, only=normalized_name))[0]
