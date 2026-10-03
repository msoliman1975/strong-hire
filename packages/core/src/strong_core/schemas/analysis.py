"""Gap analysis (GA-1 to GA-3)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import Competency, Difficulty, InterviewType, Severity


class RequirementKind(StrEnum):
    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"


class RequirementMatch(Contract):
    requirement: str = Field(min_length=1)
    kind: RequirementKind
    score: int = Field(ge=0, le=100)
    evidence: str | None = Field(default=None, description="Resume text that supports the score.")


class CompetencyMatch(Contract):
    competency: Competency
    score: int = Field(ge=0, le=100)
    notes: str | None = None


class Strength(Contract):
    summary: str = Field(min_length=1)
    evidence: str = Field(min_length=1, description="Resume evidence (GA-2).")


class Gap(Contract):
    summary: str = Field(min_length=1)
    severity: Severity
    related_requirement: str | None = None


class PlannedSession(Contract):
    """One recommended practice session (GA-3)."""

    priority: int = Field(ge=1, description="1 is the first session to run.")
    interview_type: InterviewType
    difficulty: Difficulty = Difficulty.REALISTIC
    focus_topics: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class GapAnalysis(Contract):
    match_score: int = Field(ge=0, le=100, description="GA-1.")
    requirement_breakdown: list[RequirementMatch] = Field(default_factory=list)
    competency_breakdown: list[CompetencyMatch] = Field(default_factory=list)
    strengths: list[Strength] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    probe_areas: list[str] = Field(default_factory=list)
    session_plan: list[PlannedSession] = Field(min_length=1)
