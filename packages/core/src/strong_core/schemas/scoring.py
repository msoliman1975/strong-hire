"""Scorecard (FB-1, FB-2) and progress snapshots (PR-1)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from strong_core.schemas.base import Contract, RubricScore
from strong_core.schemas.enums import Competency, HireSignal


class CompetencyScore(Contract):
    competency: Competency
    score: RubricScore
    justification: str = Field(min_length=1)
    quotes: list[str] = Field(min_length=1, description="Transcript quotes backing the score.")


class ValueScore(Contract):
    """Score for one company value (Principle.name), same 1 to 4 rubric as competencies."""

    value: str = Field(min_length=1)
    score: RubricScore
    justification: str = Field(min_length=1)
    quotes: list[str] = Field(min_length=1, description="Transcript quotes backing the score.")


class QuestionScore(Contract):
    question_ref: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    scores: list[CompetencyScore] = Field(min_length=1)
    value_scores: list[ValueScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    misses: list[str] = Field(default_factory=list)


class Scorecard(Contract):
    hire_signal: HireSignal
    rationale: str = Field(min_length=1, description="3 to 5 sentences, like a debrief summary.")
    competency_scores: list[CompetencyScore] = Field(
        min_length=1, description="Overall score per competency across the session."
    )
    value_scores: list[ValueScore] = Field(
        default_factory=list,
        description="Overall score per company value. Empty in generic mode.",
    )
    per_question: list[QuestionScore] = Field(default_factory=list)
    scorer_model: str = Field(min_length=1, description="Gateway model alias, never a vendor id.")
    rubric_version: str = Field(
        min_length=1, description="Prompt ref, for example 'scorer/rubric.v1'."
    )


class ProgressSnapshot(Contract):
    """One competency score from one Realistic session, for trend charts (PR-1)."""

    job_target_id: UUID
    session_id: UUID
    competency: Competency
    score: float = Field(ge=1, le=4)
    at: datetime
