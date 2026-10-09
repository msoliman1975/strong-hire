"""The runner with the interviewer on the fake model: a whole text session, turn by turn."""

from __future__ import annotations

from typing import Any

import pytest

from strong_core.gateway import ModelGateway
from strong_core.schemas import Difficulty, Mode, Phase, ProbeDecision, Speaker, Turn
from strong_interview import (
    PROBE_LIMIT,
    CoachNotAllowedError,
    Interviewer,
    InterviewRunner,
    SessionController,
    SessionFacts,
)
from strong_interview.interviewer import clean_reply, render_transcript
from strong_interview.runner import wants_to_ask
from strong_interview.testing import FakeClock, make_brief

ANSWER = "We built a new billing service and it went well."


async def run_session(
    gateway: ModelGateway, clock: FakeClock, **brief_args: Any
) -> InterviewRunner:
    brief = make_brief(**brief_args)
    runner = InterviewRunner(SessionController(brief, clock), Interviewer(gateway, brief))
    await runner.open()
    for _ in range(80):
        if runner.ended:
            break
        clock.advance(ms=20_000)
        phase = runner.controller.phase
        await runner.respond(
            "No questions, thanks." if phase == Phase.CANDIDATE_QUESTIONS else ANSWER
        )
    return runner


async def test_iv7_text_session_runs_to_the_end(gateway: ModelGateway, clock: FakeClock) -> None:
    """IV-7 and PL-7: a whole session runs through every phase and ends on its own."""
    runner = await run_session(gateway, clock)
    assert runner.ended
    phases = [t.phase for t in runner.turns]
    order = [Phase.INTRO, Phase.SMALL_TALK, Phase.AGENDA, Phase.CORE]
    order += [Phase.CANDIDATE_QUESTIONS, Phase.WRAP_UP]
    assert [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]] == order
    assert runner.turns[0].speaker == Speaker.INTERVIEWER
    for turn in runner.turns:
        assert turn.end_ms >= turn.start_ms
        assert (turn.question_ref is not None) == (turn.phase == Phase.CORE)


@pytest.mark.parametrize("difficulty", list(Difficulty))
async def test_iv3_follow_ups_stop_at_the_limit(
    gateway: ModelGateway, clock: FakeClock, difficulty: Difficulty
) -> None:
    """IV-3: the fake model always says "probe"; the controller stops at the limit."""
    runner = await run_session(gateway, clock, difficulty=difficulty, questions=6)
    by_question: dict[str, int] = {}
    for turn in runner.turns:
        if turn.speaker == Speaker.INTERVIEWER and turn.question_ref:
            by_question[turn.question_ref] = by_question.get(turn.question_ref, 0) + 1
    assert by_question
    for ref, count in by_question.items():
        assert count - 1 <= PROBE_LIMIT[difficulty], ref  # 1 question + probes
    # The fake model always says "probe", so the first question uses the whole limit.
    assert by_question["q1"] - 1 == PROBE_LIMIT[difficulty]


