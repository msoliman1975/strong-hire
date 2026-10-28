"""Recruiter screen (RS-2): the live interviewer speaks as a recruiter, from its own prompt."""

from __future__ import annotations

from strong_core.gateway import ModelGateway
from strong_core.schemas import InterviewType, Phase
from strong_interview.controller import Move, MoveKind
from strong_interview.interviewer import Interviewer
from strong_interview.testing import make_brief


def recruiter_brief():  # type: ignore[no-untyped-def]
    brief = make_brief()
    session = brief.session.model_copy(update={"interview_type": InterviewType.RECRUITER_SCREEN})
    return brief.model_copy(update={"session": session})


def test_rs2_interviewer_uses_the_recruiter_turn_prompt(gateway: ModelGateway) -> None:
    """RS-2: the system prompt is chosen by the session's type, not by model."""
    interviewer = Interviewer(gateway, recruiter_brief())
    system, _ = interviewer.turn_messages(Move(MoveKind.GREET, Phase.INTRO), [])
    assert system.prompt_ref == "interviewer/turn_recruiter_screen.v1"
    assert "You are Alex, a recruiter." in system.content
    assert "Never ask about these" in system.content


def test_rs2_other_types_keep_the_turn_prompt(gateway: ModelGateway) -> None:
    interviewer = Interviewer(gateway, make_brief())
    system, _ = interviewer.turn_messages(Move(MoveKind.GREET, Phase.INTRO), [])
    assert system.prompt_ref is not None and system.prompt_ref.startswith("interviewer/turn.v")
