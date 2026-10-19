"""Contracts of the Simulations routes (docs/admin-spec.md, SM). Only the admin app reads them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from strong_core.schemas import Difficulty, InterviewType, Level, Mode, Scorecard
from strong_core.schemas.enums import SimRunStatus
from strong_core.schemas.session import DurationMin
from strong_core.sim import PERSONAS, VOICE_ONLY, Behavior, Quality

Channel = Literal["text", "voice"]
RunSource = Literal["admin", "suite"]

# SM-9: response-time colors. Green under OK_MS (the spec's p50 budget), red over SLOW_MS.
LATENCY_OK_MS = 800
LATENCY_SLOW_MS = 1500


# --- the new-run form (SM-1, SM-2) -----------------------------------------------------------


class SimPersonaOut(BaseModel):
    id: str = Field(description="Resume fixture id")
    label: str
    posting: str = Field(description="The posting fixture this resume is meant for")
    level: Level


class SimBehaviorOut(BaseModel):
    id: Behavior
    voice_only: bool


class SimEstimateOut(BaseModel):
    duration_min: int
    candidate_usd: float
    judge_usd: float
    main_server_usd: float
    total_usd: float


class SimBudgetOut(BaseModel):
    limit_usd: float
    spent_usd: float = Field(description="Spend of the sim LiteLLM key in the current period")
    left_usd: float
    resets_at: datetime | None


class SimGateOut(BaseModel):
    ok: bool = Field(description="SM-3 without the budget part: enabled, not paused, live limit")
    retry: bool = Field(description="Only the live-sessions limit is in the way")
    reason: str | None


class SimQueueOut(BaseModel):
    active: int
    waiting: int = Field(description="queued and waiting runs")
    max_waiting: int


class SimOptions(BaseModel):
    """SM-1: everything the form offers, and whether a run could start now."""

    personas: list[SimPersonaOut]
    interview_types: list[InterviewType]
    difficulties: list[Difficulty]
    modes: list[Mode]
    durations: list[int]
    qualities: list[Quality]
    behaviors: list[SimBehaviorOut]
    channels: list[Channel]
    estimates: list[SimEstimateOut] = Field(description="One per duration")
    budget: SimBudgetOut | None = Field(description="None when the sim key budget is unknown")
    gate: SimGateOut
    queue: SimQueueOut


class SimRunIn(BaseModel):
    """SM-1: one interview. The posting and level follow the persona."""

    model_config = ConfigDict(extra="forbid")

    persona: str
    interview_type: InterviewType = InterviewType.BEHAVIORAL
    difficulty: Difficulty = Difficulty.REALISTIC
    mode: Mode = Mode.REALISTIC
    duration_min: DurationMin = 30
    quality: Quality = Quality.AVERAGE
    behavior: Behavior = Behavior.NORMAL
    channel: Channel = "voice"

    @model_validator(mode="after")
    def _check(self) -> SimRunIn:
        if self.persona not in PERSONAS:
            raise ValueError(f"unknown persona {self.persona!r}")
        if self.behavior in VOICE_ONLY and self.channel != "voice":
            raise ValueError(f"behavior {self.behavior.value} needs the voice channel")
        return self


class SimKeepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep: bool


class SimCancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


# --- the runs list (SM-4, SM-12, SM-13) --------------------------------------------------------


class SimScenarioOut(BaseModel):
    channel: str
    interview_type: str
    difficulty: str
    mode: str
    duration_min: int
    persona: str
    quality: str
    behavior: str
    candidate_name: str | None = None


class SimRunOut(BaseModel):
    id: str = Field(description="The sim_runs id; for a suite run '<run folder>/<scenario id>'")
    source: RunSource
    suite: str | None = Field(description="Suite name for runs from sim-run.ps1")
    run_dir: str | None
    created_by: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    status: SimRunStatus
    status_reason: str | None
    scenario: SimScenarioOut
    session_id: uuid.UUID | None
    progress_s: int = Field(description="SM-4: interview time so far")
    planned_s: int
    hire_signal: str | None
    failed_rules: list[str]
    problems: int
    latency_p50_ms: float | None
    cost_sim_usd: float | None = Field(description="Candidate and judge (the sim's meter)")
    cost_app_usd: float | None = Field(description="usage_events of the session")
    cost_total_usd: float | None
    keep: bool
    deleted_at: datetime | None
    deleted_by: str | None
    delete_reason: str | None
    files: bool = Field(description="The run folder is on disk")


class SimRunList(BaseModel):
    runs: list[SimRunOut]
    any_unfinished: bool = Field(description="SM-4: poll every 5 s while true")


# --- replay (SM-6..SM-11) --------------------------------------------------------------------


class ReplayLine(BaseModel):
    speaker: Literal["interviewer", "candidate"]
    text: str
    start_ms: int
    end_ms: int
    phase: str | None
    note: str | None = Field(description="What the harness did, e.g. 'silent for 6 s'")
    latency_ms: int | None = Field(description="SM-9, on the first interviewer line of a reply")


class ReplayLatency(BaseModel):
    n: int
    p50_ms: int | None
    p90_ms: int | None
    slow_turns: int = Field(description=f"Turns over {LATENCY_SLOW_MS} ms")
    ok_ms: int = LATENCY_OK_MS
    slow_ms: int = LATENCY_SLOW_MS


class ReplayRule(BaseModel):
    rule: str
    verdict: str = Field(description="pass, fail or not_applicable")
    reason: str


class ReplayProblem(BaseModel):
    at: str = Field(description="mm:ss")
    at_ms: int | None = Field(description="`at` in ms, for the scrubber marker")
    problem: str


class ReplayJudge(BaseModel):
    rubric: str | None
    model: str | None
    rules: list[ReplayRule]
    problems: list[ReplayProblem]


class ReplayAudio(BaseModel):
    available: bool
    bytes: int | None = Field(description="GET /admin/sessions/{id}/audio answers Range (SM-7)")


class SessionReplay(BaseModel):
    session_id: uuid.UUID
    run_dir: str | None = Field(description="The run folder; None: from the database only")
    sim_run_id: uuid.UUID | None
    channel: str
    timing: Literal["audio", "approximate"] = Field(
        description="SM-8: 'audio' when times are positions in the recording (SM-6)"
    )
    lines: list[ReplayLine]
    latency: ReplayLatency
    judge: ReplayJudge | None
    scorecard: Scorecard | None = Field(description="SM-11: as the candidate saw it")
    audio: ReplayAudio
    scenario: SimScenarioOut | None
