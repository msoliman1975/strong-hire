"""Response bodies for the debrief and progress endpoints (FB-1 to FB-3, PR-1, PR-2).

The scorecard, snapshots and planned session inside them are the shared contracts from
strong_core.schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import (
    Competency,
    PlannedSession,
    ProgressSnapshot,
    Scorecard,
    SessionConfig,
    SessionStatus,
)

# "not_ended": the interview has not ended yet (created, in progress or interrupted), so nothing
# is being scored. The web app must not wait for a scorecard then.
# "not_started": the session failed before it started (the interview plan could not be built, or
# it was ended before the candidate joined). Nothing was scored, counted or billed.
DebriefStatus = Literal["not_ended", "not_started", "scoring", "ready", "failed"]
TrendDirection = Literal["up", "down", "flat", "single"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DebriefSession(_Out):
    """The session a debrief belongs to. Same shape as the web app's SessionRecord."""

    id: uuid.UUID
    job_target_id: uuid.UUID
    config: SessionConfig
    status: SessionStatus
    started_at: datetime | None
    ended_at: datetime | None
    minutes_billed: int
    failure_reason: str | None = Field(
        default=None, description="Plain reason when the session failed before it started."
    )


class Debrief(_Out):
    session: DebriefSession
    status: DebriefStatus
    scorecard: Scorecard | None
    next_session: PlannedSession | None = Field(
        description="PR-2. Null until the debrief is ready."
    )
    generic_mode: bool = Field(description="True when no company profile was used: no values.")
    company_name: str | None
    values_framework: str | None = Field(
        description="Name of the company's values framework, for example 'Leadership Principles'."
    )


class CompetencyTrend(_Out):
    """PR-1: one competency over the Realistic sessions of a job target."""

    competency: Competency
    sessions: int = Field(ge=1)
    first: float = Field(ge=1, le=4)
    latest: float = Field(ge=1, le=4)
    change: float = Field(description="latest minus first")
    average: float = Field(ge=1, le=4)
    direction: TrendDirection


class JobProgress(_Out):
    job_target_id: uuid.UUID
    snapshots: list[ProgressSnapshot] = Field(description="Realistic sessions only (PR-1).")
    trends: list[CompetencyTrend] = Field(description="Weakest latest score first.")
    next_session: PlannedSession | None = Field(description="PR-2.")


class ScoringAccepted(_Out):
    session_id: uuid.UUID
    job_id: str
    status: SessionStatus
