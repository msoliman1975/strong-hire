"""Session setup, interviewer brief and transcript turns."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.custom import (
    CUSTOM_CASE_MIN_DURATION,
    CUSTOM_MAX_QUESTIONS,
    CustomSessionSpec,
    StandardType,
)
from strong_core.schemas.enums import (
    COMPETENCIES_BY_TYPE,
    AnswerConduct,
    Competency,
    Difficulty,
    InterviewType,
    Level,
    Mode,
    Phase,
    ProbeTrigger,
    QuestionSource,
    Speaker,
)

DurationMin = Literal[10, 30, 45]
MINI_DURATION_MIN: Final = 10
"""A mini interview: 3 questions, no candidate questions, no curveball, at most 1 probe."""

MINI_MAX_PROBES: Final = 1
FULL_MIN_QUESTIONS: Final = 6
FULL_MIN_COMPETENCIES: Final = 4


def session_duration(minutes: int) -> DurationMin:
    """A stored session length as a SessionConfig duration. Unknown values become 30."""
    if minutes == 10:
        return 10
    if minutes == 45:
        return 45
    return 30


class SessionConfig(Contract):
    """What the candidate picks before a session (journey 2, step 1)."""

    interview_type: InterviewType
    difficulty: Difficulty
    mode: Mode
    duration_min: DurationMin = Field(description="10 is a mini interview.")
    level: Level
    custom: CustomSessionSpec | None = Field(
        default=None, description="CU-1: required for the Custom type, absent for the others."
    )

    @property
    def is_mini(self) -> bool:
        return self.duration_min == MINI_DURATION_MIN

    @property
    def is_custom(self) -> bool:
        return self.interview_type == InterviewType.CUSTOM

    @model_validator(mode="after")
    def _check(self) -> SessionConfig:
        if not self.is_custom:
            if self.custom is not None:
                raise ValueError("only a custom session has a custom setup")
            return self
        if self.custom is None:
            raise ValueError("a custom session needs a custom setup")
        if self.is_mini:
            raise ValueError("a custom session cannot be a mini interview")
        cap = CUSTOM_MAX_QUESTIONS[self.duration_min]
        if len(self.custom.questions) > cap:
            raise ValueError(f"a {self.duration_min}-minute session allows {cap} own questions")
        kinds = {c.category for c in self.custom.categories}
        if InterviewType.CASE in kinds and self.duration_min < CUSTOM_CASE_MIN_DURATION:
            raise ValueError(f"case needs a {CUSTOM_CASE_MIN_DURATION}-minute session")
        return self


def session_competencies(config: SessionConfig) -> tuple[Competency, ...]:
    """The competencies a session can score: its type's, or the union over a Custom session's
    categories."""
    if config.custom is not None:
        return config.custom.competencies()
    return COMPETENCIES_BY_TYPE[config.interview_type]


class BriefQuestion(Contract):
    id: str = Field(pattern=r"^[a-z0-9_-]+$", description="Stable id, used as Turn.question_ref.")
    text: str = Field(min_length=1)
    competencies: list[Competency] = Field(min_length=1)
    values: list[str] = Field(
        default_factory=list, description="Company values this question probes (target_values)."
    )
    priority: int = Field(ge=1, description="1 is asked first.")
    probe_hints: list[str] = Field(default_factory=list)
    source: QuestionSource = Field(
        default=QuestionSource.PLANNER, description="CU-3: candidate for the candidate's own."
    )
    category: StandardType | None = Field(
        default=None, description="Custom sessions only: the question's category (CU-1)."
    )
    must_ask: bool = Field(
        default=False,
        description="CU-4: the session controller asks it before CANDIDATE_QUESTIONS.",
    )
    verbatim: bool = Field(default=False, description="CU-4: read the text word for word.")

    @model_validator(mode="after")
    def _check(self) -> BriefQuestion:
        if self.source != QuestionSource.CANDIDATE and (self.must_ask or self.verbatim):
            raise ValueError("must_ask and verbatim are for the candidate's own questions")
        return self


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
    target_competencies: list[Competency] = Field(
        min_length=2, max_length=6, description="4 to 6; a mini interview has 2."
    )
    target_values: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Company value names (Principle.name) to probe. Empty in generic mode.",
    )
    questions: list[BriefQuestion] = Field(
        min_length=3, max_length=10, description="6 to 10; a mini interview has 3."
    )
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
        if self.session.custom is not None:
            kinds = {c.category for c in self.session.custom.categories}
            for q in self.questions:
                if q.category is None or q.category not in kinds:
                    raise ValueError(f"question {q.id} needs a category of this custom session")
        elif any(q.source == QuestionSource.CANDIDATE or q.category for q in self.questions):
            raise ValueError("own questions and categories are for custom sessions only")
        if self.curveball and self.session.difficulty != Difficulty.TOUGH:
            raise ValueError("curveball is only allowed in Tough difficulty")
        if self.pushback and self.session.difficulty != Difficulty.TOUGH:
            raise ValueError("pushback is only allowed in Tough difficulty")
        if self.coach_help and self.session.mode != Mode.COACH:
            raise ValueError("coach_help is only allowed in Coach mode")
        if self.session.is_mini:
            if self.curveball:
                raise ValueError("a mini interview has no curveball")
            if self.max_probes_per_question > MINI_MAX_PROBES:
                raise ValueError(f"a mini interview allows at most {MINI_MAX_PROBES} probe")
        else:
            if len(self.questions) < FULL_MIN_QUESTIONS:
                raise ValueError(f"a full interview needs at least {FULL_MIN_QUESTIONS} questions")
            if len(self.target_competencies) < FULL_MIN_COMPETENCIES:
                raise ValueError(
                    f"a full interview needs at least {FULL_MIN_COMPETENCIES} target competencies"
                )
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


class DraftQuestion(Contract):
    """One question as the planner model writes it. The worker turns it into a BriefQuestion;
    only code sets the source, must-ask and verbatim fields."""

    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    text: str = Field(min_length=1)
    competencies: list[Competency] = Field(min_length=1)
    values: list[str] = Field(default_factory=list)
    priority: int = Field(ge=1, description="1 is asked first.")
    probe_hints: list[str] = Field(default_factory=list)
    category: StandardType | None = Field(
        default=None, description="Custom sessions only: one of the session's categories."
    )


class BriefDraft(Contract):
    """What the planner model returns for an interviewer brief. Code adds the rest: persona,
    seniority bar, probe limits, time plan and the profile version."""

    questions: list[DraftQuestion] = Field(min_length=6, max_length=12)
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


class ProbeDecision(Contract):
    """What the interviewer model decides after an answer in CORE (IV-3).

    A constrained choice, so a weak model cannot derail the session. The session controller
    enforces the probe limit per question and moves on once it is reached, whatever this says.
    """

    action: Literal["probe", "move_on"]
    missing: list[ProbeTrigger] = Field(
        default_factory=list, max_length=5, description="What the answer lacks; empty to move on."
    )


class AnswerCheck(Contract):
    """IV-12: the interviewer model's check of one candidate turn, before the reply.

    The runner warns the candidate on a turn that is not `ok`, and closes the interview when
    the warnings run out. `reason` goes to the admin traces only, never to the candidate.
    """

    conduct: AnswerConduct
    reason: str = Field(default="", max_length=200)
