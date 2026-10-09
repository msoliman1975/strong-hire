"""Contract tests for the shared Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from strong_core.config import find_repo_root
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR, read_recording
from strong_core.gateway.smoke import SmokeAnswer
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    EXPORTED_SCHEMAS,
    CompanyProfile,
    CompetencyScore,
    HireSignal,
    InterviewerBrief,
    InterviewType,
    Scorecard,
    SessionConfig,
    Turn,
    ValueScore,
)

REPO = find_repo_root()


def test_hire_signal_values_match_spec() -> None:
    """FB-1: five bands, strongest first."""
    assert [s.value for s in HireSignal] == [
        "Strong Hire",
        "Hire",
        "Lean Hire",
        "Lean No Hire",
        "No Hire",
    ]
    assert HireSignal.STRONG_HIRE.rank == 0
    assert HireSignal.NO_HIRE.rank == 4


def test_every_interview_type_has_competencies() -> None:
    """IV-2: four interview types, each with scored competencies."""
    assert set(COMPETENCIES_BY_TYPE) == set(InterviewType)
    assert all(len(c) >= 5 for c in COMPETENCIES_BY_TYPE.values())


@pytest.mark.parametrize("score", [0, 5])
def test_rubric_score_is_1_to_4(score: int) -> None:
    with pytest.raises(ValidationError):
        CompetencyScore(competency="ownership", score=score, justification="x", quotes=["y"])


def test_competency_score_needs_a_quote() -> None:
    with pytest.raises(ValidationError):
        CompetencyScore(competency="ownership", score=3, justification="x", quotes=[])


def test_session_duration_is_10_30_or_45() -> None:
    """IV-7. 10 minutes is the mini interview."""
    base = {"interview_type": "case", "difficulty": "tough", "mode": "coach", "level": "mid"}
    SessionConfig.model_validate({**base, "duration_min": 45})
    assert SessionConfig.model_validate({**base, "duration_min": 10}).is_mini
    assert not SessionConfig.model_validate({**base, "duration_min": 30}).is_mini
    for bad in (60, 15):
        with pytest.raises(ValidationError):
            SessionConfig.model_validate({**base, "duration_min": bad})


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Turn.model_validate(
            {
                "speaker": "candidate",
                "phase": "core",
                "text": "hi",
                "start_ms": 0,
                "end_ms": 1,
                "x": 1,
            }
        )


def test_turn_end_after_start() -> None:
    with pytest.raises(ValidationError):
        Turn(speaker="candidate", phase="core", text="hi", start_ms=10, end_ms=5)


def _brief() -> dict[str, object]:
    path = DEFAULT_FIXTURES_DIR / "planner" / "InterviewerBrief.json"
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_brief_company_mode_records_profile_version() -> None:
    """IN-5 and spec pipeline step 5: sessions record the profile version used."""
    data = _brief() | {"generic_mode": False, "company_name": "Example Corp"}
    with pytest.raises(ValidationError, match="profile_version"):
        InterviewerBrief.model_validate(data)
    InterviewerBrief.model_validate(data | {"profile_version": 3})


def test_brief_curveball_only_in_tough() -> None:
    """IV-4."""
    with pytest.raises(ValidationError, match="curveball"):
        InterviewerBrief.model_validate(_brief() | {"curveball": "Why not a queue?"})


def test_brief_probe_cap_is_3() -> None:
    """IV-3."""
    with pytest.raises(ValidationError):
        InterviewerBrief.model_validate(_brief() | {"max_probes_per_question": 4})


def _mini_brief(**extra: object) -> dict[str, Any]:
    data: dict[str, Any] = _brief()
    session = {**data["session"], "duration_min": 10}
    return data | {
        "session": session,
        "questions": data["questions"][:3],
        "target_competencies": data["target_competencies"][:2],
        "max_probes_per_question": 1,
        "time_plan": [],
        **extra,
    }


def test_mini_brief_has_3_questions_and_at_most_1_probe() -> None:
    """IV-3, IV-4 in a mini: 3 questions and 2 competencies are enough; 1 probe; no curveball."""
    data = _mini_brief()
    for q in data["questions"]:
        q["competencies"] = data["target_competencies"][:1]
    InterviewerBrief.model_validate(data)
    with pytest.raises(ValidationError, match="probe"):
        InterviewerBrief.model_validate(data | {"max_probes_per_question": 2})
    tough = {**data["session"], "difficulty": "tough"}
    with pytest.raises(ValidationError, match="curveball"):
        InterviewerBrief.model_validate(data | {"session": tough, "curveball": "Why not?"})


def test_full_brief_still_needs_6_questions_and_4_competencies() -> None:
    data = _brief()
    questions: list[Any] = data["questions"]  # type: ignore[assignment]
    with pytest.raises(ValidationError, match="6 questions"):
        InterviewerBrief.model_validate(data | {"questions": questions[:3]})
    comps: list[Any] = data["target_competencies"]  # type: ignore[assignment]
    with pytest.raises(ValidationError, match="4 target competencies"):
        InterviewerBrief.model_validate(data | {"target_competencies": comps[:2]})


def test_example_profile_is_valid() -> None:
    """AD-1: the example profile validates against the contract."""
    for path in (REPO / "profiles").rglob("*.json"):
        CompanyProfile.model_validate_json(path.read_text(encoding="utf-8"))


def test_profile_requires_confidence_for_every_field() -> None:
    path = REPO / "profiles" / "examples" / "example-corp.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["field_confidence"]["persona"]
    with pytest.raises(ValidationError, match="persona"):
        CompanyProfile.model_validate(data)


def _profile() -> dict[str, Any]:
    path = REPO / "profiles" / "examples" / "example-corp.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_iv5_profile_question_patterns_name_known_values() -> None:
    """IV-5: question patterns point at values from the profile's values framework."""
    profile = CompanyProfile.model_validate(_profile())
    assert profile.value_names == ["Customer first", "Own the outcome"]
    assert profile.question_patterns[0].values == ["Own the outcome"]

    data = _profile()
    data["question_patterns"][0]["values"] = ["Move fast"]
    with pytest.raises(ValidationError, match="unknown values: Move fast"):
        CompanyProfile.model_validate(data)


