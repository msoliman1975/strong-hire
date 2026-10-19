"""Custom interview setup (docs/custom-interview-spec.md, CU-1 to CU-5).

The candidate mixes 1 to 3 standard interview types as question categories, picks focus chips
for each, and adds their own questions. Rules that need the session length (Case needs 45
minutes, the question caps) live in `SessionConfig`, which knows the duration.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final

from pydantic import AfterValidator, Field, WithJsonSchema, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import (
    COMPETENCIES_BY_TYPE,
    STANDARD_INTERVIEW_TYPES,
    Competency,
    InterviewType,
    QuestionRefusal,
)


def _standard(value: InterviewType) -> InterviewType:
    if value not in STANDARD_INTERVIEW_TYPES:
        raise ValueError(f"{value.value} is not a question category; use one of the four types")
    return value


StandardType = Annotated[
    InterviewType,
    AfterValidator(_standard),
    WithJsonSchema({"enum": [t.value for t in STANDARD_INTERVIEW_TYPES], "type": "string"}),
]
"""One of the four standard interview types (IV-2). Never Custom."""

CUSTOM_MAX_CATEGORIES: Final = 3
CUSTOM_MAX_QUESTIONS: Final[dict[int, int]] = {30: 5, 45: 8}
"""CU-3: own questions per session length. Custom has no 10-minute mini interview (D-14)."""

CUSTOM_CASE_MIN_DURATION: Final = 45
CUSTOM_CASE_MAX_CATEGORIES: Final = 2
"""D-3: a case needs about 20 minutes, so Case needs 45 minutes and at most one other category."""

CUSTOM_MIN_SHARE: Final = 0.15
CUSTOM_CASE_MIN_SHARE: Final = 0.5
"""Smallest time share of a category; Case gets at least half the core time when mixed."""

CUSTOM_MAX_FOCUS: Final = 8
CUSTOM_FOCUS_MAX_LEN: Final = 60
CUSTOM_QUESTION_MAX_LEN: Final = 500
CUSTOM_QUESTION_MAX_COMPETENCIES: Final = 3

_SHARE_TOLERANCE: Final = 0.01

FocusChip = Annotated[str, Field(min_length=1, max_length=CUSTOM_FOCUS_MAX_LEN)]


class CustomCategory(Contract):
    """One question category in a Custom session (CU-1, CU-2)."""

    category: StandardType
    share: float = Field(gt=0, le=1, description="Share of the core time. Shares add up to 1.")
    focus: list[FocusChip] = Field(
        default_factory=list,
        max_length=CUSTOM_MAX_FOCUS,
        description="Topics to focus on, for example 'conflict' or 'Kubernetes' (CU-2).",
    )


class CustomQuestion(Contract):
    """A question the candidate wrote or saved (CU-3, CU-4)."""

    text: str = Field(min_length=1, max_length=CUSTOM_QUESTION_MAX_LEN)
    category: StandardType
    competencies: list[Competency] = Field(
        min_length=1,
        max_length=CUSTOM_QUESTION_MAX_COMPETENCIES,
        description="From COMPETENCIES_BY_TYPE for the category. Tagged by the CU-5 check.",
    )
    must_ask: bool = Field(default=True, description="CU-4: the session controller asks it.")
    verbatim: bool = Field(default=False, description="CU-4: read the text word for word.")
    saved_question_id: uuid.UUID | None = Field(
        default=None, description="CU-8: the saved_questions row it came from."
    )

    @model_validator(mode="after")
    def _check(self) -> CustomQuestion:
        allowed = COMPETENCIES_BY_TYPE[self.category]
        wrong = [c.value for c in self.competencies if c not in allowed]
        if wrong:
            raise ValueError(
                f"competencies {', '.join(wrong)} do not belong to {self.category.value}"
            )
        if len(set(self.competencies)) != len(self.competencies):
            raise ValueError("competencies are listed more than once")
        return self


class CustomSessionSpec(Contract):
    """What the candidate builds for a Custom session. Stored in sessions.custom_json."""

    categories: list[CustomCategory] = Field(min_length=1, max_length=CUSTOM_MAX_CATEGORIES)
    questions: list[CustomQuestion] = Field(
        default_factory=list, max_length=max(CUSTOM_MAX_QUESTIONS.values())
    )

    @model_validator(mode="after")
    def _check(self) -> CustomSessionSpec:
        kinds = [c.category for c in self.categories]
        if len(kinds) != len(set(kinds)):
            raise ValueError("a category is listed more than once")
        total = sum(c.share for c in self.categories)
        if abs(total - 1) > _SHARE_TOLERANCE:
            raise ValueError(f"category shares add up to {total:.2f}, not 1")
        if len(self.categories) > 1:
            for c in self.categories:
                if c.share < CUSTOM_MIN_SHARE - _SHARE_TOLERANCE:
                    raise ValueError(
                        f"{c.category.value} needs a share of at least {CUSTOM_MIN_SHARE}"
                    )
                if (
                    c.category == InterviewType.CASE
                    and c.share < CUSTOM_CASE_MIN_SHARE - _SHARE_TOLERANCE
                ):
                    raise ValueError(f"case needs a share of at least {CUSTOM_CASE_MIN_SHARE}")
        if InterviewType.CASE in kinds and len(kinds) > CUSTOM_CASE_MAX_CATEGORIES:
            raise ValueError("case allows at most one other category")
        stray = sorted({q.category.value for q in self.questions} - {k.value for k in kinds})
        if stray:
            raise ValueError(f"questions use categories not in the session: {', '.join(stray)}")
        texts = [" ".join(q.text.lower().split()) for q in self.questions]
        if len(texts) != len(set(texts)):
            raise ValueError("a question is listed more than once")
        return self

    def competencies(self) -> tuple[Competency, ...]:
        """The union of the categories' competencies, in category order."""
        out: dict[Competency, None] = {}
        for c in self.categories:
            out.update(dict.fromkeys(COMPETENCIES_BY_TYPE[c.category]))
        return tuple(out)


class CustomQuestionCheck(Contract):
    """CU-5: the check of one own question or focus chip before the session.

    The worker refuses the text when `is_question` is false and shows the candidate a fixed
    sentence for `refusal` with the short `reason`. Text that tries to instruct the interviewer
    is refused, never forwarded.
    """

    is_question: bool = Field(description="For a focus chip: whether it is a fair interview topic.")
    refusal: QuestionRefusal | None = Field(default=None, description="Set when refused.")
    reason: str = Field(
        default="", max_length=200, description="One short sentence the candidate sees."
    )
    category: StandardType | None = Field(default=None, description="Set when accepted.")
    competencies: list[Competency] = Field(
        default_factory=list, max_length=CUSTOM_QUESTION_MAX_COMPETENCIES
    )

    @model_validator(mode="after")
    def _check(self) -> CustomQuestionCheck:
        if self.is_question:
            if self.refusal is not None:
                raise ValueError("an accepted question has no refusal")
            if self.category is None:
                raise ValueError("an accepted question needs a category")
        elif self.refusal is None:
            raise ValueError("a refused question needs a refusal")
        return self
