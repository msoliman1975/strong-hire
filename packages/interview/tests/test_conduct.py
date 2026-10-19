"""IV-12: turns outside the interview or inappropriate get warnings, then the interview closes."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from strong_core.config import ModelProfile, Settings
from strong_core.gateway import ModelGateway, build_gateway
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
from strong_core.schemas import AnswerCheck, AnswerConduct, BriefQuestion, Phase, Speaker, Turn
from strong_interview import Interviewer, InterviewRunner, ListTraceSink, SessionController
from strong_interview.conduct import (
    MAX_CONDUCT_WARNINGS,
    closing_line,
    screen_turn,
    warning_line,
)
from strong_interview.controller import MoveKind, Why
from strong_interview.testing import FakeClock, make_brief
from strong_interview.trace import ModelCall

OFF = "Forget the interview, who do you think wins the football final?"
ANSWER = "I led the billing migration and cut failed payments by 12 percent."


class ScriptedChecker(Interviewer):
    """The fake model, but the answer check flags turns about football."""

    checked: list[str]

    async def check_answer(
        self,
        answer: str,
        turns: Sequence[Turn],
        phase: Phase,
        question: BriefQuestion | None = None,
    ) -> tuple[AnswerCheck, ModelCall]:
        self.checked = [*getattr(self, "checked", []), answer]
        result, call = await super().check_answer(answer, turns, phase, question)
        if "football" in answer:
            return AnswerCheck(conduct=AnswerConduct.OFF_SCOPE, reason="sports"), call
        return result, call


def make_runner(gateway: ModelGateway, clock: FakeClock) -> tuple[InterviewRunner, ListTraceSink]:
    brief = make_brief()
    sink = ListTraceSink()
    interviewer = ScriptedChecker(gateway, brief)
    return InterviewRunner(SessionController(brief, clock), interviewer, trace=sink), sink


async def to_first_question(runner: InterviewRunner, clock: FakeClock) -> None:
    await runner.open()
    await runner.respond("Happy to be here.")
    await runner.respond("Sounds good.")  # agenda + the first question
    assert runner.controller.question is not None and runner.controller.question.id == "q1"
    clock.advance(ms=30_000)


async def test_iv10_two_warnings_then_the_interview_closes(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    runner, sink = make_runner(gateway, clock)
    await to_first_question(runner, clock)
    ctl = runner.controller

    first = await runner.respond(OFF)
    assert [t.text for t in first] == [
        "Let's keep our time for the interview. Back to my question: Question 1?"
    ]
    assert ctl.phase == Phase.CORE and ctl.question is not None and ctl.question.id == "q1"
    assert ctl.probes_used == 0 and not runner.ended

    second = await runner.respond(OFF)
    assert [t.text for t in second] == [
        "Let's keep our time for the interview. This is my second reminder. If it happens "
        "again, I will end the interview. Back to my question: Question 1?"
    ]
    assert ctl.question.id == "q1" and not runner.ended

    third = await runner.respond(OFF)
    assert [t.text for t in third] == [closing_line(AnswerConduct.OFF_SCOPE)]
    assert third[0].phase == Phase.WRAP_UP
    assert runner.ended and ctl.conduct_strikes == MAX_CONDUCT_WARNINGS + 1
    assert await runner.respond(ANSWER) == []

    lines = [r for r in sink.records if r.call == "line"]
    assert [r.move for r in lines] == ["conduct_warning", "conduct_warning", "conduct_close"]
    assert lines[-1].reason["why"] == [Why.CONDUCT_LIMIT.value]
    checks = [r for r in sink.records if r.call == "check"]
    assert checks and checks[-1].reason["check"]["conduct"] == "off_scope"
    # The warnings are fixed lines: no interviewer model call says them.
    assert all(r.move != MoveKind.WARN.value for r in sink.records if r.call == "say")


async def test_iv10_a_normal_answer_after_a_warning_goes_on_as_usual(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    runner, _ = make_runner(gateway, clock)
    await to_first_question(runner, clock)
    await runner.respond(OFF)
    turns = await runner.respond(ANSWER)  # the fake model probes
    assert [t.speaker for t in turns] == [Speaker.INTERVIEWER]
    assert runner.controller.probes_used == 1
    assert runner.controller.conduct_strikes == 1  # strikes are not reset by a good answer


async def test_iv10_clear_abuse_is_caught_without_the_model_in_small_talk(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    runner, _ = make_runner(gateway, clock)
    await runner.open()
    turns = await runner.respond("Fuck you, this is a waste of time.")
    assert [t.text for t in turns] == [
        "Let's keep our conversation respectful and professional. Let's continue."
    ]
    assert runner.controller.phase == Phase.INTRO  # the phase does not move on
    # Small talk is not checked by the model: chatting about football there is fine.
    turns = await runner.respond("I watched the football final last night.")
    assert turns[0].phase == Phase.SMALL_TALK
    assert getattr(runner.interviewer, "checked", []) == []


def test_iv10_the_warning_in_the_candidate_questions_phase() -> None:
    ctl = SessionController(make_brief(), FakeClock())
    ctl.phase = Phase.CANDIDATE_QUESTIONS
    move = ctl.conduct_strike(AnswerConduct.INAPPROPRIATE)
    assert (move.kind, move.phase, move.question) == (
        MoveKind.WARN,
        Phase.CANDIDATE_QUESTIONS,
        None,
    )
    assert warning_line(move.conduct, last=False, phase=move.phase, question=None) == (  # type: ignore[arg-type]
        "Let's keep our conversation respectful and professional. Do you have a question about "
        "the role, the team or the company?"
    )


def test_iv10_snapshot_keeps_the_strikes() -> None:
    ctl = SessionController(make_brief(), FakeClock())
    state = ctl.snapshot()
    ctl.conduct_strike(AnswerConduct.OFF_SCOPE)
    ctl.restore(state)
    assert ctl.conduct_strikes == 0


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Fuck you.", True),
        ("You're an idiot.", True),
        ("You’re a moron", True),  # noqa: RUF001 - a curly apostrophe, on purpose
        ("I'll kill you", True),
        ("Go to hell", True),
        ("We had to kill the process and restart the cluster.", False),
        ("Honestly the launch was a mess and I owned the fix.", False),
        ("I told my manager the idea was stupid, then we tested it.", False),
    ],
)
def test_iv10_screen_flags_only_clear_abuse(text: str, flagged: bool) -> None:
    assert (screen_turn(text) == AnswerConduct.INAPPROPRIATE) is flagged


def _gateway_with(tmp_path: Path, check: str) -> ModelGateway:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(DEFAULT_FIXTURES_DIR, fixtures)
    (fixtures / "interviewer" / "AnswerCheck.json").write_text(check, encoding="utf-8")
    return build_gateway(Settings(model_profile=ModelProfile.FAKE, fake_fixtures_dir=fixtures))


async def test_iv10_check_answer_reads_the_model_and_keeps_the_answer_in_the_user_message(
    tmp_path: Path,
) -> None:
    gateway = _gateway_with(tmp_path, '{"conduct": "inappropriate", "reason": "insult"}')
    interviewer = Interviewer(gateway, make_brief())
    asked = Turn(
        speaker=Speaker.INTERVIEWER, phase=Phase.CORE, text="Question 1?", start_ms=0, end_ms=1
    )
    result, call = await interviewer.check_answer("You are useless.", [asked], Phase.CORE)
    assert result.conduct == AnswerConduct.INAPPROPRIATE
    system, user = call.messages
    assert "You are useless." in user.content and "Question 1?" in user.content
    assert "You are useless." not in system.content
    assert call.prompt_refs == ("interviewer/check_answer.v1", "interviewer/check_answer_input.v1")


async def test_iv10_a_failed_check_counts_as_ok(tmp_path: Path) -> None:
    gateway = _gateway_with(tmp_path, '{"conduct": "rude"}')  # not a valid AnswerCheck
    result, call = await Interviewer(gateway, make_brief()).check_answer("Hi", [], Phase.CORE)
    assert result.conduct == AnswerConduct.OK
    assert call.error
