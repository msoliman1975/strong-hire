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
    CustomSessionSpec,
    Difficulty,
    HireSignal,
    PlannedSession,
    ProgressSnapshot,
    QuestionSource,
    Scorecard,
    SessionConfig,
    SessionStatus,
    StandardType,
    Suggestion,
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


class DebriefQuestion(_Out):
    """One question of the session's interview plan (CU-6). Join it to
    `scorecard.per_question[].question_ref` by `question_ref`."""

    question_ref: str = Field(description="The brief question id (Turn.question_ref).")
    text: str
    source: QuestionSource = Field(description="candidate for the candidate's own question.")
    category: StandardType | None = Field(description="Custom sessions: the category.")
    competencies: list[Competency] = Field(
        default_factory=list,
        description="The competencies the question targets. CU-9: the web app saves an "
        "interviewer question to My questions with them.",
    )
    must_ask: bool
    verbatim: bool


class CustomRecommendation(_Out):
    """CU-10: a Custom session to practice the open gaps of several interview types together.
    `custom` is a ready setup (even shares, focus chips from the gaps, no own questions) that the
    web app opens prefilled."""

    interview_type: Literal["custom"] = "custom"
    difficulty: Difficulty
    duration_min: Literal[30, 45] = Field(description="45 when Case is a category (D-3).")
    custom: CustomSessionSpec
    focus_topics: list[str] = Field(
        min_length=1, description="The lead focus chip of each category, for the title."
    )
    reason: str = Field(min_length=1)


class PreviousSignal(_Out):
    """DB-1: the hire signal of the session before this one for the same job target."""

    session_id: uuid.UUID
    hire_signal: HireSignal
    ended_at: datetime | None
    change: int = Field(
        description="Bands moved since that session: positive is better, 0 is the same."
    )


class AnswersAtBar(_Out):
    """DB-2: answers whose average rubric score is 3 or more, out of the answers scored."""

    met: int = Field(ge=0)
    scored: int = Field(ge=0)


class Debrief(_Out):
    session: DebriefSession
    status: DebriefStatus
    scorecard: Scorecard | None
    next_session: PlannedSession | None = Field(
        description="PR-2. Null until the debrief is ready."
    )
    next_custom_session: CustomRecommendation | None = Field(
        default=None,
        description="CU-10: a Custom session that mixes the open gaps, when one fits and the "
        "user may run Custom. Shown in place of `next_session` by the web app.",
    )
    generic_mode: bool = Field(description="True when no company profile was used: no values.")
    company_name: str | None
    company_slug: str | None = Field(
        default=None,
        description="QB-4: the company to filter the Questions page by. None in generic mode.",
    )
    values_framework: str | None = Field(
        description="Name of the company's values framework, for example 'Leadership Principles'."
    )
    questions: list[DebriefQuestion] = Field(
        default_factory=list,
        description="CU-6: the planned questions with their source and category, in plan "
        "order. Empty when the session has no interview plan.",
    )
    previous_signal: PreviousSignal | None = Field(
        default=None,
        description="DB-1. Null when no earlier session of the same job target was scored.",
    )
    answers_at_bar: AnswersAtBar | None = Field(
        default=None, description="DB-2. Null until the debrief is ready."
    )
    suggestions: list[Suggestion] = Field(
        default_factory=list,
        description="DB-5, SG-2 to SG-4: Strova's open suggestions from this take, newest first.",
    )
    next_plan_item: str | None = Field(
        default=None,
        description="DB-6: the next item of the personal plan. Null until the plan has one (U11).",
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


class OwnQuestionPoint(_Out):
    """CU-7: a snapshot of a Custom session that comes (partly) from the candidate's own
    questions."""

    session_id: uuid.UUID
    competency: Competency
    own_questions: int = Field(ge=1, description="Scores from the candidate's own questions.")
    other_questions: int = Field(ge=0, description="Scores from the interviewer's questions.")


class JobProgress(_Out):
    job_target_id: uuid.UUID
    snapshots: list[ProgressSnapshot] = Field(
        description="Realistic sessions only (PR-1), Custom ones included (CU-7)."
    )
    trends: list[CompetencyTrend] = Field(description="Weakest latest score first.")
    next_session: PlannedSession | None = Field(description="PR-2.")
    next_custom_session: CustomRecommendation | None = Field(
        default=None,
        description="CU-10: a Custom session that mixes the open gaps, when one fits and the "
        "user may run Custom.",
    )
    own_question_points: list[OwnQuestionPoint] = Field(
        default_factory=list,
        description="CU-7: the snapshots that use scores of the candidate's own questions. "
        "Empty when own questions are excluded.",
    )
    own_questions_excluded: bool = Field(
        default=False,
        description="CU-7: true when the snapshots and trends leave out own questions' scores.",
    )


class ScoringAccepted(_Out):
    session_id: uuid.UUID
    job_id: str
    status: SessionStatus
