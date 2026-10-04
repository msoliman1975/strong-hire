"""Contract tests for the shared Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from strong_core.config import find_repo_root
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
from strong_core.gateway.smoke import SmokeAnswer
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    EXPORTED_SCHEMAS,
    CompanyProfile,
    CompetencyScore,
    HireSignal,
    InterviewerBrief,
    InterviewType,
    SessionConfig,
    Turn,
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


def test_session_duration_is_30_or_45() -> None:
    """IV-7."""
    base = {"interview_type": "case", "difficulty": "tough", "mode": "coach", "level": "mid"}
    SessionConfig.model_validate({**base, "duration_min": 45})
    with pytest.raises(ValidationError):
        SessionConfig.model_validate({**base, "duration_min": 60})


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


def test_all_contracts_produce_json_schema() -> None:
    for model in EXPORTED_SCHEMAS.values():
        assert model.model_json_schema()["type"] == "object"


def test_fixtures_are_valid_contracts() -> None:
    """Every <OutputType>.json fixture must validate against its contract."""
    by_name = {m.__name__: m for m in [*EXPORTED_SCHEMAS.values(), SmokeAnswer]}
    files = list(Path(DEFAULT_FIXTURES_DIR).rglob("*.json"))
    assert files
    for path in files:
        by_name[path.stem].model_validate_json(path.read_text(encoding="utf-8"))
