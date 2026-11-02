"""RP-4, RP-6, RP-7: the role-play planner path and the scorer's role-play rubric."""

from __future__ import annotations

from typing import Any

import pytest

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.profiles import generic_profile
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    InterviewerBrief,
    InterviewType,
    JobPosting,
    Phase,
    Resume,
    RoleFamily,
    RolePlayDraft,
    RolePlayScenario,
    SessionConfig,
    Speaker,
    Turn,
)
from strong_worker.gap.brief import (
    assemble_role_play,
    build_brief,
    role_play_messages,
)
from strong_worker.scoring.scorer import SessionScorer, buyer_text, rubric_prompt
from strong_worker.scoring.testing import RATIONALE, ScriptedBackend, scorecard_reply

ROOT = get_settings().repo_root
INPUTS = ROOT / "evals/fixtures/inputs"
FIXTURES = ROOT / "packages/core/src/strong_core/gateway/fixtures"
POSTING = JobPosting.model_validate_json(
    (INPUTS / "postings/swe-stripe-backend.json").read_text(encoding="utf-8")
).model_copy(update={"role_family": RoleFamily.SALES, "title": "Account Executive"})
RESUME = Resume.model_validate_json(
    (INPUTS / "resumes/backend-senior.json").read_text(encoding="utf-8")
)
DRAFT = RolePlayDraft.model_validate_json(
    (FIXTURES / "planner/RolePlayDraft.json").read_text(encoding="utf-8")
)


def config(**changes: Any) -> SessionConfig:
    base: dict[str, Any] = {
        "interview_type": "role_play",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 30,
        "level": "mid",
        "role_play": "discovery_call",
    }
    return SessionConfig.model_validate(base | changes)


def fake_gateway() -> ModelGateway:
    from strong_core.gateway.fake import FakeBackend

    return ModelGateway(fake_models_config(), fake=FakeBackend())


def test_rp4_planner_prompt_asks_for_the_scenario_and_beat_count() -> None:
    """RP-4: the planner gets the scenario, the beat count and the family guidance."""
    msgs = role_play_messages(config(), POSTING, RESUME, generic_profile())
    assert msgs[0].prompt_ref == "planner/interviewer_brief_role_play.v1"
    user = msgs[1].content
    assert user.startswith("Write the buyer brief and 3 beats")
    assert "Scenario: discovery_call" in user
    assert "Role family: sales" in user
    mini = role_play_messages(config(duration_min=10), POSTING, RESUME, generic_profile())
    assert mini[1].content.startswith("Write the buyer brief and 1 beats")


async def test_rp4_build_brief_makes_a_role_play_brief() -> None:
    """RP-3, RP-4: beats become questions with hidden goals; turn limits come from code."""
    built = await build_brief(fake_gateway(), config(), POSTING, RESUME, generic_profile())
    brief = built.brief
    assert brief.role_play is not None
    assert brief.role_play.scenario == RolePlayScenario.DISCOVERY_CALL
    assert [q.id for q in brief.questions] == ["b1", "b2", "b3"]
    assert brief.questions[0].probe_hints == [DRAFT.beats[0].goal]
    assert brief.max_probes_per_question == 8
    assert set(brief.target_competencies) <= set(COMPETENCIES_BY_TYPE[InterviewType.ROLE_PLAY])
    assert brief.role_family == RoleFamily.SALES
    assert "planner/interviewer_brief_role_play.v1" in built.model_version


def test_rp4_mini_and_tough_rules() -> None:
    """RP-4, D-8: a mini keeps one beat and 6 turns; the curveball only in Tough."""
    mini, flags = assemble_role_play(
        DRAFT, config(duration_min=10), POSTING, generic_profile(), None
    )
    assert len(mini.questions) == 1 and mini.max_probes_per_question == 6
    assert "dropped_beats" in flags
    assert mini.curveball is None and mini.role_play is not None
    tough, _ = assemble_role_play(
        DRAFT, config(difficulty="tough"), POSTING, generic_profile(), None
    )
    assert tough.curveball and tough.role_play is not None
    assert tough.role_play.curveball == tough.curveball and tough.pushback
    friendly, _ = assemble_role_play(
        DRAFT, config(difficulty="friendly"), POSTING, generic_profile(), None
    )
    assert friendly.max_probes_per_question == 6 and friendly.curveball is None


def test_rp4_scenario_comes_from_the_session_not_the_model() -> None:
    """RP-4: a draft written for another scenario still gets the session's scenario."""
    cold = config(role_play="cold_call")
    brief, _ = assemble_role_play(DRAFT, cold, POSTING, generic_profile(), None)
    assert brief.role_play is not None
    assert brief.role_play.scenario == RolePlayScenario.COLD_CALL


def role_play_brief() -> InterviewerBrief:
    brief, _ = assemble_role_play(DRAFT, config(), POSTING, generic_profile(), None)
    return brief


def call_turns(brief: InterviewerBrief) -> list[Turn]:
    lines = [
        (Speaker.INTERVIEWER, brief.questions[0].text, "b1"),
        (Speaker.CANDIDATE, "Thanks Dana. How do your dispatchers plan the day today?", "b1"),
        (Speaker.INTERVIEWER, "By hand, every morning. It takes two hours.", "b1"),
        (Speaker.CANDIDATE, "Could we book a demo with your dispatch lead next Tuesday?", "b1"),
    ]
    return [
        Turn(
            speaker=s,
            phase=Phase.CORE,
            text=t,
            start_ms=i * 1000,
            end_ms=i * 1000 + 900,
            question_ref=ref,
        )
        for i, (s, t, ref) in enumerate(lines)
    ]


def test_rp7_role_play_uses_its_rubric_and_buyer_block() -> None:
    """RP-7: the role-play rubric, with the buyer brief to judge discovery and closing."""
    brief = role_play_brief()
    assert rubric_prompt(brief) == "rubric_role_play"
    text = buyer_text(brief)
    assert "Success condition: Dana agrees to a 30-minute demo" in text
    assert text.count("Hidden pain:") == 2


async def test_rp7_scorer_input_carries_the_buyer_brief() -> None:
    """RP-7: the scorer's input has the buyer brief; other types say (none)."""
    brief = role_play_brief()
    turns = call_turns(brief)
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    outcome = await SessionScorer(ModelGateway(fake_models_config(), fake=backend)).score(
        brief, turns, generic_profile()
    )
    assert outcome.scorecard.rubric_version == "scorer/rubric_role_play.v1"
    rubric_input = backend.calls[0][0][1].content
    assert "Buyer brief (role-play only" in rubric_input
    assert "Hidden pain: Dispatchers rebuild" in rubric_input


@pytest.mark.parametrize("kind", ["behavioral"])
def test_rp7_other_types_have_no_buyer_block(kind: str) -> None:
    from strong_interview.testing import make_brief

    assert buyer_text(make_brief()) == "(none)"
