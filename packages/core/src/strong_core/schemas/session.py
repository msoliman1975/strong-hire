"""Session setup, interviewer brief and transcript turns."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import (
    Competency,
    Difficulty,
    InterviewType,
    Level,
    Mode,
    Phase,
    Speaker,
)


class SessionConfig(Contract):
    """What the candidate picks before a session (journey 2, step 1)."""

    interview_type: InterviewType
    difficulty: Difficulty
    mode: Mode
    duration_min: Literal[30, 45]
    level: Level


class BriefQuestion(Contract):
    id: str = Field(pattern=r"^[a-z0-9_-]+$", description="Stable id, used as Turn.question_ref.")
    text: str = Field(min_length=1)
    competencies: list[Competency] = Field(min_length=1)
    values: list[str] = Field(
        default_factory=list, description="Company values this question probes (target_values)."
    )
    priority: int = Field(ge=1, description="1 is asked first.")
    probe_hints: list[str] = Field(default_factory=list)


class PersonaBrief(Contract):
    tone: str = Field(min_length=1)
    pushback_style: str = Field(min_length=1)
    closing_style: str = Field(min_length=1)


class PhaseTime(Contract):
    """Minutes planned for one phase of the session (IV-7)."""

    phase: Phase
    minutes: int = Field(ge=0, le=45)


class InterviewerBrief(Contract):
    """Built by the planner before each session. The live interviewer reads only this."""

    session: SessionConfig
    company_name: str | None = Field(default=None, description="None in generic mode.")
    generic_mode: bool
    profile_version: int | None = Field(default=None, ge=1)
    target_competencies: list[Competency] = Field(min_length=4, max_length=6)
    target_values: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Company value names (Principle.name) to probe. Empty in generic mode.",
    )
    questions: list[BriefQuestion] = Field(min_length=6, max_length=10)
    probe_areas: list[str] = Field(default_factory=list)
    persona: PersonaBrief
    max_probes_per_question: int = Field(ge=0, le=3, description="IV-3.")
    curveball: str | None = Field(default=None, description="Tough difficulty only (IV-4).")
    seniority_bar: str | None = Field(
        default=None, description="Scope expected at session.level (IV-6). Level changes the bar."
    )
    pushback: bool = Field(
        default=False, description="Tough difficulty only: challenge assumptions (IV-4)."
    )
    coach_help: bool = Field(
        default=False, description="Coach mode only: pause, hint and redo are allowed (IV-8)."
    )
    time_plan: list[PhaseTime] = Field(
        default_factory=list,
        description="Minutes per phase. When set, the minutes add up to session.duration_min.",
    )

    @model_validator(mode="after")
    def _check(self) -> InterviewerBrief:
        if self.generic_mode and self.profile_version is not None:
            raise ValueError("generic_mode briefs must not have a profile_version")
        if not self.generic_mode and self.profile_version is None:
            raise ValueError("company briefs must record the profile_version used")
        if self.generic_mode and self.target_values:
            raise ValueError("generic_mode briefs must not have target_values")
        stray = sorted({v for q in self.questions for v in q.values} - set(self.target_values))
        if stray:
            raise ValueError(f"questions use values not in target_values: {', '.join(stray)}")
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        if self.curveball and self.session.difficulty != Difficulty.TOUGH:
            raise ValueError("curveball is only allowed in Tough difficulty")
        if self.pushback and self.session.difficulty != Difficulty.TOUGH:
            raise ValueError("pushback is only allowed in Tough difficulty")
        if self.coach_help and self.session.mode != Mode.COACH:
            raise ValueError("coach_help is only allowed in Coach mode")
        if self.time_plan:
            phases = [p.phase for p in self.time_plan]
            if len(phases) != len(set(phases)):
                raise ValueError("time_plan lists a phase more than once")
            total = sum(p.minutes for p in self.time_plan)
            if total != self.session.duration_min:
                raise ValueError(
                    f"time_plan adds up to {total} minutes, not {self.session.duration_min}"
                )
        return self


class BriefDraft(Contract):
    """What the planner model returns for an interviewer brief. Code adds the rest: persona,
    seniority bar, probe limits, time plan and the profile version."""

    questions: list[BriefQuestion] = Field(min_length=6, max_length=12)
    curveball: str | None = Field(default=None, description="Only asked for in Tough difficulty.")


class Turn(Contract):
    """One utterance in the transcript. Text only; audio is never stored."""

    speaker: Speaker
    phase: Phase
    text: str
    start_ms: int = Field(ge=0, description="Offset from session start.")
    end_ms: int = Field(ge=0)
    question_ref: str | None = Field(default=None, description="BriefQuestion.id, in CORE only.")

    @model_validator(mode="after")
    def _check(self) -> Turn:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self
