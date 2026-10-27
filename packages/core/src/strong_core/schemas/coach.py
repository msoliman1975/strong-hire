"""Coach replies (CO-3, CO-4, CO-9) and story versions (CO-8)."""

from __future__ import annotations

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import Competency, StoryPart


class StoryPartUpdate(Contract):
    """CO-3, CO-9: new text for one story part, backed by the candidate's own words."""

    part: StoryPart
    text: str = Field(min_length=1, description="The part, written from the candidate's words.")
    quotes: list[str] = Field(
        min_length=1, description="The candidate's words this part came from, verbatim."
    )


class CoachReply(Contract):
    """CO-3, CO-4: one coach turn. The coach updates only the parts the candidate's own words
    support (CO-9) and asks for what is still missing."""

    message: str = Field(min_length=1, description="What the coach says to the candidate.")
    parts: list[StoryPartUpdate] = Field(
        default_factory=list, description="Parts this turn updated. Empty when none changed."
    )
    missing: list[StoryPart] = Field(
        default_factory=list, description="Parts the candidate has not given yet."
    )
    skills: list[Competency] = Field(
        default_factory=list, description="Skills the story shows so far."
    )

    @model_validator(mode="after")
    def _check(self) -> CoachReply:
        updated = [p.part for p in self.parts]
        if len(updated) != len(set(updated)):
            raise ValueError("parts must not repeat a story part")
        if len(self.missing) != len(set(self.missing)):
            raise ValueError("missing must not repeat")
        if set(updated) & set(self.missing):
            raise ValueError("a part cannot be both updated and missing")
        if len(self.skills) != len(set(self.skills)):
            raise ValueError("skills must not repeat")
        return self


class StoryVersion(Contract):
    """CO-8: one telling of the story, built only from the candidate's words."""

    text: str = Field(min_length=1)
    quotes: list[str] = Field(
        min_length=1, description="The candidate's words this version came from, verbatim."
    )


class StoryVersions(Contract):
    """CO-8: the coach's 60-second and full versions of a story."""

    sixty_second: StoryVersion = Field(description="About 150 words, to say in 60 seconds.")
    full: StoryVersion = Field(description="All five parts, in order.")
