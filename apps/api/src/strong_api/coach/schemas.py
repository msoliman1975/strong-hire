"""Request and response bodies of the coach API (CO-2 to CO-5, SC-1, SC-4 to SC-7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import (
    AnswerConduct,
    CoachReply,
    CoachSessionStatus,
    CoachSpeaker,
    CoachStyle,
    Competency,
    CraftReply,
    SessionChannel,
    SlotRef,
    Story,
    StoryPart,
    StorySection,
    StoryStyle,
)

TURN_MAX_CHARS = 4000


class AskFor(StrEnum):
    """CO-4: the one thing the coach asks for next, from the IV-3 follow-up rules."""

    CONCRETE_EXAMPLE = "concrete_example"  # context: one specific time
    STAKES = "stakes"
    OWN_ROLE = "own_role"  # action, told as "I"
    MEASURABLE_RESULT = "measurable_result"  # result, with a number
    TRADEOFF_REASONING = "tradeoff_reasoning"
    REFLECTION = "reflection"
    NOTHING = "nothing"  # all five parts are there


class StartCoachRequest(BaseModel):
    """Start a coach session on a new story (no story_id) or an existing one."""

    model_config = ConfigDict(extra="forbid")

    story_id: uuid.UUID | None = None
    style: CoachStyle = CoachStyle.GENTLE
    channel: SessionChannel = Field(
        default=SessionChannel.TEXT, description="CO-6: voice sessions run through the voice agent"
    )
    target_skill: Competency | None = Field(
        default=None, description="The skill the story should show; tags the story."
    )
    job_target_id: uuid.UUID | None = Field(
        default=None,
        description="The plan page whose story-fit gap opened this session (with target_skill).",
    )
    resume_id: uuid.UUID | None = Field(
        default=None, description="ST-12: start from a story idea on this resume (RM-4)."
    )
    resume_line_ref: str | None = Field(
        default=None,
        pattern=r"^roles\[\d+\]\.achievements\[\d+\]$",
        description="ST-12: the achievement, as roles[<i>].achievements[<j>]. It seeds the "
        "context, and the first question asks for the stakes.",
    )
    story_style: StoryStyle | None = Field(
        default=None,
        description="SC-1: STAR or CARL for a new story, crafted section by section. Null keeps "
        "the classic five-part session; the response then carries Strova's suggested style. "
        "Ignored for an existing story, which keeps its own style.",
    )


class CoachTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=TURN_MAX_CHARS)


class StyleRequest(BaseModel):
    """CO-5: switch the style mid-session; the next reply uses it."""

    model_config = ConfigDict(extra="forbid")

    style: CoachStyle


class CoachTurnOut(BaseModel):
    seq: int
    speaker: CoachSpeaker
    text: str
    at_ms: int = Field(description="Milliseconds from the start of the session")


class CoachSessionOut(BaseModel):
    id: uuid.UUID
    story_id: uuid.UUID | None
    style: CoachStyle
    channel: SessionChannel
    status: CoachSessionStatus
    minutes: int
    started_at: datetime | None
    ended_at: datetime | None
    section: StorySection | None = Field(
        default=None,
        description="SC-4: the outline section in progress; null for a classic session, or once "
        "every section of a styled story is done",
    )


class CraftAsk(BaseModel):
    """SC-4, SC-7: what Strova is asking about on a styled story."""

    section: StorySection | None = Field(description="Null once every section is done")
    slots: list[SlotRef] = Field(description="The empty slots of the section, in asking order")


class CoachSessionDetail(BaseModel):
    session: CoachSessionOut
    story: Story | None
    turns: list[CoachTurnOut]
    missing: list[StoryPart] = Field(description="CO-3: parts the story does not have yet")
    asking_for: AskFor = Field(description="CO-4: what the coach is asking for now")
    asking: CraftAsk | None = Field(
        default=None, description="SC-4: the section and slots, for a styled story"
    )
    suggested_style: StoryStyle | None = Field(
        default=None,
        description="SC-1, D-2: Strova's suggested style when a new session started without one",
    )


class StyleSuggestion(BaseModel):
    """SC-1, D-2: the style the start screen preselects."""

    style: StoryStyle


class CoachTurnResult(BaseModel):
    """One candidate turn and the coach's reply."""

    reply: CoachReply = Field(
        description="CO-3: only the part updates the candidate's own words back. On a styled "
        "story the parts are empty and `craft` has the slot updates."
    )
    craft: CraftReply | None = Field(
        default=None,
        description="SC-6: on a styled story, the kept slot updates and skips, and whether the "
        "section is done",
    )
    asking: CraftAsk | None = Field(default=None, description="SC-4: what Strova asks next")
    story: Story | None = Field(description="None when an empty new story was dropped at the end")
    turns: list[CoachTurnOut] = Field(description="The candidate's turn, then the coach's")
    asking_for: AskFor
    conduct: AnswerConduct = Field(description="IV-12: ok, or why the turn got a warning")
    ended: bool = Field(description="True when the session ended on this turn")
