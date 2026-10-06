"""Company name key and company request log (IN-5, spec: Companies outside the 20).

This module is the one place that turns a company name into a matching key. Company matching
in apps/worker/inputs and the request report both use it, so their keys always agree.
"""

from __future__ import annotations

import re
import unicodedata
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import CompanyRequest

NAME_MAX = 200

# Words removed from the end of a name: "Stripe, Inc." and "Stripe" give the same key.
_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "plc",
        "gmbh",
        "ag",
        "sa",
        "technologies",
        "technology",
        "platforms",
        "labs",
        "group",
        "holdings",
        "the",
    }
)
_PAREN = re.compile(r"\([^)]*\)")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_company_name(name: str) -> str:
    """Lowercase ASCII words without legal suffixes or text in brackets.

    'The Stripe Company (US)' gives 'stripe'. 'Société Générale' gives 'societe generale'.
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = _NON_WORD.sub(" ", _PAREN.sub(" ", text)).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


async def record_company_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    company_name: str,
    matched_company_id: uuid.UUID | None,
    job_target_id: uuid.UUID | None = None,
    source_host: str | None = None,
) -> CompanyRequest:
    """Log one company name entered at job setup, matched or not. The caller commits."""
    row = CompanyRequest(
        org_id=org_id,
        user_id=user_id,
        job_target_id=job_target_id,
        company_name=company_name.strip()[:NAME_MAX],
        normalized_name=normalize_company_name(company_name)[:NAME_MAX],
        matched_company_id=matched_company_id,
        source_host=source_host[:NAME_MAX] if source_host else None,
    )
    db.add(row)
    return row


async def most_requested_uncurated(db: AsyncSession, limit: int = 20) -> list[tuple[str, int]]:
    """Normalized names of companies outside the curated list, most requested first.

    Counts distinct users, so one user who enters the same company twice counts once.
    """
    users = func.count(func.distinct(CompanyRequest.user_id))
    stmt = (
        select(CompanyRequest.normalized_name, users)
        .where(CompanyRequest.matched_company_id.is_(None))
        .where(CompanyRequest.normalized_name != "")
        .group_by(CompanyRequest.normalized_name)
        .order_by(users.desc(), CompanyRequest.normalized_name)
        .limit(limit)
    )
    return [(name, int(count)) for name, count in (await db.execute(stmt)).all()]
