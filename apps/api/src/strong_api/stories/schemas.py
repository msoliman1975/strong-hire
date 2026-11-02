"""Request and response bodies for the story API (ST-1, ST-2, ST-6, ST-8, ST-11, ST-13).
Stories are the core contract `Story` with the status to show (`StoryOut`)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from strong_core.schemas import (
    ACTION_STEPS_MAX,
    Competency,
    SlotEdit,
    SlotRef,
    Story,
    StoryOutline,
    StorySource,
    StoryStyle,
)
from strong_core.schemas.stories import STORY_TITLE_MAX_CHARS

STORY_PART_MAX_CHARS = 8000
"""One part of a story. Longer text is refused (422)."""
STORY_NOTE_MAX_CHARS = 2000
STORY_ASK_MAX_CHARS = 500


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


DisplayStatus = Literal["draft", "ready", "proven"]


class StoryOut(Story):
    """ST-1 and ST-8: a story with the status to show. Proven stays as stored (ST-7); a draft
    with all five parts filled shows as Ready."""

    display_status: DisplayStatus = Field(description="ST-8: draft, ready or proven.")


class StoryAskIn(_In):
    """ST-13: a question for Strova about the user's stories."""

    question: str = Field(min_length=1, max_length=STORY_ASK_MAX_CHARS)


class ReviewQueued(BaseModel):
    """ST-11: the review is being written. It arrives as an open `review` suggestion for the
    story (GET /suggestions?place=story&story_id=...)."""

    job_id: str


# --- Deep story crafting: the story page's outline actions (SC-10 to SC-13) ------------------

IMPROVE_NOTE_MAX_CHARS = 1000


class SlotEditIn(SlotRef):
    """SC-10, D-10: the user's own text for one slot (no quotes). Blank or null text empties the
    slot; `skipped` marks it skipped. The metric may also carry before, after and unit."""

    text: str | None = Field(default=None, max_length=STORY_PART_MAX_CHARS)
    skipped: bool = False
    before: str | None = Field(default=None, max_length=100)
    after: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=100)


class OutlinePatch(_In):
    """SC-10: inline edits. `slots` are applied first (a step index equal to the number of
    steps adds a step); then `steps`, when sent, is the new order of the action steps by their
    index, and a step left out is removed. 1 to 5 steps must remain."""

    slots: list[SlotEditIn] = Field(default_factory=list, max_length=60)
    steps: list[int] | None = Field(default=None, min_length=1, max_length=ACTION_STEPS_MAX)


class ImproveIn(_In):
    """SC-11: an optional note for Strova ("make it shorter", "add that I led the review")."""

    note: str | None = Field(default=None, max_length=IMPROVE_NOTE_MAX_CHARS)


class ImproveAccept(_In):
    """SC-11: the edits from an improve that the user accepts; the rest are rejected."""

    edits: list[SlotEdit] = Field(min_length=1, max_length=30)
    note: str | None = Field(
        default=None,
        max_length=IMPROVE_NOTE_MAX_CHARS,
        description="The note the improve was asked with, so its words count as the user's.",
    )


class StyleIn(_In):
    """SC-12: switch to the other style. Without `rewrite` the slots are renamed and moved in
    code and saved at once; with it, Strova rewrites the wording (one model call) as a preview."""

    style: StoryStyle
    rewrite: bool = False


class StyleSwitchOut(BaseModel):
    """SC-12: the switched story (no rewrite), or the rewrite to accept or discard."""

    story: StoryOut | None = None
    preview: StoryOutline | None = Field(
        default=None,
        description="The rewrite to accept (POST /stories/{id}/style/accept) or discard. Slots "
        "the user typed stay theirs; Strova's slots carry quotes.",
    )
