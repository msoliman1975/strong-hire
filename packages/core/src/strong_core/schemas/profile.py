"""Company profile contract. Matches the 'Profile structure' table in docs/spec.md.

schemas/company_profile.schema.json is generated from this model (AD-1). Research prompts
produce JSON against that schema, and `strongctl profiles import` validates with this model.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import (
    Competency,
    Confidence,
    InterviewType,
    Level,
    ProfileStatus,
    RoleFamily,
)


class ProfileField(StrEnum):
    """Top-level profile fields that carry sources and a confidence level."""

    VALUES_FRAMEWORK = "values_framework"
    LOOP_STRUCTURE = "loop_structure"
    QUESTION_PATTERNS = "question_patterns"
    BAR_BY_LEVEL = "bar_by_level"
    PERSONA = "persona"
    SCORING_WEIGHTS = "scoring_weights"
    CASE_STYLE = "case_style"


class Principle(Contract):
    """One company value, for example 'Customer Obsession'. The name is its id in briefs and
    scorecards, so keep it stable across profile versions."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_signals: list[str] = Field(
        min_length=1, description="What evidence of this principle sounds like in an answer."
    )
    weight: float = Field(
        default=1.0, gt=0, description="Relative weight of this value inside the values share."
    )


class ValuesFramework(Contract):
    name: str = Field(min_length=1, description="For example 'Leadership Principles'.")
    principles: list[Principle] = Field(min_length=1)


class LoopRound(Contract):
    name: str = Field(min_length=1)
    interview_type: InterviewType | None = Field(
        default=None, description="None for rounds v1 does not simulate, such as live coding."
    )
    duration_min: int | None = Field(default=None, ge=5, le=240)
    interviewer_role: str | None = None
    notes: str | None = None


class LoopStructure(Contract):
    role_family: RoleFamily
    levels: list[str] = Field(default_factory=list, description="Company level names covered.")
    rounds: list[LoopRound] = Field(min_length=1)


class QuestionPattern(Contract):
    """A recurring theme, phrased as a pattern. Never a leaked or NDA-protected question."""

    interview_type: InterviewType
    theme: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    competencies: list[Competency] = Field(default_factory=list)
    values: list[str] = Field(
        default_factory=list, description="Principle names from values_framework this probes."
    )


class LevelBar(Contract):
    level_name: str = Field(min_length=1, description="Company label, for example 'L5' or 'E5'.")
    normalized_level: Level
    role_family: RoleFamily | None = None
    scope_expectation: str = Field(min_length=1)


class PersonaNotes(Contract):
    tone: str = Field(min_length=1)
    pace: str = Field(min_length=1)
    pushback_style: str = Field(min_length=1)
    closing_style: str = Field(min_length=1)


class CaseStyle(Contract):
    """Relative emphasis, each from 0 to 1."""

    product_sense: float = Field(ge=0, le=1)
    estimation: float = Field(ge=0, le=1)
    system_thinking: float = Field(ge=0, le=1)
    notes: str | None = None


class Source(Contract):
    url: str = Field(min_length=1)
    title: str | None = None
    retrieved_at: date
    fields: list[ProfileField] = Field(
        min_length=1, description="Which profile fields this source supports."
    )


class ProfileMeta(Contract):
    version: int = Field(ge=1)
    status: ProfileStatus = ProfileStatus.DRAFT
    reviewed_by: str | None = None
    researched_at: date | None = None
    published_at: datetime | None = None


class CompanyProfile(Contract):
    company_name: str = Field(min_length=1)
    company_slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    meta: ProfileMeta
    values_framework: ValuesFramework
    loop_structure: list[LoopStructure] = Field(min_length=1)
    question_patterns: list[QuestionPattern] = Field(min_length=1)
    bar_by_level: list[LevelBar] = Field(min_length=1)
    persona: PersonaNotes
    scoring_weights: dict[Competency, float] = Field(
        min_length=1,
        description="Relative weight of each competency in the hire signal. Missing means 1.0.",
    )
    values_share: float = Field(
        default=0.25,
        ge=0,
        le=0.5,
        description=(
            "Share of the hire signal that comes from company value scores. The rest comes from "
            "competency scores. P08 owns the hire-signal formula."
        ),
    )
    case_style: CaseStyle
    sources: list[Source] = Field(min_length=1)
    field_confidence: dict[ProfileField, Confidence] = Field(
        description="Confidence per field. Every ProfileField must be present."
    )
    low_confidence_notes: list[str] = Field(
        default_factory=list, description="Fields or claims flagged for reviewer attention."
    )

    @model_validator(mode="after")
    def _check(self) -> CompanyProfile:
        missing = set(ProfileField) - set(self.field_confidence)
        if missing:
            names = ", ".join(sorted(m.value for m in missing))
            raise ValueError(f"field_confidence is missing: {names}")
        bad = [c.value for c, w in self.scoring_weights.items() if w <= 0]
        if bad:
            raise ValueError(f"scoring_weights must be positive: {', '.join(bad)}")
        names = [p.name for p in self.values_framework.principles]
        if len(names) != len(set(names)):
            raise ValueError("values_framework principle names must be unique")
        unknown = sorted({v for q in self.question_patterns for v in q.values} - set(names))
        if unknown:
            raise ValueError(f"question_patterns use unknown values: {', '.join(unknown)}")
        return self

    @property
    def value_names(self) -> list[str]:
        return [p.name for p in self.values_framework.principles]
