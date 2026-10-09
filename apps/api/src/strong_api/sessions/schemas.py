"""Request and response bodies for the sessions API. Shapes match apps/web/src/api/planned.ts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import SessionChannel, SessionConfig, SessionStatus, Turn


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_target_id: uuid.UUID
    resume_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "PR-3: the CV to interview against. It needs a ready gap analysis with this job. "
            "Default: the CV of the job's latest ready gap analysis."
        ),
    )
    config: SessionConfig
    channel: SessionChannel = Field(
        default=SessionChannel.VOICE,
        description="text runs the same interviewer with typed input; dev and test only (PL-7)",
    )


class SessionRecord(BaseModel):
    id: uuid.UUID
    job_target_id: uuid.UUID
    resume_id: uuid.UUID | None = Field(
        default=None, description="PR-3: the CV used for the session. None for old sessions."
    )
    config: SessionConfig
    channel: SessionChannel
    status: SessionStatus
    brief_ready: bool = Field(description="True when the interviewer brief is built.")
    started_at: datetime | None
    ended_at: datetime | None
    minutes_billed: int
    failure_reason: str | None = Field(
        default=None,
        description=(
            "Plain reason when the session failed before it started (status failed, never "
            "started), for example when the interview plan could not be built. Such a session "
            "is not billed and does not use a free interview. Null otherwise."
        ),
    )


class TextTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class CoachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Literal["pause", "resume", "hint", "redo"]


class TextTurns(BaseModel):
    """The interviewer's new turns, and whether the session has ended."""

    turns: list[Turn]
    ended: bool
    phase: str


class VoiceJoin(BaseModel):
    """What the browser needs to join the interview room (P7, P10)."""

    livekit_url: str
    room: str
    token: str
    identity: str


class InternalEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interrupted: bool = Field(default=False, description="True when the candidate did not return.")
