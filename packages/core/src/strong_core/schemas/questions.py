"""Question bank contracts for the Questions page (QB-1 to QB-5).

The bank has two parts:
- Company questions: `SampleQuestion` entries in each Published company profile.
- General questions: `questions/general.json`, validated by `GeneralQuestionBank`.

Both carry `QuestionHints`: what the question is looking for, strong signals and watch-outs.
Hints are our own guidance, never a model answer (model answers are out of scope for v1).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field, WithJsonSchema, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import (
    COMPETENCIES_BY_TYPE,
    STANDARD_INTERVIEW_TYPES,
    Competency,
    InterviewType,
    Level,
    RoleFamily,
)

BANK_INTERVIEW_TYPES: tuple[InterviewType, ...] = (
    *STANDARD_INTERVIEW_TYPES,
    InterviewType.RECRUITER_SCREEN,
)
"""The types a bank question can have: the four standard types and Recruiter screen (RS-1)."""


def _bank_type(value: InterviewType) -> InterviewType:
    if value not in BANK_INTERVIEW_TYPES:
        raise ValueError(
            f"{value.value} is not a question category; use a standard type or recruiter_screen"
        )
    return value


BankType = Annotated[
    InterviewType,
    AfterValidator(_bank_type),
    WithJsonSchema({"enum": [t.value for t in BANK_INTERVIEW_TYPES], "type": "string"}),
]
"""A standard interview type or recruiter_screen (RS-1). Never Custom."""

HintLine = Annotated[str, Field(min_length=1, max_length=200)]


class QuestionHints(Contract):
    """QB-2: short bullets shown under a question on the Questions page."""

    looking_for: list[HintLine] = Field(
        min_length=1, max_length=4, description="What the interviewer is assessing."
    )
    strong_signals: list[HintLine] = Field(
        min_length=1, max_length=4, description="What a strong answer shows."
    )
    watch_outs: list[HintLine] = Field(
        min_length=1, max_length=4, description="Common ways answers fall short."
    )


class GeneralQuestion(Contract):
    """A question asked across many companies. Written in our own words (QB-5)."""

    id: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        max_length=80,
        description="Stable slug, unique in the bank.",
    )
    interview_type: BankType
    question: str = Field(min_length=1, max_length=400)
    hints: QuestionHints
    competencies: list[Competency] = Field(min_length=1, max_length=3)
    role_families: list[RoleFamily] = Field(
        default_factory=list, description="Job categories it fits. Empty means all."
    )
    levels: list[Level] = Field(default_factory=list, description="Empty means all levels.")

    @model_validator(mode="after")
    def _check(self) -> GeneralQuestion:
        allowed = set(COMPETENCIES_BY_TYPE[self.interview_type])
        wrong = sorted(c.value for c in self.competencies if c not in allowed)
        if wrong:
            raise ValueError(
                f"competencies {', '.join(wrong)} do not belong to {self.interview_type.value}"
            )
        return self


class GeneralQuestionBank(Contract):
    """The file questions/general.json."""

    version: int = Field(ge=1)
    questions: list[GeneralQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> GeneralQuestionBank:
        ids = [q.id for q in self.questions]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate question ids: {', '.join(dupes)}")
        return self