def test_iv5_profile_value_names_are_unique() -> None:
    data = _profile()
    principles = data["values_framework"]["principles"]
    principles.append(dict(principles[0]))
    with pytest.raises(ValidationError, match="unique"):
        CompanyProfile.model_validate(data)


@pytest.mark.parametrize(("field", "value"), [("values_share", 0.6), ("values_share", -0.1)])
def test_profile_values_share_is_0_to_half(field: str, value: float) -> None:
    with pytest.raises(ValidationError, match=field):
        CompanyProfile.model_validate(_profile() | {field: value})


def test_profile_value_weight_is_positive() -> None:
    data = _profile()
    data["values_framework"]["principles"][0]["weight"] = 0
    with pytest.raises(ValidationError, match="weight"):
        CompanyProfile.model_validate(data)


def test_profile_value_defaults() -> None:
    """Older profile files without the value fields still validate."""
    data = _profile()
    del data["values_share"]
    for principle in data["values_framework"]["principles"]:
        principle.pop("weight", None)
    for pattern in data["question_patterns"]:
        pattern.pop("values", None)
    profile = CompanyProfile.model_validate(data)
    assert profile.values_share == 0.25
    assert all(p.weight == 1.0 for p in profile.values_framework.principles)


def _company_brief(target_values: list[str], question_values: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = _brief() | {
        "generic_mode": False,
        "company_name": "Example Corp",
        "profile_version": 1,
        "target_values": target_values,
    }
    data["questions"] = [dict(q) for q in data["questions"]]
    data["questions"][0]["values"] = question_values
    return data


def test_iv5_company_brief_targets_values() -> None:
    """IV-5: a company brief lists the values to probe, and each question names its values."""
    brief = InterviewerBrief.model_validate(
        _company_brief(["Own the outcome", "Customer first"], ["Own the outcome"])
    )
    assert brief.target_values == ["Own the outcome", "Customer first"]
    assert brief.questions[0].values == ["Own the outcome"]


def test_iv5_brief_questions_use_only_target_values() -> None:
    with pytest.raises(ValidationError, match="not in target_values: Customer first"):
        InterviewerBrief.model_validate(_company_brief(["Own the outcome"], ["Customer first"]))


def test_brief_at_most_4_target_values() -> None:
    with pytest.raises(ValidationError, match="target_values"):
        InterviewerBrief.model_validate(_company_brief(["a", "b", "c", "d", "e"], []))


def test_generic_brief_has_no_values() -> None:
    """IN-5 generic mode: no company values to probe."""
    assert InterviewerBrief.model_validate(_brief()).target_values == []
    with pytest.raises(ValidationError, match="target_values"):
        InterviewerBrief.model_validate(_brief() | {"target_values": ["Own the outcome"]})


def _scorecard() -> dict[str, Any]:
    path = DEFAULT_FIXTURES_DIR / "scorer" / "Scorecard.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_fb2_scorecard_value_scores() -> None:
    """FB-2: value scores use the same 1 to 4 rubric, with quotes. Empty in generic mode."""
    assert Scorecard.model_validate(_scorecard()).value_scores == []
    score = {"value": "Own the outcome", "score": 3, "justification": "x", "quotes": ["y"]}
    card = Scorecard.model_validate(_scorecard() | {"value_scores": [score]})
    assert card.value_scores == [ValueScore.model_validate(score)]
    with pytest.raises(ValidationError, match="one entry per value"):
        Scorecard.model_validate(_scorecard() | {"value_scores": [score, score]})
    with pytest.raises(ValidationError):
        ValueScore.model_validate(score | {"quotes": []})
    with pytest.raises(ValidationError):
        ValueScore.model_validate(score | {"score": 5})


def test_all_contracts_produce_json_schema() -> None:
    for model in EXPORTED_SCHEMAS.values():
        assert model.model_json_schema()["type"] == "object"


def test_fixtures_are_valid_contracts() -> None:
    """Every <OutputType>.json fixture and every recorded output must validate."""
    by_name = {m.__name__: m for m in [*EXPORTED_SCHEMAS.values(), SmokeAnswer]}
    files = list(Path(DEFAULT_FIXTURES_DIR).rglob("*.json"))
    assert files
    for path in files:
        recorded = read_recording(path)
        if recorded is not None:
            if recorded.output_type is not None:
                by_name[recorded.output_type].model_validate(recorded.output)
            continue
        by_name[path.stem].model_validate_json(path.read_text(encoding="utf-8"))


def test_iv3_probe_decision_is_a_constrained_choice() -> None:
    """IV-3: the probe decision allows only probe or move_on, with known triggers."""
    from strong_core.schemas import ProbeDecision, ProbeTrigger

    ok = ProbeDecision.model_validate({"action": "probe", "missing": ["own_role"]})
    assert ok.missing == [ProbeTrigger.OWN_ROLE]
    assert ProbeDecision.model_validate({"action": "move_on"}).missing == []
    for bad in (
        {"action": "ask_again"},
        {"action": "probe", "missing": ["vibes"]},
        {"action": "probe", "reason": "extra field"},
    ):
        with pytest.raises(ValidationError):
            ProbeDecision.model_validate(bad)


def test_in6_in7_input_check_is_a_constrained_choice() -> None:
    """IN-6, IN-7: the input check names a known document kind and a short reason."""
    from strong_core.schemas import DocumentKind, InputCheck

    ok = InputCheck.model_validate({"matches": False, "looks_like": "job_list", "reason": "x"})
    assert ok.looks_like == DocumentKind.JOB_LIST
    for bad in (
        {"matches": True, "looks_like": "poem"},
        {"matches": True, "looks_like": "resume", "reason": "x" * 201},
        {"matches": True, "looks_like": "resume", "advice": "extra field"},
    ):
        with pytest.raises(ValidationError):
            InputCheck.model_validate(bad)


def test_iv10_answer_check_is_a_constrained_choice() -> None:
    """IV-10: the answer check allows only ok, off_scope or inappropriate."""
    from strong_core.schemas import AnswerCheck, AnswerConduct

    assert AnswerCheck.model_validate({"conduct": "off_scope"}).conduct == AnswerConduct.OFF_SCOPE
    for bad in ({"conduct": "rude"}, {"conduct": "ok", "warn": True}):
        with pytest.raises(ValidationError):
            AnswerCheck.model_validate(bad)
