"""Practice readiness (RD-1). Always shown as a practice estimate, never a prediction (RD-3)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract, RubricScore
from strong_core.schemas.enums import Competency, ReadinessStatus


class SkillReadiness(Contract):
    """RD-1: readiness for one skill, from Realistic sessions only."""

    competency: Competency
    status: ReadinessStatus
    score: int | None = Field(
        ge=0, le=100, description="0 to 100. Null exactly when status is not_enough_data."
    )
    sessions_counted: int = Field(ge=0, description="Realistic sessions that scored this skill.")

    @model_validator(mode="after")
    def _score_matches_status(self) -> SkillReadiness:
        if (self.status == ReadinessStatus.NOT_ENOUGH_DATA) != (self.score is None):
            raise ValueError("score is null exactly when status is not_enough_data")
        return self


class Readiness(Contract):
    """RD-1: practice readiness per skill for one job target's interview."""

    job_target_id: UUID
    kind: Literal["practice_estimate"] = Field(
        default="practice_estimate", description="RD-3: every screen labels it this way."
    )
    as_of: date
    skills: list[SkillReadiness] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_item_per_skill(self) -> Readiness:
        skills = [s.competency for s in self.skills]
        if len(skills) != len(set(skills)):
            raise ValueError("skills must have one entry per competency")
        return self


READINESS_GOAL = 75
"""RH-2: the readiness goal per interview."""


class CompetencyReadiness(Contract):
    """RH-2: the most recent rubric score of one competency over the last three Realistic takes."""

    competency: Competency
    score: RubricScore | None = Field(description="1 to 4. Null when not scored yet.")


class InterviewReadiness(Contract):
    """RH-2: readiness for one interview (role x resume x type), from Realistic takes only.

    score = round((mean - 1) / 3 * 100) over the competencies scored so far; null with no
    Realistic take.
    """

    interview_id: UUID
    kind: Literal["practice_estimate"] = Field(
        default="practice_estimate", description="RD-3: every screen labels it this way."
    )
    score: int | None = Field(ge=0, le=100, description="0 to 100. Null with no Realistic take.")
    goal: int = Field(default=READINESS_GOAL, ge=0, le=100)
    competencies: list[CompetencyReadiness] = Field(default_factory=list)
    change: int | None = Field(
        default=None, description="Change since the previous take. Null when there is none."
    )
    takes_counted: int = Field(default=0, ge=0, le=3, description="Realistic takes used.")

    @model_validator(mode="after")
    def _check(self) -> InterviewReadiness:
        names = [c.competency for c in self.competencies]
        if len(names) != len(set(names)):
            raise ValueError("competencies must have one entry per competency")
        if self.takes_counted == 0 and self.score is not None:
            raise ValueError("score is null when no Realistic take counted")
        return self
