"""RP-1 to RP-3: the role-play type, the sales family and the buyer brief contract."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from strong_core.role_families import family_info
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    ROLE_PLAY_ONLY_COMPETENCIES,
    STORY_SKILLS,
    Competency,
    InterviewerBrief,
    InterviewType,
    RoleFamily,
    RolePlayDraft,
    RolePlayScenario,
    SessionConfig,
)

RP = InterviewType.ROLE_PLAY


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


def buyer(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "scenario": "discovery_call",
        "persona_name": "Dana Ruiz",
        "persona_title": "VP of Operations",
        "company_summary": "A freight broker with 300 staff in three offices.",
        "product": "A dispatch scheduling tool",
        "situation": "Dana took the call after a webinar about late shipments.",
        "hidden_pains": ["Dispatchers rebuild the schedule by hand every morning"],
        "budget": "About 40,000 dollars a year, not yet approved",
        "decision_process": "Dana decides with the CFO; IT reviews security",
        "objections": [{"text": "We tried a tool like this and nobody used it.", "when": "early"}],
        "success_condition": "Dana agrees to a demo with her dispatch lead next week",
    }
    return base | changes


def beat(i: int) -> dict[str, Any]:
    return {
        "id": f"beat-{i}",
        "text": "So, what is this about?",
        "competencies": ["discovery"],
        "priority": i,
    }


def brief(cfg: SessionConfig, *, beats: int = 3, probes: int = 6, **changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session": cfg.model_dump(mode="json"),
        "generic_mode": True,
        "target_competencies": [c.value for c in COMPETENCIES_BY_TYPE[RP]],
        "questions": [beat(i) for i in range(1, beats + 1)],
        "persona": {"tone": "Neutral", "pushback_style": "Plain", "closing_style": "Short"},
        "max_probes_per_question": probes,
        "role_play": buyer(scenario=cfg.role_play.value if cfg.role_play else "discovery_call"),
    }
    return base | changes


def test_rp1_role_play_type_and_competencies() -> None:
    """RP-1, D-6: role-play scores its four new competencies and communication."""
    assert set(COMPETENCIES_BY_TYPE[RP]) == {*ROLE_PLAY_ONLY_COMPETENCIES, Competency.COMMUNICATION}
    for kind, comps in COMPETENCIES_BY_TYPE.items():
        if kind != RP:
            assert not set(comps) & set(ROLE_PLAY_ONLY_COMPETENCIES)


def test_rp1_story_skills_leave_out_role_play_competencies() -> None:
    """RP-1: the coach and stories never offer a skill only a live call shows."""
    assert not set(STORY_SKILLS) & set(ROLE_PLAY_ONLY_COMPETENCIES)
    assert set(STORY_SKILLS) | set(ROLE_PLAY_ONLY_COMPETENCIES) == set(Competency)


def test_rp4_role_play_session_needs_a_scenario_and_others_have_none() -> None:
    """RP-4, D-5: a role-play names its scenario; no other type may."""
    assert config().role_play == RolePlayScenario.DISCOVERY_CALL
    with pytest.raises(ValidationError, match="role_play scenario"):
        config(role_play=None)
    with pytest.raises(ValidationError, match="role_play scenario"):
        config(interview_type="behavioral")


def test_rp3_brief_holds_the_buyer_and_its_beats() -> None:
    """RP-3: a role-play brief has a buyer brief, 2 to 4 beats, and up to 8 buyer turns."""
    ok = InterviewerBrief.model_validate(brief(config(), probes=8))
    assert ok.role_play is not None and ok.role_play.persona_name == "Dana Ruiz"
    for bad, match in (
        ({"role_play": None}, "needs a buyer brief"),
        ({"questions": [beat(1)]}, "2 to 4 beats"),
        ({"max_probes_per_question": 9}, "less than or equal to 8"),
    ):
        with pytest.raises(ValidationError, match=match):
            InterviewerBrief.model_validate(brief(config()) | bad)
    mismatch = brief(config()) | {"role_play": buyer(scenario="cold_call")}
    with pytest.raises(ValidationError, match="scenario"):
        InterviewerBrief.model_validate(mismatch)


def test_rp3_mini_role_play_has_one_beat_and_curveball_needs_tough() -> None:
    """RP-4, D-8: a mini has one beat and at most 6 buyer turns; the curveball is Tough only."""
    mini = config(duration_min=10)
    InterviewerBrief.model_validate(brief(mini, beats=1, probes=6))
    with pytest.raises(ValidationError, match="one beat"):
        InterviewerBrief.model_validate(brief(mini, beats=2))
    with pytest.raises(ValidationError, match="6 buyer turns"):
        InterviewerBrief.model_validate(brief(mini, beats=1, probes=7))
    curve = brief(config()) | {"role_play": buyer(curveball="We just renewed with a competitor.")}
    with pytest.raises(ValidationError, match="Tough"):
        InterviewerBrief.model_validate(curve)
    InterviewerBrief.model_validate(
        brief(config(difficulty="tough"))
        | {"role_play": buyer(curveball="We just renewed with a competitor.")}
    )


def test_rp3_other_types_keep_their_limits_and_have_no_buyer() -> None:
    """RP-3: the other types still cap follow-ups at 3 and never carry a buyer brief."""
    beh = SessionConfig.model_validate(
        {
            "interview_type": "behavioral",
            "difficulty": "realistic",
            "mode": "realistic",
            "duration_min": 10,
            "level": "mid",
        }
    )
    base = brief(beh, beats=3, probes=1) | {
        "target_competencies": ["ownership", "impact"],
        "role_play": None,
    }
    InterviewerBrief.model_validate(base)
    with pytest.raises(ValidationError, match="only a role-play"):
        InterviewerBrief.model_validate(base | {"role_play": buyer()})
    full = SessionConfig.model_validate(beh.model_dump() | {"duration_min": 30})
    with pytest.raises(ValidationError, match="at most 3 probes"):
        InterviewerBrief.model_validate(
            brief(full, beats=6, probes=4)
            | {
                "role_play": None,
                "target_competencies": ["ownership", "impact", "collaboration", "communication"],
            }
        )


def test_rp4_planner_draft_contract() -> None:
    """RP-4: the planner returns a buyer brief and 1 to 4 beats."""
    draft = RolePlayDraft.model_validate(
        {
            "buyer": buyer(),
            "beats": [
                {
                    "id": "open",
                    "opening": "Hi, I have ten minutes. What's this about?",
                    "goal": "Earn the right to ask questions",
                    "competencies": ["discovery"],
                }
            ],
        }
    )
    assert draft.beats[0].goal.startswith("Earn")
    with pytest.raises(ValidationError):
        RolePlayDraft.model_validate({"buyer": buyer(), "beats": []})


def test_rp2_sales_family_registry_entry() -> None:
    """RP-2, D-10: sales leads with a recruiter screen and the role-play; Strova plays the buyer."""
    info = family_info(RoleFamily.SALES)
    assert info.label == "Sales"
    assert info.generic_loop == (
        InterviewType.RECRUITER_SCREEN,
        InterviewType.ROLE_PLAY,
        InterviewType.HIRING_MANAGER,
    )
    assert info.interviewer_title(InterviewType.ROLE_PLAY) == "Buyer"
    assert {"account executive", "sdr", "sales engineer"} <= set(info.title_keywords)


def test_rp12_question_bank_has_sales_questions_and_scenario_cards() -> None:
    """RP-12: at least 15 general sales questions (behavioral and hiring manager) and at least
    8 role-play scenario cards, two or more per call type."""
    from collections import Counter

    from strong_core.config import find_repo_root
    from strong_core.schemas import GeneralQuestionBank

    path = find_repo_root() / "questions" / "general.json"
    bank = GeneralQuestionBank.model_validate_json(path.read_text(encoding="utf-8"))
    sales = [q for q in bank.questions if RoleFamily.SALES in q.role_families]
    by_type = Counter(q.interview_type for q in sales)
    general = by_type[InterviewType.BEHAVIORAL] + by_type[InterviewType.HIRING_MANAGER]
    assert general >= 15, by_type
    assert by_type[InterviewType.BEHAVIORAL] >= 3 and by_type[InterviewType.HIRING_MANAGER] >= 3
    cards = [q for q in bank.questions if q.interview_type == RP]
    assert len(cards) >= 8
    calls = Counter(q.question.split(":", 1)[0] for q in cards)
    assert set(calls) == {"Cold call", "Discovery call", "Demo", "Negotiation", "Close"}
