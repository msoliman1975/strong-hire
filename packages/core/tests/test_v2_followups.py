"""C1 follow-ups: the brief's company summary (AP-2) and recruiter screen bank questions
(RS-1)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
from strong_core.schemas import (
    BRIEF_COMPANY_SUMMARY_MAX,
    EXPORTED_SCHEMAS,
    GeneralQuestion,
    InterviewerBrief,
    InterviewType,
)


def _brief(**extra: Any) -> dict[str, Any]:
    path = DEFAULT_FIXTURES_DIR / "planner" / "InterviewerBrief.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data | extra


def _question(**extra: Any) -> dict[str, Any]:
    hints = {"looking_for": ["a"], "strong_signals": ["b"], "watch_outs": ["c"]}
    return {
        "id": "why-this-role",
        "interview_type": "recruiter_screen",
        "question": "Why are you interested in this role?",
        "hints": hints,
        "competencies": ["motivation"],
    } | extra


def test_ap2_brief_company_summary_is_optional_and_capped() -> None:
    """AP-2: briefs without a company summary still validate; a summary has a length cap."""
    assert InterviewerBrief.model_validate(_brief()).company_summary is None
    summary = "Example Corp builds payment infrastructure."
    assert InterviewerBrief.model_validate(_brief(company_summary=summary)).company_summary
    with pytest.raises(ValidationError):
        InterviewerBrief.model_validate(
            _brief(company_summary="x" * (BRIEF_COMPANY_SUMMARY_MAX + 1))
        )


def test_rs1_bank_question_can_be_recruiter_screen_but_not_custom() -> None:
    """RS-1: a general bank question may be a recruiter screen question; never Custom."""
    q = GeneralQuestion.model_validate(_question())
    assert q.interview_type is InterviewType.RECRUITER_SCREEN
    with pytest.raises(ValidationError):
        GeneralQuestion.model_validate(_question(interview_type="custom"))
    with pytest.raises(ValidationError):  # competencies must belong to recruiter screen
        GeneralQuestion.model_validate(_question(competencies=["estimation_logic"]))


def test_rs1_bank_schema_lists_recruiter_screen() -> None:
    """RS-1: the exported JSON Schema for the bank allows recruiter_screen, not custom."""
    schema = json.dumps(EXPORTED_SCHEMAS["general_question_bank"].model_json_schema())
    assert "recruiter_screen" in schema
    assert '"custom"' not in schema
