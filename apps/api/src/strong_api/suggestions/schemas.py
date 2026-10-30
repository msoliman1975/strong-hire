"""Request and response bodies of the suggestions endpoints (SG-2 to SG-8)."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import Competency, StoryPart, Suggestion


class Place(StrEnum):
    """Where the suggestions are shown (ux-spec section 8)."""

    DEBRIEF = "debrief"  # session_id
    STORY = "story"  # story_id
    ROLE = "role"  # job_target_id
    STORIES = "stories"  # Career Stories "Strova suggests"
    RESUME = "resume"  # resume_id


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after: str | None = Field(
        default=None,
        min_length=1,
        description='"Edit first": the user\'s edited text, in place of the proposed one. For '
        "tune_story, improve_resume_line and tailor_role.",
    )
    parts: list[StoryPart] | None = Field(
        default=None,
        description="review: the parts whose edits to apply. Null applies every edit.",
    )


class Crafting(BaseModel):
    """SG-4, RM-4: what "Craft with Strova" opens with."""

    model_config = ConfigDict(extra="forbid")

    competency: Competency | None = None
    job_target_id: UUID | None = None
    achievement: str | None = Field(default=None, description="RM-4: the context to start from.")
    skills: list[Competency] = Field(default_factory=list)


class AcceptOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion: Suggestion
    story_id: UUID | None = Field(
        default=None, description="The story it changed or created (SG-2, SG-3, SG-5, ST-11)."
    )
    resume_id: UUID | None = Field(default=None, description="The resume it changed (SG-6).")
    crafting: Crafting | None = Field(
        default=None, description="SG-4, RM-4: open crafting with this target."
    )
    can_undo: bool = False
