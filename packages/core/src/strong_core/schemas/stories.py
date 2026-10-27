"""Story library (ST-1) and story fit (ST-5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import (
    Competency,
    StoryFitStrength,
    StoryPart,
    StorySource,
    StoryStatus,
)

STORY_TITLE_MAX_CHARS = 200


class StoryNote(Contract):
    """ST-6: a fix note sent to the story from a debrief answer that used it."""

    text: str = Field(min_length=1)
    session_id: UUID | None = Field(default=None, description="The debrief's session.")
    question_ref: str | None = Field(default=None, description="QuestionScore.question_ref.")
    at: datetime


class Story(Contract):
    """ST-1: one story in the user's library. The stories table holds org_id and user_id."""

    id: UUID
    title: str = Field(min_length=1, max_length=STORY_TITLE_MAX_CHARS)
    context: str | None = None
    stakes: str | None = None
    action: str | None = None
    result: str | None = None
    reflection: str | None = None
    skills: list[Competency] = Field(default_factory=list, description="Skill tags.")
    status: StoryStatus = StoryStatus.DRAFT
    source: StorySource
    source_session_id: UUID | None = Field(
        default=None, description="ST-2: the session of the debrief answer it came from."
    )
    source_question_ref: str | None = Field(
        default=None, description="ST-2: QuestionScore.question_ref of that answer."
    )
    notes: list[StoryNote] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _unique_skills(self) -> Story:
        if len(self.skills) != len(set(self.skills)):
            raise ValueError("skills must not repeat")
        return self

    def part(self, name: StoryPart) -> str | None:
        """The text of one part, by StoryPart."""
        value: str | None = getattr(self, name.value)
        return value


class StoryFitItem(Contract):
    """ST-5: for one skill the interview will test, the best story and how well it fits."""

    competency: Competency
    story_id: UUID | None = Field(description="Null when no story fits (strength missing).")
    strength: StoryFitStrength
    reason: str = Field(min_length=1, description="One sentence the plan page shows.")

    @model_validator(mode="after")
    def _story_matches_strength(self) -> StoryFitItem:
        if (self.strength == StoryFitStrength.MISSING) != (self.story_id is None):
            raise ValueError("story_id is null exactly when strength is missing")
        return self


class StoryFit(Contract):
    """ST-5: the planner's story fit table, one item per tested skill."""

    items: list[StoryFitItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_item_per_skill(self) -> StoryFit:
        skills = [i.competency for i in self.items]
        if len(skills) != len(set(skills)):
            raise ValueError("items must have one entry per competency")
        return self
