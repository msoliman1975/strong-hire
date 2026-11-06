"""Scrub interview turns before they are kept as content (LT-22, D-13).

First `strong_core.ops.errors.scrub_text` (emails, phone numbers, URL query strings), then what we
know about this user: their profile name (and each part of it) becomes `[name]`, and the company
names in their resumes and job targets become `[company]`. Matching is case-insensitive on word
boundaries, longest first, so "Acme Corporation" goes before "Acme".

Best effort by design: a nickname, a colleague's name or a company the user never listed can
survive. The consent wording says so (docs/llm-tracing/phase2-gates.md).

    scrubber = await Scrubber.for_org(db, org_id)
    record_turn_content(tags, index, "text", reply, answer, scrubber.scrub)
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.ops.errors import scrub_text

MIN_TERM_CHARS = 2
NAME = "[name]"
COMPANY = "[company]"


def _pattern(terms: Iterable[str]) -> re.Pattern[str] | None:
    clean = sorted(
        {t.strip() for t in terms if t and len(t.strip()) >= MIN_TERM_CHARS},
        key=lambda t: (-len(t), t.lower()),
    )
    if not clean:
        return None
    alternatives = "|".join(re.escape(t) for t in clean)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


class Scrubber:
    """Removes one user's known identifiers from text. Never raises from `scrub`."""

    def __init__(self, names: Iterable[str] = (), companies: Iterable[str] = ()) -> None:
        name_list = [n for n in names if n]
        parts = [p for n in name_list for p in n.split()]
        self._names = _pattern([*name_list, *parts])
        self._companies = _pattern(companies)

    def scrub(self, text: str) -> str:
        if not text:
            return text
        out = scrub_text(text)
        # Companies first: a company named after a person ("Johnson Controls") stays a company.
        if self._companies is not None:
            out = self._companies.sub(COMPANY, out)
        if self._names is not None:
            out = self._names.sub(NAME, out)
        return out

    @classmethod
    async def for_org(cls, db: AsyncSession, org_id: uuid.UUID) -> Scrubber:
        """The org's users' profile names and the companies in its resumes and job targets."""
        from strong_core.db.models import JobTarget, Resume, User

        names = [
            n
            for (n,) in (await db.execute(select(User.full_name).where(User.org_id == org_id)))
            if n
        ]
        companies: list[str] = []
        resumes = await db.execute(select(Resume.parsed_json).where(Resume.org_id == org_id))
        for (parsed,) in resumes:
            companies += _resume_companies(parsed)
        targets = await db.execute(select(JobTarget.parsed_json).where(JobTarget.org_id == org_id))
        for (parsed,) in targets:
            if isinstance(parsed, dict) and isinstance(parsed.get("company_name"), str):
                companies.append(parsed["company_name"])
        return cls(names, companies)


def _resume_companies(parsed: Any) -> list[str]:
    if not isinstance(parsed, dict):
        return []
    roles = parsed.get("roles")
    if not isinstance(roles, list):
        return []
    return [
        r["company"] for r in roles if isinstance(r, dict) and isinstance(r.get("company"), str)
    ]


__all__ = ["COMPANY", "NAME", "Scrubber"]
