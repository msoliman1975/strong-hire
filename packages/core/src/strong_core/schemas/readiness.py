"""Practice readiness (RD-1). Always shown as a practice estimate, never a prediction (RD-3)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
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
