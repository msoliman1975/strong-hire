"""Company name helpers shared by job setup (IN-5) and reporting on company requests."""

from __future__ import annotations

import re
import unicodedata
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import CompanyRequest

_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|llc|ltd|limited|plc|gmbh|ag|sa|"
    r"technologies|technology|labs)\b\.?",
)
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_company_name(name: str) -> str:
    """'Stripe, Inc.' and 'stripe' give the same key: 'stripe'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = text.replace("&", " and ")
    text = _SUFFIXES.sub(" ", text)
    return _NON_WORD.sub(" ", text).strip()


async def record_company_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    company_name: str,
    matched_company_id: uuid.UUID | None,
    job_target_id: uuid.UUID | None = None,
) -> CompanyRequest:
    """Log a company name entered at job setup. The caller commits."""
    row = CompanyRequest(
        org_id=org_id,
        user_id=user_id,
        job_target_id=job_target_id,
        company_name=company_name.strip()[:200],
        normalized_name=normalize_company_name(company_name)[:200],
        matched_company_id=matched_company_id,
    )
    db.add(row)
    return row


async def most_requested_uncurated(db: AsyncSession, limit: int = 20) -> list[tuple[str, int]]:
    """Normalized names of companies outside the curated list, most requested first.
    Counts distinct users, so one user adding the same company twice counts once."""
    users = func.count(func.distinct(CompanyRequest.user_id))
    stmt = (
        select(CompanyRequest.normalized_name, users)
        .where(CompanyRequest.matched_company_id.is_(None))
        .group_by(CompanyRequest.normalized_name)
        .order_by(users.desc(), CompanyRequest.normalized_name)
        .limit(limit)
    )
    return [(name, int(count)) for name, count in (await db.execute(stmt)).all()]
