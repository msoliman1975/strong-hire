"""The profile the interviewer and scorer work from: a published company profile, or generic mode.

Generic mode (spec, 'Companies outside the 20'): a default tech-industry persona, equal
competency weights, and no company values. It has no version number, so sessions store NULL
in profile_version.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from strong_core.schemas import CompanyProfile, Competency, PersonaNotes, ValuesFramework

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
