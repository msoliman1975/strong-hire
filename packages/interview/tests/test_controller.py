"""Session controller: state machine, time budget, probe limits, curveball and Coach controls."""

from __future__ import annotations

import pytest

from strong_core.schemas import Difficulty, Mode, Phase, ProbeDecision, ProbeTrigger
from strong_interview import PROBE_LIMIT, CoachNotAllowedError, MoveKind, SessionController
from strong_interview.controller import CURVEBALL_REF, MIN_QUESTION_MS
from strong_interview.testing import FakeClock, make_brief

PROBE = ProbeDecision(action="probe", missing=[ProbeTrigger.MEASURABLE_RESULT])
MOVE_ON = ProbeDecision(action="move_on")


def kinds(moves: list) -> list[MoveKind]:  # type: ignore[type-arg]
    return [m.kind for m in moves]


def test_iv7_phases_run_in_order_and_the_controller_ends_the_session(clock: FakeClock) -> None:
    """IV-7: intro, small talk, agenda, core, candidate questions, wrap-up."""
    ctl = SessionController(make_brief(questions=6), clock)
    assert ctl.start().kind == MoveKind.GREET
    assert kinds(ctl.after_answer()) == [MoveKind.SMALL_TALK]
    moves = ctl.after_answer()
    assert kinds(moves) == [MoveKind.AGENDA, MoveKind.ASK]
    assert moves[0].expects_answer is False
    assert moves[1].question is not None and moves[1].question.id == "q1"
    asked = ["q1"]
    for _ in range(5):
        moves = ctl.after_answer(MOVE_ON)
        assert kinds(moves) == [MoveKind.ASK]
        assert moves[0].question is not None
        asked.append(moves[0].question.id)
    assert asked == ["q1", "q2", "q3", "q4", "q5", "q6"]  # by priority
    assert kinds(ctl.after_answer(MOVE_ON)) == [MoveKind.INVITE_QUESTIONS]
    assert ctl.phase == Phase.CANDIDATE_QUESTIONS
    assert kinds(ctl.after_answer(has_question=True)) == [MoveKind.ANSWER_QUESTION]
    assert kinds(ctl.after_answer(has_question=False)) == [MoveKind.WRAP_UP]
    assert not ctl.ended
    assert ctl.after_answer() == []
    assert ctl.ended


@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_iv3_probe_limit_per_difficulty(difficulty: Difficulty, clock: FakeClock) -> None:
    """IV-3: Friendly 1, Realistic 2, Tough 3 probes per question, even if the model asks more."""
    ctl = SessionController(make_brief(difficulty=difficulty, max_probes=3), clock)
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()  # agenda + first question
    probes = 0
    while True:
        moves = ctl.after_answer(PROBE)
        if moves[0].kind != MoveKind.PROBE:
            break
        assert moves[0].missing == (ProbeTrigger.MEASURABLE_RESULT,)
        probes += 1
    assert probes == PROBE_LIMIT[difficulty]
    assert moves[0].kind in (MoveKind.ASK, MoveKind.CURVEBALL)


def test_iv3_brief_can_only_lower_the_probe_limit(clock: FakeClock) -> None:
    ctl = SessionController(make_brief(difficulty=Difficulty.TOUGH, max_probes=1), clock)
    assert ctl.probe_limit == 1


def test_iv3_move_on_skips_the_follow_up(clock: FakeClock) -> None:
    ctl = SessionController(make_brief(), clock)
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()
    assert kinds(ctl.after_answer(MOVE_ON)) == [MoveKind.ASK]
    assert ctl.probes_used == 0


def test_iv7_core_drops_lower_priority_questions_when_time_runs_short(clock: FakeClock) -> None:
    """IV-7: CORE keeps to its time budget by dropping the lowest-priority questions."""
    ctl = SessionController(make_brief(questions=8), clock)
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()  # asks q1
    left = ctl.deadline_ms(Phase.CORE) - ctl.elapsed_ms
    clock.advance(ms=left - MIN_QUESTION_MS + 1)  # less than MIN_QUESTION_MS of CORE left
    assert kinds(ctl.after_answer(MOVE_ON)) == [MoveKind.INVITE_QUESTIONS]
    assert ctl.asked == ["q1"]
    assert ctl.dropped == ["q2", "q3", "q4", "q5", "q6", "q7", "q8"]


def test_iv7_no_probe_after_the_core_time_is_over(clock: FakeClock) -> None:
    ctl = SessionController(make_brief(), clock)
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()
    clock.advance(ms=ctl.deadline_ms(Phase.CORE))
    assert not ctl.needs_decision
    assert kinds(ctl.after_answer(PROBE)) == [MoveKind.INVITE_QUESTIONS]


