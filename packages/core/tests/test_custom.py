"""Custom interview contracts (docs/custom-interview-spec.md, CU-1 to CU-5)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR as FIXTURES_DIR
from strong_core.schemas import (
    BriefQuestion,
    CompanyProfile,
    Competency,
    CustomQuestionCheck,
    CustomSessionSpec,
    InterviewerBrief,
    InterviewType,
    QuestionRefusal,
    QuestionSource,
    SessionConfig,
    session_competencies,
)


def spec(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "categories": [
            {"category": "behavioral", "share": 0.5, "focus": ["conflict"]},
            {"category": "technical_qa", "share": 0.5, "focus": ["Kubernetes"]},
        ],
        "questions": [
            {
                "text": "Tell me about a time you disagreed with your manager.",
                "category": "behavioral",
                "competencies": ["conflict_handling"],
            }
        ],
    }
    base.update(over)
    return base


def config(duration: int = 30, **over: Any) -> dict[str, Any]:
    return {
        "interview_type": "custom",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": duration,
        "level": "senior",
        "custom": spec(**over),
    }


def test_cu1_custom_session_mixes_up_to_three_categories() -> None:
    cfg = SessionConfig.model_validate(config())
    assert cfg.is_custom
    assert cfg.custom is not None
    assert cfg.custom.questions[0].must_ask  # CU-4: on by default
    assert not cfg.custom.questions[0].verbatim
    four = [
        {"category": c, "share": 0.25}
        for c in ("behavioral", "technical_qa", "hiring_manager", "case")
    ]
    with pytest.raises(ValidationError, match="at most 3"):
        CustomSessionSpec.model_validate(spec(categories=four, questions=[]))


def test_cu1_custom_is_not_a_question_category() -> None:
    with pytest.raises(ValidationError, match="not a question category"):
        CustomSessionSpec.model_validate(
            spec(categories=[{"category": "custom", "share": 1}], questions=[])
        )


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"categories": [{"category": "behavioral", "share": 0.7}]}, "add up to"),
        (
            {
                "categories": [
                    {"category": "behavioral", "share": 0.95},
                    {"category": "technical_qa", "share": 0.05},
                ]
            },
            "at least",
        ),
        (
            {
                "categories": [
                    {"category": "behavioral", "share": 0.5},
                    {"category": "behavioral", "share": 0.5},
                ]
            },
            "more than once",
        ),
    ],
)
def test_cu1_category_shares(over: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        CustomSessionSpec.model_validate(spec(questions=[], **over))


def test_cu1_case_needs_45_minutes_and_one_other_category_at_most() -> None:
    """D-3."""
    case = [
        {"category": "case", "share": 0.6},
        {"category": "behavioral", "share": 0.4},
    ]
    SessionConfig.model_validate(config(duration=45, categories=case, questions=[]))
    with pytest.raises(ValidationError, match="45-minute"):
        SessionConfig.model_validate(config(duration=30, categories=case, questions=[]))
    three = [
        {"category": "case", "share": 0.5},
        {"category": "behavioral", "share": 0.25},
        {"category": "technical_qa", "share": 0.25},
    ]
    with pytest.raises(ValidationError, match="at most one other"):
        CustomSessionSpec.model_validate(spec(categories=three, questions=[]))
    small_case = [
        {"category": "case", "share": 0.3},
        {"category": "behavioral", "share": 0.7},
    ]
    with pytest.raises(ValidationError, match="case needs a share"):
        CustomSessionSpec.model_validate(spec(categories=small_case, questions=[]))


def test_cu1_custom_setup_only_on_custom_sessions_and_never_mini() -> None:
    """D-14: no mini Custom interview."""
    with pytest.raises(ValidationError, match="needs a custom setup"):
        SessionConfig.model_validate({**config(), "custom": None})
    with pytest.raises(ValidationError, match="only a custom session"):
        SessionConfig.model_validate({**config(), "interview_type": "behavioral"})
    with pytest.raises(ValidationError, match="mini"):
        SessionConfig.model_validate(config(duration=10))


def test_cu2_focus_chips_are_short() -> None:
    long = [{"category": "behavioral", "share": 1, "focus": ["x" * 61]}]
    with pytest.raises(ValidationError):
        CustomSessionSpec.model_validate(spec(categories=long, questions=[]))


def _question(i: int) -> dict[str, Any]:
    return {
        "text": f"Question number {i}?",
        "category": "behavioral",
        "competencies": ["ownership"],
    }


def test_cu3_own_question_caps_by_duration() -> None:
    """D-5: 5 in 30 minutes, 8 in 45."""
    SessionConfig.model_validate(config(duration=30, questions=[_question(i) for i in range(5)]))
    with pytest.raises(ValidationError, match="allows 5"):
        SessionConfig.model_validate(
            config(duration=30, questions=[_question(i) for i in range(6)])
        )
    SessionConfig.model_validate(config(duration=45, questions=[_question(i) for i in range(8)]))
    with pytest.raises(ValidationError):
        SessionConfig.model_validate(
            config(duration=45, questions=[_question(i) for i in range(9)])
        )


def test_cu3_question_competencies_belong_to_its_category() -> None:
    bad = {**_question(1), "competencies": ["technical_depth"]}
    with pytest.raises(ValidationError, match="do not belong"):
        CustomSessionSpec.model_validate(spec(questions=[bad]))
    stray = {**_question(1), "category": "case", "competencies": ["structure"]}
    with pytest.raises(ValidationError, match="not in the session"):
        CustomSessionSpec.model_validate(spec(questions=[stray]))


def test_cu5_duplicate_questions_are_refused() -> None:
    a = _question(1)
    b = {**a, "text": "  question NUMBER 1? "}
    with pytest.raises(ValidationError, match="more than once"):
        CustomSessionSpec.model_validate(spec(questions=[a, b]))


def test_cu5_question_check_contract() -> None:
    ok = CustomQuestionCheck(
        is_question=True, category=InterviewType.BEHAVIORAL, competencies=[Competency.IMPACT]
    )
    assert ok.refusal is None
    refused = CustomQuestionCheck(
        is_question=False, refusal=QuestionRefusal.INSTRUCTIONS, reason="It gives orders."
    )
    assert refused.category is None
    with pytest.raises(ValidationError, match="needs a refusal"):
        CustomQuestionCheck(is_question=False)
    with pytest.raises(ValidationError, match="needs a category"):
        CustomQuestionCheck(is_question=True)


def test_cu5_question_check_fixture_validates() -> None:
    path = FIXTURES_DIR / "extractor" / "CustomQuestionCheck.json"
    CustomQuestionCheck.model_validate_json(path.read_text(encoding="utf-8"))


def test_cu6_session_competencies_union_the_categories() -> None:
    cfg = SessionConfig.model_validate(config())
    comps = session_competencies(cfg)
    assert Competency.CONFLICT_HANDLING in comps
    assert Competency.TECHNICAL_DEPTH in comps
    assert Competency.ROLE_FIT not in comps
    std = SessionConfig.model_validate({**config(), "interview_type": "behavioral", "custom": None})
    assert Competency.TECHNICAL_DEPTH not in session_competencies(std)


def _brief(cfg: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    path = FIXTURES_DIR / "planner" / "InterviewerBrief.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    data["session"] = cfg
    data["questions"] = questions
    data["time_plan"] = []
    data["curveball"] = None
    data["pushback"] = False
    data["coach_help"] = False
    return data


def _bq(i: int, **over: Any) -> dict[str, Any]:
    q: dict[str, Any] = {
        "id": f"q{i}",
        "text": f"Question {i}?",
        "competencies": ["ownership"],
        "priority": i,
    }
    q.update(over)
    return q


def test_cu4_brief_carries_own_questions_with_categories() -> None:
    questions = [_bq(1, source="candidate", category="behavioral", must_ask=True, verbatim=True)]
    questions += [_bq(i, category="technical_qa") for i in range(2, 8)]
    brief = InterviewerBrief.model_validate(_brief(config(), questions))
    own = brief.questions[0]
    assert own.source == QuestionSource.CANDIDATE
    assert own.must_ask
    assert own.verbatim
    assert brief.questions[1].source == QuestionSource.PLANNER

    questions[1] = _bq(2)  # no category
    with pytest.raises(ValidationError, match="needs a category"):
        InterviewerBrief.model_validate(_brief(config(), questions))
    questions[1] = _bq(2, category="case")
    with pytest.raises(ValidationError, match="needs a category"):
        InterviewerBrief.model_validate(_brief(config(), questions))


def test_cu4_must_ask_and_verbatim_only_on_own_questions() -> None:
    with pytest.raises(ValidationError, match="own questions"):
        BriefQuestion.model_validate(_bq(1, must_ask=True))
    standard = {**config(), "interview_type": "behavioral", "custom": None}
    with pytest.raises(ValidationError, match="custom sessions only"):
        InterviewerBrief.model_validate(
            _brief(standard, [_bq(i, category="behavioral") for i in range(1, 8)])
        )


def test_profiles_never_use_the_custom_type() -> None:
    """Company sample questions and loop rounds name one of the four standard types."""
    assert '"custom"' not in json.dumps(CompanyProfile.model_json_schema())
