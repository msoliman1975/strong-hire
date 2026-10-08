"""Response bodies for the admin area (R2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from strong_core.schemas import (
    Competency,
    Difficulty,
    HireSignal,
    InterviewType,
    Mode,
    Phase,
    SessionChannel,
    SessionStatus,
    SubscriptionStatus,
    Turn,
)

CostSource = Literal["usage_events", "traces", "none"]


class AdminUser(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime
    last_sign_in_at: datetime | None
    plan: Literal["free", "paid"]
    subscription_status: SubscriptionStatus | None
    minutes_used: int
    minutes_cap: int
    training_consent: bool
    interviews: int
    is_admin: bool


class AdminScore(BaseModel):
    competency: Competency
    score: int


class AdminSession(BaseModel):
    """Metadata of one interview. Always shown, with or without consent."""

    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None
    training_consent: bool
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    interview_type: InterviewType
    difficulty: Difficulty
    mode: Mode
    duration_min: int
    duration_s: int | None = Field(description="From start to end. None until it ends.")
    channel: SessionChannel
    status: SessionStatus
    minutes_billed: int
    hire_signal: HireSignal | None
    scores: list[AdminScore]
    model_profile: str | None
    interviewer_model_id: str | None
    prompt_version: str | None
    cost_usd: float | None = Field(
        description="Interviewer model cost. From usage events, else from the traces."
    )
    cost_source: CostSource


class DailyCost(BaseModel):
    day: date
    sessions: int
    cost_usd: float


class AdminSessionList(BaseModel):
    sessions: list[AdminSession]
    daily: list[DailyCost] = Field(description="Cost per day (UTC) of the sessions listed.")
    total_cost_usd: float
    limit: int


class AdminMessage(BaseModel):
    role: str
    content: str
    prompt_ref: str | None = None


class AdminTrace(BaseModel):
    seq: int
    turn_index: int
    call: str
    move: str
    reason: dict[str, Any] | None
    phase: Phase
    elapsed_ms: int
    phase_deadline_ms: int | None
    question_ref: str | None
    messages: list[AdminMessage] | None
    raw_reply: str | None
    spoken_text: str | None
    model: str | None
    prompt_refs: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: int | None
    error: str | None
    created_at: datetime


class AdminSessionDetail(BaseModel):
    session: AdminSession
    content_visible: bool = Field(
        description="True when the user has training consent on now. Else only metadata."
    )
    transcript: list[Turn] | None
    traces: list[AdminTrace] | None
    trace_retention_days: int


class AdminAuditEntry(BaseModel):
    id: uuid.UUID
    at: datetime
    actor: str
    action: str
    entity: str
    org_id: uuid.UUID | None
    details: dict[str, Any] | None
