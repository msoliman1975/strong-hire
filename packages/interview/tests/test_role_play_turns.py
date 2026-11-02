"""RP-5, RP-6: the live interviewer plays the buyer from the hidden buyer brief."""

from __future__ import annotations

from strong_core.gateway import ModelGateway
from strong_core.schemas import COMPETENCIES_BY_TYPE, InterviewerBrief, InterviewType, Phase
from strong_interview.controller import Move, MoveKind
from strong_interview.interviewer import Interviewer, buyer_text
from strong_interview.testing import make_brief

BUYER = {
    "scenario": "discovery_call",
    "persona_name": "Dana Ruiz",
    "persona_title": "VP of Operations",
    "company_summary": "A freight broker with 300 staff.",
    "product": "A dispatch scheduling tool",
    "product_illustrative": True,
    "situation": "Dana booked the call after a webinar.",
    "hidden_pains": ["Dispatchers rebuild the schedule by hand every morning"],
    "budget": "About 40,000 dollars a year",
    "decision_process": "Dana decides with the CFO",
    "objections": [{"text": "We tried a tool and nobody used it.", "when": "early"}],
    "success_condition": "Dana agrees to a demo next week",
}


def role_play_brief() -> InterviewerBrief:
    base = make_brief().model_dump(mode="json")
    base["session"] |= {"interview_type": "role_play", "role_play": "discovery_call"}
    base["questions"] = [
        {
            "id": "b1",
            "text": "Hi, what's this about?",
            "competencies": ["discovery"],
            "priority": 1,
            "probe_hints": ["Ask about the current process"],
        },
        {
            "id": "b2",
            "text": "What would it cost?",
            "competencies": ["objection_handling"],
            "priority": 2,
            "probe_hints": ["Handle the price objection"],
        },
    ]
    base["target_competencies"] = [c.value for c in COMPETENCIES_BY_TYPE[InterviewType.ROLE_PLAY]]
    base["max_probes_per_question"] = 8
    base["role_play"] = BUYER
    base["curveball"] = None
    base["pushback"] = False
    return InterviewerBrief.model_validate(base)


def test_rp5_role_play_turn_prompt_carries_the_buyer(gateway: ModelGateway) -> None:
    """RP-5: the system prompt is the role-play one and holds the hidden buyer brief."""
    interviewer = Interviewer(gateway, role_play_brief())
    system, _ = interviewer.turn_messages(Move(MoveKind.GREET, Phase.INTRO), [])
    assert system.prompt_ref == "interviewer/turn_role_play.v1"
    assert "Dana Ruiz, VP of Operations" in system.content
    assert "Hidden pain (say it only when asked about it): Dispatchers rebuild" in system.content
    assert "A good seller earns: Dana agrees to a demo next week" in system.content
    assert "(illustrative)" in system.content


def test_rp5_other_types_keep_their_turn_prompt(gateway: ModelGateway) -> None:
    """RP-5: a behavioral session never sees a buyer."""
    system, _ = Interviewer(gateway, make_brief()).turn_messages(
        Move(MoveKind.GREET, Phase.INTRO), []
    )
    assert system.prompt_ref is not None and system.prompt_ref.startswith("interviewer/turn.v")
    assert buyer_text(make_brief()) == "none"
    assert "Dana" not in system.content


async def test_rp6_decide_uses_the_role_play_prompt(gateway: ModelGateway) -> None:
    """RP-6: the follow-up decision for a beat uses the role-play triggers."""
    brief = role_play_brief()
    interviewer = Interviewer(gateway, brief)
    await interviewer.decide(brief.questions[0], "We have a great tool for you.", [])
    assert interviewer.last_call is not None
    assert "interviewer/decide_role_play.v1" in interviewer.last_call.prompt_refs