def test_iv7_session_wraps_up_when_the_duration_is_over(clock: FakeClock) -> None:
    ctl = SessionController(make_brief(duration=45), clock)
    ctl.start()
    ctl.after_answer()
    clock.advance(minutes=45)
    assert kinds(ctl.after_answer()) == [MoveKind.WRAP_UP]
    assert ctl.after_answer() == []
    assert ctl.ended


def test_iv4_tough_asks_one_curveball_after_the_first_question(clock: FakeClock) -> None:
    """IV-4: Tough difficulty adds one curveball per session, and probes push back."""
    ctl = SessionController(make_brief(difficulty=Difficulty.TOUGH), clock)
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()  # q1
    probe = ctl.after_answer(PROBE)[0]
    assert probe.kind == MoveKind.PROBE and probe.pushback
    seen = []
    for _ in range(12):
        moves = ctl.after_answer(MOVE_ON)
        seen += kinds(moves)
        if moves[0].kind == MoveKind.INVITE_QUESTIONS:
            break
    assert seen.count(MoveKind.CURVEBALL) == 1
    assert seen[0] == MoveKind.CURVEBALL
    assert CURVEBALL_REF in ctl.asked


def test_no_curveball_below_tough(clock: FakeClock) -> None:
    ctl = SessionController(make_brief(difficulty=Difficulty.REALISTIC), clock)
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()
    probe = ctl.after_answer(PROBE)[0]
    assert probe.pushback is False
    assert MoveKind.CURVEBALL not in kinds(ctl.after_answer(MOVE_ON))


def test_iv8_coach_controls_are_not_allowed_in_realistic_mode(clock: FakeClock) -> None:
    """IV-8: Realistic mode allows no pause, hint or redo."""
    ctl = SessionController(make_brief(mode=Mode.REALISTIC), clock)
    ctl.start()
    for action in (ctl.pause, ctl.resume, ctl.hint, ctl.redo):
        with pytest.raises(CoachNotAllowedError):
            action()


def test_iv8_coach_pause_stops_the_clock(clock: FakeClock) -> None:
    ctl = SessionController(make_brief(mode=Mode.COACH), clock)
    ctl.start()
    clock.advance(minutes=1)
    ctl.pause()
    assert ctl.paused
    clock.advance(minutes=10)
    assert ctl.elapsed_ms == 60_000
    ctl.resume()
    clock.advance(minutes=1)
    assert ctl.elapsed_ms == 120_000


def test_iv8_coach_hint_and_redo(clock: FakeClock) -> None:
    """IV-8: a hint is a nudge on the current question (2 at most); redo asks it again."""
    ctl = SessionController(make_brief(mode=Mode.COACH), clock)
    ctl.start()
    assert ctl.hint() is None  # no question yet
    ctl.after_answer()
    ctl.after_answer()  # q1
    first, second = ctl.hint(), ctl.hint()
    assert first is not None and first.kind == MoveKind.HINT
    assert second is not None
    assert ctl.hint() is None
    ctl.after_answer(PROBE)
    assert ctl.probes_used == 1
    redo = ctl.redo()
    assert redo is not None and redo.kind == MoveKind.REDO
    assert redo.question is not None and redo.question.id == "q1"
    assert ctl.probes_used == 0


def test_question_ref_is_set_in_core_only(clock: FakeClock) -> None:
    ctl = SessionController(make_brief(), clock)
    assert ctl.start().question_ref is None
    moves = ctl.after_answer()
    assert moves[0].question_ref is None
    moves = ctl.after_answer()
    assert moves[0].question_ref is None  # agenda
    assert moves[1].question_ref == "q1"


def test_brief_time_plan_sets_the_core_budget(clock: FakeClock) -> None:
    from strong_core.schemas import PhaseTime

    brief = make_brief(duration=30).model_copy(
        update={
            "time_plan": [
                PhaseTime(phase=Phase.INTRO, minutes=1),
                PhaseTime(phase=Phase.SMALL_TALK, minutes=1),
                PhaseTime(phase=Phase.AGENDA, minutes=1),
                PhaseTime(phase=Phase.CORE, minutes=24),
                PhaseTime(phase=Phase.CANDIDATE_QUESTIONS, minutes=2),
                PhaseTime(phase=Phase.WRAP_UP, minutes=1),
            ]
        }
    )
    ctl = SessionController(brief, clock)
    assert ctl.deadline_ms(Phase.CORE) == 27 * 60 * 1000


def test_iv9_hold_stops_the_clock_in_any_mode(clock: FakeClock) -> None:
    """IV-9: while the candidate is disconnected, session time does not run (Realistic too)."""
    ctl = SessionController(make_brief(mode=Mode.REALISTIC), clock)
    ctl.start()
    clock.advance(minutes=2)
    ctl.hold()
    clock.advance(minutes=1.5)
    assert ctl.elapsed_ms == 120_000
    ctl.release()
    clock.advance(minutes=1)
    assert ctl.elapsed_ms == 180_000
    ctl.release()  # safe to call twice
    assert ctl.elapsed_ms == 180_000
