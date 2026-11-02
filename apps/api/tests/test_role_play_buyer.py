"""RP-8, RP-9: the API shows who Strova plays, and the hidden buyer brief only after the call."""

from __future__ import annotations

from typing import Any

import pytest

from strong_api.scoring.router import _buyer
from strong_core.db.models import InterviewSession
from strong_core.schemas import SessionStatus

BUYER: dict[str, Any] = {
    "scenario": "discovery_call",
    "persona_name": "Dana Ruiz",
    "persona_title": "VP of Operations",
    "company_summary": "A freight broker with 300 staff.",
    "product": "A dispatch scheduling tool",
    "situation": "Dana booked the call after a webinar.",
    "hidden_pains": ["Dispatchers rebuild the schedule by hand every morning"],
    "budget": "About 40,000 dollars a year",
    "decision_process": "Dana decides with the CFO",
    "objections": [{"text": "We tried a tool and nobody used it.", "when": "early"}],
    "success_condition": "Dana agrees to a demo next week",
}


def brief() -> dict[str, Any]:
    beat = {"text": "Hi, what's this about?", "competencies": ["discovery"]}
    return {
        "session": {
            "interview_type": "role_play",
            "difficulty": "realistic",
            "mode": "realistic",
            "duration_min": 30,
            "level": "mid",
            "role_play": "discovery_call",
        },
        "generic_mode": True,
        "target_competencies": [
            "discovery",
            "objection_handling",
            "value_articulation",
            "closing",
            "communication",
        ],
        "questions": [{**beat, "id": "b1", "priority": 1}, {**beat, "id": "b2", "priority": 2}],
        "persona": {"tone": "Neutral", "pushback_style": "Plain", "closing_style": "Short"},
        "max_probes_per_question": 8,
        "role_play": BUYER,
    }


@pytest.mark.parametrize(
    ("status", "revealed"),
    [
        (SessionStatus.CREATED, False),
        (SessionStatus.IN_PROGRESS, False),
        (SessionStatus.INTERRUPTED, False),
        (SessionStatus.SCORING, True),
        (SessionStatus.COMPLETED, True),
    ],
)
def test_rp8_rp9_buyer_is_public_but_its_brief_only_after_the_call(
    status: SessionStatus, revealed: bool
) -> None:
    session = InterviewSession(status=status, brief_json=brief())
    buyer = _buyer(session)
    assert buyer is not None
    assert (buyer.name, buyer.title) == ("Dana Ruiz", "VP of Operations")
    assert (buyer.reveal is not None) == revealed


def test_rp8_other_sessions_have_no_buyer() -> None:
    assert _buyer(InterviewSession(status=SessionStatus.COMPLETED, brief_json=None)) is None
