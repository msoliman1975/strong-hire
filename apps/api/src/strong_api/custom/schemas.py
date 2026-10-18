"""Request and response bodies for the Custom interview API (CU-2, CU-5, CU-8, CU-9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import Competency, QuestionRefusal, StandardType
from strong_core.schemas.custom import CUSTOM_QUESTION_MAX_COMPETENCIES, CUSTOM_QUESTION_MAX_LEN

CHECK_MAX_INPUT = 2000
"""Longer text is refused by validation (422). Text over the question or chip limit but under
this gets a polite refusal instead."""
CHECK_MAX_EXISTING = 20


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- CU-5 check -----------------------------------------------------------------------------


class QuestionCheckRequest(_In):
    text: str = Field(max_length=CHECK_MAX_INPUT, description="The question or focus chip.")
    kind: Literal["question", "focus"] = Field(
        default="question", description="An own question, or a free-text focus chip (CU-2)."
    )
    category: StandardType | None = Field(
        default=None,
        description="The category the candidate chose. When set, it wins over the model's tag.",
    )
    existing: list[str] = Field(
        default_factory=list,
        max_length=CHECK_MAX_EXISTING,
        description="The other questions (or chips) already in the session, for the duplicate "
        "flag.",
    )


class QuestionCheckOut(_Out):
    accepted: bool
    refusal: QuestionRefusal | None = Field(description="Set when not accepted.")
    reason: str = Field(
        description="Empty when accepted. Else a fixed sentence for the refusal, then the "
        "model's short reason when there is one."
    )
    category: StandardType | None = Field(description="Set when accepted.")
    competencies: list[Competency] = Field(
        description="1 to 3 competencies of `category` when accepted, else empty."
    )
    duplicate_of: int | None = Field(
        description="Index in `existing` of a near-duplicate (CU-5), else null. A flag only."
    )


# --- CU-2 focus chips -----------------------------------------------------------------------


class CategoryFocus(_Out):
    suggested: list[str] = Field(description="Every suggested chip, best first, at most 8.")
    preselected: list[str] = Field(description="The chips to select by default, a subset.")


class FocusSuggestions(_Out):
    """Suggested focus chips per standard category (CU-2)."""

    job_target_id: uuid.UUID
    gap_analysis_id: uuid.UUID | None = Field(
        description="The ready gap analysis the chips came from, null when there is none."
    )
    behavioral: CategoryFocus
    technical_qa: CategoryFocus
    hiring_manager: CategoryFocus
    case: CategoryFocus


# --- CU-8 saved questions -------------------------------------------------------------------


class SavedQuestionIn(_In):
    text: str = Field(min_length=1, max_length=CUSTOM_QUESTION_MAX_LEN)
    category: StandardType
    competencies: list[Competency] = Field(
        min_length=1,
        max_length=CUSTOM_QUESTION_MAX_COMPETENCIES,
        description="From COMPETENCIES_BY_TYPE for the category.",
    )
    bank_ref: str | None = Field(
        default=None, max_length=200, description="Question bank id when added from the bank."
    )


class SavedQuestionPatch(_In):
    text: str | None = Field(default=None, min_length=1, max_length=CUSTOM_QUESTION_MAX_LEN)
    category: StandardType | None = None
    competencies: list[Competency] | None = Field(
        default=None, min_length=1, max_length=CUSTOM_QUESTION_MAX_COMPETENCIES
    )


class SavedQuestionOut(_Out):
    id: uuid.UUID
    text: str
    category: StandardType
    competencies: list[Competency]
    bank_ref: str | None
    created_at: datetime
    updated_at: datetime
