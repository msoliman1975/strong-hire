"""Request and response bodies of the takes and versions API (CO-7, CO-8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import CompetencyScore, SessionChannel

TAKE_MAX_CHARS = 8000


class TakeStatus(StrEnum):
    SCORING = "scoring"
    SCORED = "scored"
    FAILED = "failed"


class TakeRequest(BaseModel):
    """CO-7: one telling of a story, typed or a voice transcript (S32)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=TAKE_MAX_CHARS)
    channel: SessionChannel = Field(
        default=SessionChannel.TEXT, description="voice when the text is a spoken transcript"
    )
    duration_s: float | None = Field(
        default=None, ge=0, description="Length of a spoken take; leave out for a typed one"
    )


class TakeOut(BaseModel):
    id: uuid.UUID
    story_id: uuid.UUID
    channel: SessionChannel
    text: str
    duration_s: float | None
    status: TakeStatus
    scores: list[CompetencyScore] = Field(
        default_factory=list, description="Per skill, 1 to 4, with the take's words as quotes"
    )
    reason: str | None = Field(default=None, description="Why scoring failed, in plain words")
    created_at: datetime
