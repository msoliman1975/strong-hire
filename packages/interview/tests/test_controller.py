"""Session controller: state machine, time budget, probe limits, curveball and Coach controls."""

from __future__ import annotations

import pytest

from strong_core.schemas import Difficulty, Mode, Phase, ProbeDecision, ProbeTrigger
from strong_interview import PROBE_LIMIT, CoachNotAllowedError, MoveKind, SessionController
from strong_interview.controller import (
    CURVEBALL_REF,
    MAX_CANDIDATE_QUESTIONS,
    MIN_QUESTION_MS,
    Why,
)
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
    """IV-3: Friendly 1, Realistic 2, Tough 3 probes per question, even if the model asks more.
    Each decision names a new gap here, so only the limit stops the probes."""
    ctl = SessionController(make_brief(difficulty=difficulty, max_probes=3), clock)
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()  # agenda + first question
    probes = 0
    gaps = list(ProbeTrigger)
    while True:
        moves = ctl.after_answer(ProbeDecision(action="probe", missing=[gaps[probes]]))
        if moves[0].kind != MoveKind.PROBE:
            break
        assert moves[0].missing == (gaps[probes],)
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


# --- mini interview (10 minutes) --------------------------------------------------------------


def test_iv7_mini_default_plan_adds_up_to_10_minutes() -> None:
    """IV-7: minute 1 greeting and agenda, 8 minutes CORE, no candidate questions, 1 wrap-up."""
    from strong_interview.controller import DEFAULT_PLAN

    plan = DEFAULT_PLAN[10]
    assert sum(plan.values()) == 10
    assert plan[Phase.CORE] == 8
    assert plan[Phase.CANDIDATE_QUESTIONS] == 0
    assert plan[Phase.SMALL_TALK] == 0
    assert plan[Phase.WRAP_UP] == 1


def test_iv7_mini_skips_small_talk_and_candidate_questions(clock: FakeClock) -> None:
    """A mini goes greet, agenda with the first question, 3 questions, then wrap-up."""
    ctl = SessionController(make_brief(duration=10, questions=3), clock)
    assert ctl.mini
    assert ctl.deadline_ms(Phase.CORE) == 9 * 60 * 1000
    assert ctl.start().kind == MoveKind.GREET
    moves = ctl.after_answer()
    assert kinds(moves) == [MoveKind.AGENDA, MoveKind.ASK]
    assert moves[0].expects_answer is False
    seen = [MoveKind.GREET, *kinds(moves)]
    clock.advance(minutes=2)
    seen += kinds(ctl.after_answer(MOVE_ON))
    clock.advance(minutes=2)
    seen += kinds(ctl.after_answer(MOVE_ON))
    clock.advance(minutes=2)
    moves = ctl.after_answer(MOVE_ON)
    seen += kinds(moves)
    assert kinds(moves) == [MoveKind.WRAP_UP]
    assert ctl.asked == ["q1", "q2", "q3"]
    assert MoveKind.SMALL_TALK not in seen
    assert MoveKind.INVITE_QUESTIONS not in seen
    assert ctl.after_answer() == []
    assert ctl.ended


def test_iv7_mini_wraps_up_when_core_time_runs_out(clock: FakeClock) -> None:
    """With less than 2 minutes of CORE left, the mini drops the rest and wraps up."""
    ctl = SessionController(make_brief(duration=10, questions=3), clock)
    ctl.start()
    ctl.after_answer()
    clock.advance(minutes=7.5)
    assert kinds(ctl.after_answer(MOVE_ON)) == [MoveKind.WRAP_UP]
    assert ctl.dropped == ["q2", "q3"]


@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_iv3_mini_allows_one_probe_per_question(difficulty: Difficulty, clock: FakeClock) -> None:
    """IV-3 in a mini: at most 1 follow-up per question, whatever the difficulty."""
    brief = make_brief(duration=10, questions=3, difficulty=difficulty)
    # Even a brief that asks for more (built without validation) gets 1.
    ctl = SessionController(brief.model_copy(update={"max_probes_per_question": 3}), clock)
    assert ctl.probe_limit == 1
    ctl.start()
    ctl.after_answer()
    assert kinds(ctl.after_answer(PROBE)) == [MoveKind.PROBE]
    assert kinds(ctl.after_answer(PROBE)) == [MoveKind.ASK]


def test_iv4_mini_has_no_curveball(clock: FakeClock) -> None:
    """IV-4: no curveball in a mini, even if the brief carries one."""
    brief = make_brief(duration=10, questions=3, difficulty=Difficulty.TOUGH)
    assert brief.curveball is None
    brief = brief.model_copy(update={"curveball": "The budget is cut in half."})
    ctl = SessionController(brief, clock)
    ctl.start()
    ctl.after_answer()
    moves = ctl.after_answer(MOVE_ON)
    assert kinds(moves) == [MoveKind.ASK]
    assert CURVEBALL_REF not in ctl.asked


# ---------------------------------------------------------------- same gap, closing questions


def at_first_question(clock: FakeClock, **brief_args: object) -> SessionController:
    ctl = SessionController(make_brief(**brief_args), clock)  # type: ignore[arg-type]
    ctl.start()
    ctl.after_answer()
    ctl.after_answer()  # agenda + first question
    return ctl


def probe(*missing: ProbeTrigger) -> ProbeDecision:
    return ProbeDecision(action="probe", missing=list(missing))


