"""Response bodies of GET /questions and GET /questions/companies (QB-1 to QB-3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import Competency, InterviewType, Level, QuestionHints, RoleFamily

QuestionSource = Literal["company", "general"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BankCompany(_Out):
    slug: str
    name: str
    question_count: int = Field(description="Company questions in its Published profile.")


class BankQuestion(_Out):
    """QB-2: one question with its tags and key hints."""

    id: str = Field(description="'<company slug>-<n>' for a company question, else the bank id.")
    source: QuestionSource
    company_slug: str | None = Field(description="None for general questions.")
    company_name: str | None
    interview_type: InterviewType
    question: str
    competencies: list[Competency]
    values: list[str] = Field(description="Company values the question probes.")
    role_families: list[RoleFamily] = Field(description="Empty means every job category.")
    levels: list[Level] = Field(description="Empty means every level.")
    hints: QuestionHints | None = Field(description="None until hints are written for it.")
    source_url: str | None = Field(description="Public page that reports a company question.")


class QuestionList(_Out):
    """QB-3: with a company selected, company_questions hold its questions and
    general_questions the general ones that match the other filters ("Also common")."""

    company: BankCompany | None = Field(description="The selected company, if any.")
    company_questions: list[BankQuestion]
    general_questions: list[BankQuestion]
