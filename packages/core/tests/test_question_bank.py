"""Question bank contracts and the general bank loader (QB-1, QB-2, QB-5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from strong_core.config import find_repo_root
from strong_core.question_bank import QuestionBankError, load_general_bank
from strong_core.schemas import (
    GeneralQuestion,
    GeneralQuestionBank,
    InterviewType,
    QuestionHints,
    SampleQuestion,
)

REPO = find_repo_root()


def _hints() -> dict[str, Any]:
    return {
        "looking_for": ["You push back with data, not opinion"],
        "strong_signals": ["Names the stakes and the outcome"],
        "watch_outs": ["Blaming the manager"],
    }


def _question(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "disagree-with-manager",
        "interview_type": "behavioral",
        "question": "Tell me about a time you disagreed with your manager.",
        "hints": _hints(),
        "competencies": ["conflict_handling"],
    }
    data.update(overrides)
    return data


def test_qb2_hints_need_each_section() -> None:
    """QB-2: every question shows looking-for, strong signals and watch-outs."""
    assert QuestionHints.model_validate(_hints()).looking_for
    for key in ("looking_for", "strong_signals", "watch_outs"):
        with pytest.raises(ValidationError):
            QuestionHints.model_validate({**_hints(), key: []})
    with pytest.raises(ValidationError):
        QuestionHints.model_validate({**_hints(), "watch_outs": ["x"] * 5})


def test_qb1_general_question_defaults_to_every_role_family_and_level() -> None:
    """QB-1: empty role_families and levels mean the question fits all of them."""
    q = GeneralQuestion.model_validate(_question())
    assert q.interview_type is InterviewType.BEHAVIORAL
    assert q.role_families == []
    assert q.levels == []


def test_qb1_general_question_competencies_match_its_interview_type() -> None:
    """QB-1: the area filter narrows by interview type, so areas must belong to the type."""
    with pytest.raises(ValidationError, match="estimation_logic do not belong to behavioral"):
        GeneralQuestion.model_validate(_question(competencies=["estimation_logic"]))


def test_qb1_general_question_is_never_custom() -> None:
    """QB-1: questions belong to one of the four standard types; Custom is not a category."""
    with pytest.raises(ValidationError, match="custom is not a question category"):
        GeneralQuestion.model_validate(_question(interview_type="custom"))


def test_qb5_bank_rejects_duplicate_ids() -> None:
    """QB-5: ids are stable and unique."""
    with pytest.raises(ValidationError, match="duplicate question ids: disagree-with-manager"):
        GeneralQuestionBank.model_validate({"version": 1, "questions": [_question(), _question()]})


def test_qb2_sample_question_hints_and_tags_are_optional() -> None:
    """QB-2: older profiles without hints still load."""
    q = SampleQuestion.model_validate(
        {
            "interview_type": "behavioral",
            "question": "Tell me about a time you owned a problem outside your team.",
            "strong_answer": "A specific story, own actions, and a measured result.",
            "source_url": "https://example.com/interview-guide",
        }
    )
    assert q.hints is None
    assert q.role_families == []
    assert q.levels == []


def test_qb5_checked_in_general_bank_is_valid() -> None:
    """QB-5: questions/general.json matches the contract."""
    bank = load_general_bank(REPO / "questions" / "general.json")
    assert bank.version >= 1


def test_qb5_loader_reports_a_bad_file(tmp_path: Path) -> None:
    missing = tmp_path / "general.json"
    with pytest.raises(QuestionBankError, match="cannot read"):
        load_general_bank(missing)
    missing.write_text('{"version": 0}', encoding="utf-8")
    with pytest.raises(QuestionBankError, match="version"):
        load_general_bank(missing)
