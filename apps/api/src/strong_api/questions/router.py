"""GET /questions (QB-1 to QB-3): the question bank with filters, for any signed-in user.

The bank is the sample questions of every Published company profile plus the general questions
in questions/general.json. It is small (a few hundred questions), so filtering runs in Python.

Filters:
- company: a company slug, or "general" for general questions only. Without it, every
  company's questions and the general ones.
- interview_type, competency (repeatable, matches any), role_family, level, q (text search in
  the question and its hints).
A question with no role_families or levels fits every job category or level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from strong_api.inputs.deps import Db, Me
from strong_api.questions.schemas import BankCompany, BankQuestion, QuestionList
from strong_core.db.models import Company
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.profiles import ProfileFileError, row_profile
from strong_core.question_bank import load_general_bank
from strong_core.schemas import (
    CompanyProfile,
    Competency,
    Level,
    ProfileStatus,
    RoleFamily,
    StandardType,
)

router = APIRouter(tags=["questions"])

GENERAL = "general"


@dataclass(frozen=True)
class Filters:
    interview_type: StandardType | None
    competencies: frozenset[Competency]
    role_family: RoleFamily | None
    level: Level | None
    text: str

    def match(self, q: BankQuestion) -> bool:
        if self.interview_type is not None and q.interview_type != self.interview_type:
            return False
        if self.competencies and not self.competencies.intersection(q.competencies):
            return False
        if self.role_family and q.role_families and self.role_family not in q.role_families:
            return False
        if self.level is not None and q.levels and self.level not in q.levels:
            return False
        return not self.text or self.text in _haystack(q)


def _haystack(q: BankQuestion) -> str:
    parts = [q.question]
    if q.hints is not None:
        parts += q.hints.looking_for + q.hints.strong_signals + q.hints.watch_outs
    return " ".join(parts).casefold()


async def _published(db: Db) -> list[tuple[Company, CompanyProfile]]:
    rows = await db.execute(
        select(Company, ProfileRow)
        .join(ProfileRow, ProfileRow.company_id == Company.id)
        .where(ProfileRow.status == ProfileStatus.PUBLISHED, Company.active.is_(True))
        .order_by(Company.name)
    )
    out = []
    for company, row in rows:
        try:
            out.append((company, row_profile(row)))
        except ProfileFileError:
            continue  # a stored profile that no longer validates is left out, not a 500
    return out


def _bank_company(company: Company, profile: CompanyProfile) -> BankCompany:
    return BankCompany(
        slug=company.slug, name=company.name, question_count=len(profile.sample_questions)
    )


def company_questions(company: Company, profile: CompanyProfile) -> list[BankQuestion]:
    return [
        BankQuestion(
            id=f"{company.slug}-{n}",
            source="company",
            company_slug=company.slug,
            company_name=company.name,
            interview_type=q.interview_type,
            question=q.question,
            competencies=q.competencies,
            values=q.values,
            role_families=q.role_families,
            levels=q.levels,
            hints=q.hints,
            source_url=q.source_url,
        )
        for n, q in enumerate(profile.sample_questions, start=1)
    ]


def general_questions() -> list[BankQuestion]:
    return [
        BankQuestion(
            id=q.id,
            source="general",
            company_slug=None,
            company_name=None,
            interview_type=q.interview_type,
            question=q.question,
            competencies=q.competencies,
            values=[],
            role_families=q.role_families,
            levels=q.levels,
            hints=q.hints,
            source_url=None,
        )
        for q in load_general_bank().questions
    ]


@router.get("/questions/companies")
async def list_bank_companies(db: Db, me: Me) -> list[BankCompany]:
    """QB-1: companies for the company filter, by name. Only companies with a Published
    profile are listed."""
    return [_bank_company(c, p) for c, p in await _published(db)]


@router.get("/questions")
async def list_questions(
    db: Db,
    me: Me,
    company: str | None = None,
    interview_type: StandardType | None = None,
    competency: Annotated[list[Competency] | None, Query()] = None,
    role_family: RoleFamily | None = None,
    level: Level | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> QuestionList:
    """QB-1 to QB-3. 404 when `company` names a company with no Published profile."""
    filters = Filters(
        interview_type=interview_type,
        competencies=frozenset(competency or ()),
        role_family=role_family,
        level=level,
        text=(q or "").strip().casefold(),
    )
    selected: BankCompany | None = None
    from_companies: list[BankQuestion] = []
    if company != GENERAL:
        published = await _published(db)
        if company is not None:
            published = [(c, p) for c, p in published if c.slug == company]
            if not published:
                raise HTTPException(404, f"No published question bank for company '{company}'.")
            selected = _bank_company(*published[0])
        for c, p in published:
            from_companies += company_questions(c, p)
    return QuestionList(
        company=selected,
        company_questions=[x for x in from_companies if filters.match(x)],
        general_questions=[x for x in general_questions() if filters.match(x)],
    )