async def test_transcript_is_text_only_with_timings(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    """Turns hold text and timing only; no audio field exists to store."""
    seen: list[Turn] = []
    brief = make_brief()
    runner = InterviewRunner(
        SessionController(brief, clock), Interviewer(gateway, brief), on_turn=seen.append
    )
    await runner.open()
    await runner.respond(ANSWER, start_ms=1_000, end_ms=4_000)
    assert seen == runner.turns
    assert set(Turn.model_fields) == {
        "speaker",
        "phase",
        "text",
        "start_ms",
        "end_ms",
        "question_ref",
    }
    candidate = runner.turns[1]
    assert (candidate.start_ms, candidate.end_ms) == (1_000, 4_000)


async def test_iv8_runner_coach_commands(gateway: ModelGateway, clock: FakeClock) -> None:
    brief = make_brief(mode=Mode.COACH)
    runner = InterviewRunner(SessionController(brief, clock), Interviewer(gateway, brief))
    await runner.open()
    await runner.respond(ANSWER)
    await runner.respond(ANSWER)  # agenda + q1
    hint = await runner.coach("hint")
    assert len(hint) == 1 and hint[0].question_ref == "q1"
    redo = await runner.coach("redo")
    assert len(redo) == 1 and redo[0].question_ref == "q1"
    realistic = make_brief()
    other = InterviewRunner(SessionController(realistic, clock), Interviewer(gateway, realistic))
    await other.open()
    with pytest.raises(CoachNotAllowedError):
        await other.coach("hint")


async def test_close_wraps_up_and_ends(gateway: ModelGateway, clock: FakeClock) -> None:
    brief = make_brief()
    runner = InterviewRunner(SessionController(brief, clock), Interviewer(gateway, brief))
    await runner.open()
    closing = await runner.close()
    assert [t.phase for t in closing] == [Phase.WRAP_UP]
    assert runner.ended
    assert await runner.respond(ANSWER) == []


async def test_decision_failure_moves_on(clock: FakeClock, gateway: ModelGateway) -> None:
    """A model that cannot return a ProbeDecision never blocks the session."""

    class Broken:
        def __getattr__(self, name: str) -> Any:
            return getattr(gateway, name)

        async def complete(self, *args: Any, **kwargs: Any) -> Any:
            if kwargs.get("output_type") is ProbeDecision:
                raise RuntimeError("bad JSON")
            return await gateway.complete(*args, **kwargs)

    brief = make_brief()
    interviewer = Interviewer(Broken(), brief)  # type: ignore[arg-type]
    decision = await interviewer.decide(brief.questions[0], ANSWER, [])
    assert decision.action == "move_on"


def test_wants_to_ask() -> None:
    assert wants_to_ask("What does the team work on?")
    assert wants_to_ask("Yes, how big is the team")
    assert not wants_to_ask("No questions, thanks.")
    assert not wants_to_ask("I'm good, thank you")
    assert not wants_to_ask("That's all from me")


def test_clean_reply_and_window() -> None:
    assert clean_reply("Interviewer: **Hello** there.") == "Hello there."
    turns = [
        Turn(speaker=Speaker.CANDIDATE, phase=Phase.INTRO, text=str(i), start_ms=0, end_ms=0)
        for i in range(10)
    ]
    assert render_transcript(turns, 3).splitlines() == [
        "Candidate: 7",
        "Candidate: 8",
        "Candidate: 9",
    ]
    assert render_transcript([], 3) == "(nothing yet)"


def test_facts_render_only_what_is_known() -> None:
    assert SessionFacts().render() == "No facts are available."
    text = SessionFacts(company_name="Stripe", job_title="Engineer", notes=("Remote",)).render()
    assert text.splitlines() == ["Company: Stripe", "Job: Engineer", "- Remote"]


async def test_rollback_takes_back_a_turn_and_its_reply(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    """Voice turn taking: a reply that was not spoken can be taken back completely."""
    brief = make_brief(questions=6)
    runner = InterviewRunner(SessionController(brief, clock), Interviewer(gateway, brief))
    await runner.open()
    for _ in range(4):  # into CORE, with a question open
        clock.advance(ms=60_000)
        await runner.respond(ANSWER)
    assert runner.controller.phase == Phase.CORE
    before_turns = list(runner.turns)
    before_state = runner.controller.snapshot()

    checkpoint = runner.checkpoint()
    await runner.respond(ANSWER)
    assert len(runner.turns) > len(before_turns)
    runner.rollback(checkpoint)

    assert runner.turns == before_turns
    assert runner.controller.snapshot() == before_state


async def test_note_and_line_keep_the_question_open(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    brief = make_brief(questions=6)
    runner = InterviewRunner(SessionController(brief, clock), Interviewer(gateway, brief))
    await runner.open()
    for _ in range(4):
        clock.advance(ms=60_000)
        await runner.respond(ANSWER)
    state = runner.controller.snapshot()
    question = runner.controller.question

    note = await runner.note("Give me a moment.")
    line = await runner.line("Sure, take your time.")

    assert (note.speaker, line.speaker) == (Speaker.CANDIDATE, Speaker.INTERVIEWER)
    assert note.question_ref == line.question_ref == (question.id if question else None)
    assert runner.controller.snapshot() == state
