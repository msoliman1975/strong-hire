"""CS-1, CS-2: the escalation call and the customer success family."""

from __future__ import annotations

from typing import Any

from strong_core.role_families import family_info
from strong_core.schemas import InterviewType, RoleFamily, RolePlayScenario, SessionConfig


def config(**changes: Any) -> SessionConfig:
    base: dict[str, Any] = {
        "interview_type": "role_play",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 30,
        "level": "mid",
        "role_play": "escalation_call",
    }
    return SessionConfig.model_validate(base | changes)


def test_cs1_escalation_call_is_a_role_play_call() -> None:
    """CS-1: a role-play session can be an escalation call; the sales calls still load."""
    assert config().role_play == RolePlayScenario.ESCALATION_CALL
    for call in ("cold_call", "discovery_call", "demo_objections", "negotiation_close"):
        assert config(role_play=call).role_play == RolePlayScenario(call)


def test_cs2_customer_success_registry_entry() -> None:
    """CS-2, D-2, D-5: label, keywords, loop, and Strova plays the customer."""
    info = family_info(RoleFamily.CUSTOMER_SUCCESS)
    assert info.label == "Customer success"
    assert {"customer success", "csm", "technical account manager"} <= set(info.title_keywords)
    assert info.generic_loop == (
        InterviewType.RECRUITER_SCREEN,
        InterviewType.ROLE_PLAY,
        InterviewType.HIRING_MANAGER,
    )
    assert info.interviewer_title(InterviewType.ROLE_PLAY) == "Customer"


def test_cs2_other_families_play_the_buyer() -> None:
    """D-5: every family but customer success plays the buyer in a role-play."""
    for family in RoleFamily:
        title = family_info(family).interviewer_title(InterviewType.ROLE_PLAY)
        assert title == ("Customer" if family == RoleFamily.CUSTOMER_SUCCESS else "Buyer")
