"""Parsed inputs: the job posting (IN-2) and the resume (IN-3)."""

from __future__ import annotations

from pydantic import Field

from strong_core.schemas.base import Contract, YearMonth
from strong_core.schemas.enums import Level, RoleFamily


class JobPosting(Contract):
    """Structured data extracted from a job posting. The user confirms or edits it (IN-2)."""

    company_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    role_family: RoleFamily = RoleFamily.OTHER
    level: Level | None = Field(
        default=None, description="Normalized level, if it can be inferred."
    )
    level_label: str | None = Field(
        default=None, description="Level as written in the posting, for example 'L5' or 'Senior'."
    )
    team: str | None = None
    location: str | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    source_url: str | None = None


class ResumeRole(Contract):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    start: YearMonth | None = None
    end: YearMonth | None = Field(default=None, description="None means current role.")
    achievements: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class Education(Contract):
    institution: str = Field(min_length=1)
    degree: str | None = None
    field_of_study: str | None = None
    end: YearMonth | None = None


class Resume(Contract):
    """A parsed resume (IN-3). Contact details are deliberately not part of the contract."""

    summary: str | None = None
    roles: list[ResumeRole] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
