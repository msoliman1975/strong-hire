"""Request bodies for the story API (ST-1, ST-2, ST-6). Responses use the core contracts
`Story` and `StoryNote` (strong_core.schemas.stories)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from strong_core.schemas import Competency, StorySource
from strong_core.schemas.stories import STORY_TITLE_MAX_CHARS

STORY_PART_MAX_CHARS = 8000
"""One part of a story. Longer text is refused (422)."""
STORY_NOTE_MAX_CHARS = 2000


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _unique(skills: list[Competency] | None) -> list[Competency] | None:
    if skills is not None and len(skills) != len(set(skills)):
        raise ValueError("skills must not repeat")
    return skills


Part = str | None


class StoryIn(_In):
    """ST-1: a new story typed by the candidate (or built by the coach). It starts as a draft."""

    title: str = Field(min_length=1, max_length=STORY_TITLE_MAX_CHARS)
    context: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    stakes: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    action: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    result: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    reflection: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    skills: list[Competency] = Field(default_factory=list, description="Skill tags.")
    source: Literal[StorySource.MANUAL, StorySource.COACH] = Field(
        default=StorySource.MANUAL,
        description="A debrief answer becomes a story through POST /stories/from-answer.",
    )

    _skills = field_validator("skills")(_unique)


class StoryPatch(_In):
    """ST-1: change the title, the skill tags or any part. Only the fields sent change; a part
    sent as null (or blank) is cleared. The status is never set by hand (ST-7)."""

    title: str | None = Field(default=None, min_length=1, max_length=STORY_TITLE_MAX_CHARS)
    context: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    stakes: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    action: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    result: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    reflection: Part = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    skills: list[Competency] | None = None

    _skills = field_validator("skills")(_unique)


class StoryFromAnswerIn(_In):
    """ST-2: save one debrief answer as a draft story."""

    session_id: uuid.UUID
    question_ref: str = Field(min_length=1, description="QuestionScore.question_ref.")
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=STORY_TITLE_MAX_CHARS,
        description="Default: the question's text, cut to the title limit.",
    )


class StoryNoteIn(_In):
    """ST-6: a fix note for the story, usually from a debrief answer that used it."""

    text: str = Field(min_length=1, max_length=STORY_NOTE_MAX_CHARS)
    session_id: uuid.UUID | None = None
    question_ref: str | None = Field(default=None, min_length=1)
