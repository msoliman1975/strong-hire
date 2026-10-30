"""Request and response bodies of the coach API (CO-2 to CO-5)."""

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
    SessionChannel,
    Story,
    StoryPart,
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


class CoachSessionDetail(BaseModel):
    session: CoachSessionOut
    story: Story | None
    turns: list[CoachTurnOut]
    missing: list[StoryPart] = Field(description="CO-3: parts the story does not have yet")
    asking_for: AskFor = Field(description="CO-4: what the coach is asking for now")


class CoachTurnResult(BaseModel):
    """One candidate turn and the coach's reply."""

    reply: CoachReply = Field(
        description="CO-3: only the part updates the candidate's own words back"
    )
    story: Story | None = Field(description="None when an empty new story was dropped at the end")
    turns: list[CoachTurnOut] = Field(description="The candidate's turn, then the coach's")
    asking_for: AskFor
    conduct: AnswerConduct = Field(description="IV-12: ok, or why the turn got a warning")
    ended: bool = Field(description="True when the session ended on this turn")
