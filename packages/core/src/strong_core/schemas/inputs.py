"""Parsed inputs: the job posting (IN-2) and the resume (IN-3), and the input check (IN-6, IN-7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from pydantic import Field

from strong_core.schemas.base import Contract, YearMonth
from strong_core.schemas.enums import DocumentKind, Level, RoleFamily


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


class InputCheck(Contract):
    """Is the text the kind of document the user gave it as (IN-6 job description, IN-7 CV)?

    The worker runs this check before the extraction. When `matches` is false, it refuses the
    input and shows the user a fixed sentence for `looks_like` with the short `reason`.
    """

    matches: bool
    looks_like: DocumentKind
    reason: str = Field(
        default="", max_length=200, description="One short sentence on what the text is."
    )


ACCEPTED_ISSUE_KEY_MAX: Final = 200
ACCEPTED_ISSUES_MAX: Final = 100


class AcceptedIssue(Contract):
    """A CV check issue the user marked as fine, stored in resumes.accepted_issues.

    The web computes `key` from the issue, for example
    'overlap:2019-06:2022-03:northwind:lumen-pay'. Core treats it as opaque.
    """

    key: str = Field(min_length=1, max_length=ACCEPTED_ISSUE_KEY_MAX)
    accepted_at: datetime


AcceptedIssues = Annotated[list[AcceptedIssue], Field(max_length=ACCEPTED_ISSUES_MAX)]
"""The accepted_issues list of one CV, at most ACCEPTED_ISSUES_MAX entries."""
