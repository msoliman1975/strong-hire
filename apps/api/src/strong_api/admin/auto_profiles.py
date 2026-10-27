"""Admin auto-profile queue (AP-3): review the company summaries the auto-profile job builds.

    GET  /admin/auto-profiles?status=pending      counts per status and the rows in one status
    GET  /admin/auto-profiles/{id}                one row: summary, values, process notes, sources
    POST /admin/auto-profiles/{id}/approve        pending → approved
    PUT  /admin/auto-profiles/{id}/summary        edit the summary text (pending or approved)
    POST /admin/auto-profiles/{id}/retire         pending or approved → retired

The worker (AP-1) writes the rows; the brief reads only approved ones (AP-3). Every write follows
AA-5/AA-6: AdminWrite, a reason, and an audit row with the state before and after. A retired row
stays retired.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin
from strong_api.auth.deps import DbSession
from strong_core.db.models import CompanyAutoProfile
from strong_core.schemas import AutoProfileSummary
from strong_core.schemas.enums import AutoProfileStatus

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminAutoProfile(BaseModel):
    id: uuid.UUID
    company_name: str
    normalized_name: str
    source_host: str
    summary: str
    values_mentioned: list[str]
    interview_process_notes: list[str]
    sources: list[str]
    status: AutoProfileStatus
    reviewed_by: str | None
    reviewed_at: datetime | None
    model_profile: str
    prompt_version: str
    created_at: datetime


class AdminAutoProfiles(BaseModel):
    counts: dict[AutoProfileStatus, int] = Field(description="Rows per status; all present")
    profiles: list[AdminAutoProfile] = Field(description="Oldest first, so the queue is FIFO")


class SummaryIn(ActionIn):
    summary: str = Field(min_length=1, max_length=2000, description="AutoProfileSummary.summary")


def _out(row: CompanyAutoProfile) -> AdminAutoProfile:
    data: dict[str, Any] = row.summary_json or {}
    sources = row.sources_json or data.get("sources") or []
    return AdminAutoProfile(
        id=row.id,
        company_name=row.company_name,
        normalized_name=row.normalized_name,
        source_host=row.source_host,
        summary=row.summary,
        values_mentioned=[str(v) for v in data.get("values_mentioned", [])],
        interview_process_notes=[str(v) for v in data.get("interview_process_notes", [])],
        sources=[str(s) for s in sources],
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        model_profile=row.model_profile,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
    )


async def _get(db: DbSession, profile_id: uuid.UUID) -> CompanyAutoProfile:
    row = await db.get(CompanyAutoProfile, profile_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such auto-profile")
    return row


def _state(row: CompanyAutoProfile) -> dict[str, Any]:
    return {"status": row.status.value, "summary": row.summary}


def _reviewed(row: CompanyAutoProfile, email: str) -> None:
    row.reviewed_by = email
    row.reviewed_at = datetime.now(UTC)


@router.get("/auto-profiles")
async def list_auto_profiles(
    _: Admin,
    db: DbSession,
    status_: Annotated[
        AutoProfileStatus | Literal["all"], Query(alias="status", description="Which rows")
    ] = AutoProfileStatus.PENDING,
) -> AdminAutoProfiles:
    """AP-3: the review queue. Pending rows by default, oldest first."""
    counts = dict.fromkeys(AutoProfileStatus, 0)
    grouped = await db.execute(
        select(CompanyAutoProfile.status, func.count()).group_by(CompanyAutoProfile.status)
    )
    for st, n in grouped:
        counts[AutoProfileStatus(st)] = int(n)
    query = select(CompanyAutoProfile).order_by(CompanyAutoProfile.created_at)
    if status_ != "all":
        query = query.where(CompanyAutoProfile.status == status_)
    rows = (await db.scalars(query)).all()
    return AdminAutoProfiles(counts=counts, profiles=[_out(r) for r in rows])


@router.get("/auto-profiles/{profile_id}")
async def get_auto_profile(profile_id: uuid.UUID, _: Admin, db: DbSession) -> AdminAutoProfile:
    return _out(await _get(db, profile_id))


@router.post("/auto-profiles/{profile_id}/approve")
async def approve_auto_profile(
    profile_id: uuid.UUID, body: ActionIn, admin: AdminWrite, db: DbSession
) -> AdminAutoProfile:
    """AP-3: an approved profile may reach a brief."""
    row = await _get(db, profile_id)
    if row.status != AutoProfileStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The profile is {row.status.value}")
    before = _state(row)
    row.status = AutoProfileStatus.APPROVED
    _reviewed(row, admin.email)
    audit_action(
        db,
        admin,
        "auto_profile.approve",
        f"company_auto_profile:{row.id}",
        reason=body.reason,
        before=before,
        after=_state(row),
        details={"company": row.company_name},
    )
    await db.commit()
    return _out(row)


@router.put("/auto-profiles/{profile_id}/summary")
async def edit_auto_profile_summary(
    profile_id: uuid.UUID, body: SummaryIn, admin: AdminWrite, db: DbSession
) -> AdminAutoProfile:
    """AP-3: correct the summary text. The status stays as it is."""
    row = await _get(db, profile_id)
    if row.status == AutoProfileStatus.RETIRED:
        raise HTTPException(status.HTTP_409_CONFLICT, "A retired profile cannot be edited")
    text = body.summary.strip()
    data = {**(row.summary_json or {}), "summary": text}
    try:
        AutoProfileSummary.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid summary: {first['msg']}"
        ) from exc
    before = _state(row)
    row.summary = text
    row.summary_json = data  # a new dict, so the JSON column sees the change
    _reviewed(row, admin.email)
    audit_action(
        db,
        admin,
        "auto_profile.edit",
        f"company_auto_profile:{row.id}",
        reason=body.reason,
        before=before,
        after=_state(row),
        details={"company": row.company_name},
    )
    await db.commit()
    return _out(row)


@router.post("/auto-profiles/{profile_id}/retire")
async def retire_auto_profile(
    profile_id: uuid.UUID, body: ActionIn, admin: AdminWrite, db: DbSession
) -> AdminAutoProfile:
    """AP-3: a retired profile never reaches a brief again."""
    row = await _get(db, profile_id)
    if row.status == AutoProfileStatus.RETIRED:
        raise HTTPException(status.HTTP_409_CONFLICT, "The profile is already retired")
    before = _state(row)
    row.status = AutoProfileStatus.RETIRED
    _reviewed(row, admin.email)
    audit_action(
        db,
        admin,
        "auto_profile.retire",
        f"company_auto_profile:{row.id}",
        reason=body.reason,
        before=before,
        after=_state(row),
        details={"company": row.company_name},
    )
    await db.commit()
    return _out(row)
