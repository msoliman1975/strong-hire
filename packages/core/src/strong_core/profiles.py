"""Company profile lookups for the interviewer, planner and scorer (AD-1, IV-5, FB-1, IN-5).

This is the read side. The write side (file import, diff, publish, the strongctl command line)
is in apps/api `strong_api.profiles` and imports these lookups from here.

A session works from a ResolvedProfile: the company's Published profile, or generic mode.
Generic mode (spec, 'Companies outside the 20'): a default tech-industry persona, equal
competency weights, and no company values. It has no version number, so sessions store NULL
in profile_version.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import Company, InterviewSession, JobTarget
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.schemas import (
    CompanyProfile,
    Competency,
    PersonaNotes,
    ProfileStatus,
    ValuesFramework,
)

__all__ = [
    "DEFAULT_WEIGHT",
    "GENERIC_PERSONA",
    "ProfileError",
    "ProfileFileError",
    "ResolvedProfile",
    "field_path",
    "format_validation_error",
    "generic_profile",
    "get_profile_version",
    "get_published_profile",
    "get_published_row",
    "parse_profile",
    "profile_for_session",
    "resolve_profile",
    "row_profile",
    "use_profile_for_session",
]


# --- errors and parsing ----------------------------------------------------------------------


class ProfileError(Exception):
    """A profile action cannot run. The message says why and what to do."""


class ProfileFileError(Exception):
    """The file is missing, is not JSON, or does not match the CompanyProfile schema."""

    def __init__(self, path: Path, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        super().__init__(f"{path}: " + "; ".join(problems))


def field_path(loc: tuple[int | str, ...]) -> str:
    """('a', 'b', 0, 'c') -> 'a.b[0].c'. An empty location means the whole profile."""
    out = ""
    if loc and loc[-1] == "[key]":  # pydantic marks a bad dict key this way
        return f"{field_path(loc[:-1])} (key)"
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "(profile)"


def format_validation_error(error: ValidationError) -> list[str]:
    problems = []
    for item in error.errors(include_url=False):
        message = str(item["msg"]).removeprefix("Value error, ")
        if item["type"] == "extra_forbidden":
            message = "unknown field (check the spelling, or remove it)"
        problems.append(f"{field_path(tuple(item['loc']))}: {message}")
    return problems


def parse_profile(data: Any, path: Path | None = None) -> CompanyProfile:
    """Validate profile data. Raises ProfileFileError that names each bad field."""
    try:
        return CompanyProfile.model_validate(data)
    except ValidationError as exc:
        raise ProfileFileError(path or Path("<data>"), format_validation_error(exc)) from exc


def row_profile(row: ProfileRow) -> CompanyProfile:
    """The stored profile as the contract. Raises ProfileFileError if it no longer validates."""
    return parse_profile(row.profile_json)


# --- the resolved profile --------------------------------------------------------------------

GENERIC_PERSONA = PersonaNotes(
    tone="Professional and friendly, like a typical tech company interviewer",
    pace="Moderate. Gives the candidate time to think before follow-up questions",
    pushback_style="Asks one or two follow-up questions for specifics, numbers and own role",
    closing_style="Leaves time for the candidate's questions, then explains next steps",
)

DEFAULT_WEIGHT = 1.0


def _equal_weights() -> dict[Competency, float]:
    return dict.fromkeys(Competency, DEFAULT_WEIGHT)


@dataclass(frozen=True)
class ResolvedProfile:
    """What a session uses. `version` is None in generic mode."""

    persona: PersonaNotes
    scoring_weights: dict[Competency, float] = field(default_factory=_equal_weights)
    company_id: uuid.UUID | None = None
    company_slug: str | None = None
    company_name: str | None = None
    version: int | None = None
    profile: CompanyProfile | None = None

    @property
    def generic(self) -> bool:
        return self.profile is None

    @property
    def values_framework(self) -> ValuesFramework | None:
        return self.profile.values_framework if self.profile else None

    @property
    def values_share(self) -> float:
        """Share of the hire signal from company value scores. 0 in generic mode (no values)."""
        return self.profile.values_share if self.profile else 0.0

    @property
    def value_weights(self) -> dict[str, float]:
        """Principle name to its weight inside the values share. Empty in generic mode."""
        if self.profile is None:
            return {}
        return {p.name: p.weight for p in self.profile.values_framework.principles}

    def weight(self, competency: Competency) -> float:
        """Weight in the hire signal. Competencies the profile leaves out weigh 1.0."""
        return self.scoring_weights.get(competency, DEFAULT_WEIGHT)

    @classmethod
    def from_profile(
        cls, profile: CompanyProfile, *, company_id: uuid.UUID, version: int
    ) -> ResolvedProfile:
        return cls(
            persona=profile.persona,
            scoring_weights={**_equal_weights(), **profile.scoring_weights},
            company_id=company_id,
            company_slug=profile.company_slug,
            company_name=profile.company_name,
            version=version,
            profile=profile,
        )


def generic_profile(
    company_id: uuid.UUID | None = None, company_name: str | None = None
) -> ResolvedProfile:
    """Generic mode. Pass the company when it is known but has no published profile."""
    return ResolvedProfile(
        persona=GENERIC_PERSONA, company_id=company_id, company_name=company_name
    )


# --- lookups ---------------------------------------------------------------------------------


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