def test_iv3_same_gap_not_filled_moves_on(clock: FakeClock) -> None:
    """IV-3: after one probe on a gap, a second probe for the same gap moves on instead."""
    ctl = at_first_question(clock)  # Realistic: 2 probes allowed
    first = ctl.after_answer(probe(ProbeTrigger.OWN_ROLE, ProbeTrigger.MEASURABLE_RESULT))
    assert kinds(first) == [MoveKind.PROBE]
    # The answer still lacks the same two things: asking again in new words does not help.
    moves = ctl.after_answer(probe(ProbeTrigger.MEASURABLE_RESULT, ProbeTrigger.OWN_ROLE))
    assert kinds(moves) == [MoveKind.ASK]
    assert moves[0].question is not None and moves[0].question.id == "q2"
    assert Why.SAME_GAP_NOT_FILLED in moves[0].reason
    assert ctl.probes_used == 0 and ctl.probed_missing == []


def test_iv3_a_new_gap_may_still_be_probed_and_only_the_new_gap_is_asked(
    clock: FakeClock,
) -> None:
    ctl = at_first_question(clock)  # Realistic: 2 probes allowed
    ctl.after_answer(probe(ProbeTrigger.OWN_ROLE))
    moves = ctl.after_answer(probe(ProbeTrigger.OWN_ROLE, ProbeTrigger.TRADEOFF_REASONING))
    assert kinds(moves) == [MoveKind.PROBE]
    assert moves[0].missing == (ProbeTrigger.TRADEOFF_REASONING,)  # not own role again
    assert ctl.probes_used == 2


def test_iv3_a_second_probe_with_nothing_named_moves_on(clock: FakeClock) -> None:
    ctl = at_first_question(clock)  # Realistic: 2 probes allowed
    assert kinds(ctl.after_answer(probe())) == [MoveKind.PROBE]
    moves = ctl.after_answer(probe())
    assert kinds(moves) == [MoveKind.ASK]
    assert Why.SAME_GAP_NOT_FILLED in moves[0].reason


def test_iv3_probed_gaps_are_per_question_and_taken_back_with_a_snapshot(
    clock: FakeClock,
) -> None:
    ctl = at_first_question(clock)
    ctl.after_answer(probe(ProbeTrigger.OWN_ROLE))
    state = ctl.snapshot()
    ctl.after_answer(MOVE_ON)  # q2
    assert ctl.probed_missing == []
    assert kinds(ctl.after_answer(probe(ProbeTrigger.OWN_ROLE))) == [MoveKind.PROBE]
    ctl.restore(state)
    assert ctl.probed_missing == [ProbeTrigger.OWN_ROLE]


def at_candidate_questions(clock: FakeClock) -> SessionController:
    ctl = at_first_question(clock)
    for _ in range(10):
        if kinds(ctl.after_answer(MOVE_ON)) == [MoveKind.INVITE_QUESTIONS]:
            return ctl
    raise AssertionError("never reached the candidate questions")


def test_iv7_no_question_closes_at_once(clock: FakeClock) -> None:
    ctl = at_candidate_questions(clock)
    moves = ctl.after_answer(has_question=False)
    assert kinds(moves) == [MoveKind.WRAP_UP]
    assert moves[0].reason == (Why.CANDIDATE_HAD_NO_QUESTION,)
    assert not moves[0].open_question


def test_iv7_a_question_past_the_limit_is_answered_before_the_close(clock: FakeClock) -> None:
    """A question asked when the limit is reached gets a last short answer, then the wrap-up."""
    ctl = at_candidate_questions(clock)
    for _ in range(MAX_CANDIDATE_QUESTIONS):
        assert kinds(ctl.after_answer(has_question=True)) == [MoveKind.ANSWER_QUESTION]
    moves = ctl.after_answer(has_question=True)
    assert kinds(moves) == [MoveKind.ANSWER_QUESTION, MoveKind.WRAP_UP]
    answer, close = moves
    assert answer.closing and not answer.expects_answer
    assert answer.reason == (Why.CANDIDATE_QUESTIONS_LIMIT, Why.ANSWER_BEFORE_CLOSE)
    assert close.reason == (Why.CANDIDATE_QUESTIONS_LIMIT,) and not close.open_question
    assert ctl.phase == Phase.WRAP_UP


def test_iv7_a_question_after_the_phase_time_is_answered_before_the_close(
    clock: FakeClock,
) -> None:
    ctl = at_candidate_questions(clock)
    clock.now_ms = ctl.deadline_ms(Phase.CANDIDATE_QUESTIONS)  # phase over, session time left
    moves = ctl.after_answer(has_question=True)
    assert kinds(moves) == [MoveKind.ANSWER_QUESTION, MoveKind.WRAP_UP]
    assert moves[0].reason == (Why.CANDIDATE_QUESTIONS_TIME_UP, Why.ANSWER_BEFORE_CLOSE)


def test_iv7_a_question_when_the_session_time_is_up_is_acknowledged_in_the_close(
    clock: FakeClock,
) -> None:
    ctl = at_candidate_questions(clock)
    clock.now_ms = ctl.total_ms
    moves = ctl.after_answer(has_question=True)
    assert kinds(moves) == [MoveKind.WRAP_UP]
    assert moves[0].open_question
    assert moves[0].reason == (Why.SESSION_TIME_UP, Why.CANDIDATE_QUESTION_LEFT_OPEN)
