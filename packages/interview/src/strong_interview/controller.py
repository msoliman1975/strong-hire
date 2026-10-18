"""Session controller: the conversation state machine and the clock (IV-3, IV-4, IV-7, IV-8).

INTRO -> SMALL_TALK -> AGENDA -> CORE (question, answer, follow-ups) -> CANDIDATE_QUESTIONS ->
WRAP_UP. The controller decides every phase change and when the session ends; the model never
does. The interviewer model only chooses what to say, and in CORE whether to probe. The
controller caps probes per question by difficulty, so a weak model cannot loop.

A follow-up must aim at something new. Each probe records what the answer lacked (the decision's
`missing`). When the next decision asks to probe only for gaps already probed on this question,
the candidate did not fill them after being asked once, so the controller moves on
(`same_gap_not_filled`) instead of asking the same thing in new words. A probe on a gap not yet
asked about is still allowed, within the probe limit.

Candidate questions: a question is answered while time and the limit allow. When the controller
must close anyway (limit reached, phase time up), a pending question still gets a short last
answer before the wrap-up. When the session time is fully used, the wrap-up line acknowledges the
question and says the recruiter can follow up.

Time: each phase gets minutes from the brief's time_plan (or a default plan). CORE stops
starting new questions when less than MIN_QUESTION_MS is left; lower-priority questions are
dropped. Coach mode can pause the clock.

A phase with 0 planned minutes is skipped: no SMALL_TALK turn (the greeting may hold one short
small-talk line) and no CANDIDATE_QUESTIONS turn (CORE goes straight to WRAP_UP). The agenda is
always said, in one short turn. The 10-minute mini interview uses this: minute 1 is the greeting
and the agenda, 8 minutes of CORE, 1 minute of WRAP_UP. A mini also has no curveball and at
most MINI_MAX_PROBES follow-ups per question, whatever the difficulty.

Custom sessions (CU-4, D-6): CORE runs category by category in the order the candidate set
(`brief.session.custom.categories`), and by priority within a category. Must-ask questions are
guaranteed by this controller, never by the model. See the time-pressure rule above
`_probe_fits`. The four standard types never take these paths.

IV-12: a candidate turn outside the interview, or an inappropriate one, is a conduct strike
(`conduct_strike`). The first MAX_CONDUCT_WARNINGS strikes get a WARN move: the phase, the open
question and the probe count stay as they were, so the candidate answers the same question
again. The next strike closes the interview at once; the session ends after the closing line.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from strong_core.schemas import (
    MINI_MAX_PROBES,
    AnswerConduct,
    BriefQuestion,
    Difficulty,
    InterviewerBrief,
    Phase,
    ProbeDecision,
    ProbeTrigger,
    QuestionSource,
    Speaker,
    Turn,
)
from strong_interview.conduct import MAX_CONDUCT_WARNINGS

# IV-3: most follow-ups per question. The brief's max_probes_per_question can only lower it.
PROBE_LIMIT: dict[Difficulty, int] = {
    Difficulty.FRIENDLY: 1,
    Difficulty.REALISTIC: 2,
    Difficulty.TOUGH: 3,
}
# Minutes per phase when the brief has no time_plan (IV-7). Each plan adds up to the duration.
DEFAULT_PLAN: dict[int, dict[Phase, int]] = {
    10: {
        Phase.INTRO: 1,  # greeting and the agenda
        Phase.SMALL_TALK: 0,
        Phase.AGENDA: 0,
        Phase.CORE: 8,
        Phase.CANDIDATE_QUESTIONS: 0,
        Phase.WRAP_UP: 1,
    },
    30: {
        Phase.INTRO: 1,
        Phase.SMALL_TALK: 2,
        Phase.AGENDA: 1,
        Phase.CORE: 21,
        Phase.CANDIDATE_QUESTIONS: 4,
        Phase.WRAP_UP: 1,
    },
    45: {
        Phase.INTRO: 1,
        Phase.SMALL_TALK: 2,
        Phase.AGENDA: 1,
        Phase.CORE: 35,
        Phase.CANDIDATE_QUESTIONS: 5,
        Phase.WRAP_UP: 1,
    },
}
ORDER = (
    Phase.INTRO,
    Phase.SMALL_TALK,
    Phase.AGENDA,
    Phase.CORE,
    Phase.CANDIDATE_QUESTIONS,
    Phase.WRAP_UP,
)
MIN_QUESTION_MS = 2 * 60 * 1000  # do not start a new CORE question with less time left
MAX_HINTS_PER_QUESTION = 2
MAX_CANDIDATE_QUESTIONS = 3
CURVEBALL_REF = "curveball"
# CU-4: the time a Custom session plans per must-ask question and per follow-up. Both are low on
# purpose: nothing is cut while the session runs to time, only when the clock is really short.
MUST_ASK_QUESTION_MS = MIN_QUESTION_MS  # a must-ask question with no follow-up
PROBE_MS = 60 * 1000  # one follow-up and its answer


class Why(StrEnum):
    """Why the controller made a move. Kept in the admin traces (R2), never shown to users."""

    START = "start"
    NEXT_PHASE = "next_phase"
    SESSION_TIME_UP = "session_time_up"
    MODEL_CHOSE_PROBE = "model_chose_probe"
    MODEL_CHOSE_MOVE_ON = "model_chose_move_on"
    NO_DECISION = "no_decision"
    PROBE_LIMIT_REACHED = "probe_limit_reached"
    CORE_TIME_UP = "core_time_up"
    CURVEBALL_DUE = "curveball_due"
    NEXT_QUESTION = "next_question"
    CORE_TIME_LEFT_UNDER_MIN = "core_time_left_under_2_min"
    NO_QUESTIONS_LEFT = "no_questions_left"
    NO_CANDIDATE_QUESTIONS_PHASE = "no_candidate_questions_phase"
    CANDIDATE_ASKED = "candidate_asked"
    CANDIDATE_HAD_NO_QUESTION = "candidate_had_no_question"
    CANDIDATE_QUESTIONS_TIME_UP = "candidate_questions_time_up"
    CANDIDATE_QUESTIONS_LIMIT = "candidate_questions_limit"
    SAME_GAP_NOT_FILLED = "same_gap_not_filled"
    ANSWER_BEFORE_CLOSE = "answer_before_close"
    CANDIDATE_QUESTION_LEFT_OPEN = "candidate_question_left_open"
    ENDED_EARLY = "ended_early"
    COACH_REQUEST = "coach_request"
    CONDUCT_WARNING = "conduct_warning"
    CONDUCT_LIMIT = "conduct_limit"
    UNEXPECTED_PHASE = "unexpected_phase"
    # CU-4, Custom sessions only
    PROBES_CUT_FOR_MUST_ASK = "probes_cut_for_must_ask"
    SKIPPED_FOR_TIME = "questions_skipped_for_time"
    MUST_ASK_GUARANTEED = "must_ask_guaranteed"


class MoveKind(StrEnum):
    """What the interviewer does next. The interviewer prompt explains each one."""

    GREET = "greet"
    SMALL_TALK = "small_talk"
    AGENDA = "agenda"
    ASK = "ask"
    PROBE = "probe"
    CURVEBALL = "curveball"
    INVITE_QUESTIONS = "invite_questions"
    ANSWER_QUESTION = "answer_question"
    WRAP_UP = "wrap_up"
    HINT = "hint"
    REDO = "redo"
    WARN = "warn"  # IV-12: a fixed warning line, then the same question again


@dataclass(frozen=True)
class Move:
    kind: MoveKind
    phase: Phase
    question: BriefQuestion | None = None
    missing: tuple[ProbeTrigger, ...] = ()
    pushback: bool = False
    expects_answer: bool = True
    reason: tuple[Why, ...] = ()
    # ANSWER_QUESTION: the last answer before the close; do not invite more questions.
    closing: bool = False
    # WRAP_UP: the candidate asked a question there is no time left to answer.
    open_question: bool = False
    # IV-12: WARN, or the WRAP_UP that closes the interview, for this kind of turn.
    conduct: AnswerConduct | None = None
    last_warning: bool = False  # WARN: the next strike closes the interview

    @property
    def question_ref(self) -> str | None:
        """Turn.question_ref: the question id, in CORE only."""
        return self.question.id if self.phase == Phase.CORE and self.question else None


class CoachNotAllowedError(RuntimeError):
    """Pause, hint and redo exist only in Coach mode (IV-8)."""


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


@dataclass
class _Clock:
    now: Callable[[], int]
    started: int | None = None
    paused_total: int = 0
    paused_at: int | None = None

    def elapsed(self) -> int:
        if self.started is None:
            return 0
        end = self.paused_at if self.paused_at is not None else self.now()
        return max(0, end - self.started - self.paused_total)


@dataclass
class SessionController:
    brief: InterviewerBrief
    clock: Callable[[], int] = _monotonic_ms
    phase: Phase = Phase.INTRO
    question: BriefQuestion | None = None
    probes_used: int = 0
    hints_used: int = 0
    ended: bool = False
    asked: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    curveball_used: bool = False
    candidate_questions: int = 0
    # The gaps (ProbeDecision.missing) already probed on the current question.
    probed_missing: list[ProbeTrigger] = field(default_factory=list)
    conduct_strikes: int = 0  # IV-12

    def __post_init__(self) -> None:
        self._clock = _Clock(self.clock)
        self._queue = self._order(self.brief.questions)
        minutes = self._plan()
        self._minutes = minutes
        self._deadline: dict[Phase, int] = {}
        total = 0
        for phase in ORDER:
            total += minutes.get(phase, 0) * 60 * 1000
            self._deadline[phase] = total
        self.total_ms = self.brief.session.duration_min * 60 * 1000

    def _order(self, questions: Sequence[BriefQuestion]) -> list[BriefQuestion]:
        """By priority. A Custom session runs its categories in the candidate's order (CU-4),
        by priority within each category."""
        custom = self.brief.session.custom
        if custom is None:
            return sorted(questions, key=lambda q: q.priority)
        rank = {c.category: i for i, c in enumerate(custom.categories)}

        def key(q: BriefQuestion) -> tuple[int, int]:
            return (rank.get(q.category, len(rank)) if q.category else len(rank), q.priority)

        return sorted(questions, key=key)

    def _plan(self) -> dict[Phase, int]:
        if self.brief.time_plan:
            return {p.phase: p.minutes for p in self.brief.time_plan}
        return DEFAULT_PLAN[self.brief.session.duration_min]

    # ------------------------------------------------------------------ take back

    # Everything a turn can change, without the clock. Voice uses this to take back a reply that
    # was not spoken because the candidate went on talking.
    _STATE = (
        "phase",
        "question",
        "probes_used",
        "hints_used",
        "ended",
        "asked",
        "dropped",
        "curveball_used",
        "candidate_questions",
        "probed_missing",
        "conduct_strikes",
        "_queue",
    )

    def snapshot(self) -> dict[str, object]:
        return {name: copy.copy(getattr(self, name)) for name in self._STATE}

    def restore(self, state: dict[str, object]) -> None:
        for name, value in state.items():
            setattr(self, name, copy.copy(value))

    # ------------------------------------------------------------------ clock

    @property
    def elapsed_ms(self) -> int:
        """Session time, without paused time."""
        return self._clock.elapsed()

    @property
    def paused(self) -> bool:
        return self._clock.paused_at is not None

    def deadline_ms(self, phase: Phase) -> int:
        """When `phase` should be over, in session time."""
        return self._deadline[phase]

    @property
    def mini(self) -> bool:
        """A 10-minute mini interview."""
        return self.brief.session.is_mini

    def _skipped(self, phase: Phase) -> bool:
        """True when the plan gives the phase 0 minutes, so it gets no turn of its own.
        A phase the plan does not list keeps its turn, as before."""
        return self._minutes.get(phase) == 0

    @property
    def probe_limit(self) -> int:
        limit = min(self.brief.max_probes_per_question, PROBE_LIMIT[self.brief.session.difficulty])
        return min(limit, MINI_MAX_PROBES) if self.mini else limit

    @property
    def needs_decision(self) -> bool:
        """True after an answer in CORE when the interviewer may still probe this question."""
        return (
            not self.ended
            and self.phase == Phase.CORE
            and self.question is not None
            and self.probes_used < self.probe_limit
            and self.elapsed_ms < self._deadline[Phase.CORE]
            and self._probe_fits()
        )

    # ------------------------------------------------------------------ Custom sessions (CU-4)

    @property
    def custom(self) -> bool:
        """A Custom session (CU-1): categories, own questions, must-ask questions."""
        return self.brief.session.custom is not None

    @property
    def must_ask_left(self) -> list[str]:
        """CU-4: the must-ask questions not asked yet. Derived from the queue, so a snapshot,
        a restore and `rebuild` from the transcript all keep it."""
        return [q.id for q in self._queue if q.must_ask]

    def _must_reserve_ms(self, probes: int) -> int:
        """The time the must-ask questions still to come need, with `probes` follow-ups each."""
        return len(self.must_ask_left) * (MUST_ASK_QUESTION_MS + probes * PROBE_MS)

    # The time-pressure rule (CU-4, D-6). While must-ask questions are still to come, the
    # controller gives way in this order as the CORE time left shrinks:
    #   1. Follow-ups on questions that are not must-ask stop (`_probe_fits`): a follow-up must
    #      leave time for one more question and for every must-ask question with one follow-up.
    #   2. Unasked questions that are not must-ask are skipped, the interviewer's (planner)
    #      questions before the candidate's own (`_pick_custom`): one is started only while the
    #      must-ask questions keep time for one follow-up each.
    #   3. Follow-ups on must-ask questions stop: one must leave time for the other must-ask
    #      questions with no follow-up.
    #   4. A must-ask question is never skipped. It is started even with less than
    #      MIN_QUESTION_MS of CORE left, then with no follow-up (the CORE deadline stops
    #      probes): asking it with 0 probes is preferred over running late with probes, so CORE
    #      ends late only by what the answers take. The session's hard end (duration_min) still
    #      wins; the controller, never the model, ends the session. The reserve is kept from the
    #      first question and the CU-3 caps keep the must-ask floor (2 minutes each) well under
    #      the CORE time, so only very long answers can reach the hard end first.
    # With no must-ask question left, a Custom session probes like the standard types; only
    # the skipping order (planner questions before the candidate's own) differs.

    def _probe_fits(self) -> bool:
        """CU-4: whether one more follow-up on the current question leaves time for the
        must-ask questions still to come (steps 1 and 3 above). Always true outside Custom."""
        if not self.custom or self.question is None or not self.must_ask_left:
            return True
        left = self._core_left_ms() - PROBE_MS
        if self.question.must_ask:
            return left >= self._must_reserve_ms(probes=0)
        more = MIN_QUESTION_MS if any(not q.must_ask for q in self._queue) else 0
        return left >= self._must_reserve_ms(probes=1) + more

    def _pick_custom(self) -> tuple[BriefQuestion | None, list[Why]]:
        """CU-4: the next question of a Custom session (steps 2 and 4 above).

        Counts how many questions that are not must-ask still fit, keeping the candidate's own
        before the planner's. The first must-ask or kept question in queue order is asked, so
        the category order holds. Questions passed over are dropped for good, so the session
        never goes back to an earlier category.
        """
        left = self._core_left_ms()
        others = [q for q in self._queue if not q.must_ask]
        fit = 0
        if left >= MIN_QUESTION_MS:
            fit = max(0, (left - self._must_reserve_ms(probes=1)) // MIN_QUESTION_MS)
        own = [q for q in others if q.source == QuestionSource.CANDIDATE]
        planner = [q for q in others if q.source != QuestionSource.CANDIDATE]
        keep = {q.id for q in [*own, *planner][:fit]}
        for i, q in enumerate(self._queue):
            if q.must_ask or q.id in keep:
                skipped = self._queue[:i]
                self.dropped.extend(s.id for s in skipped)
                self._queue = self._queue[i + 1 :]
                why = [Why.SKIPPED_FOR_TIME] if skipped else []
                if q.must_ask and left < MIN_QUESTION_MS:
                    why.append(Why.MUST_ASK_GUARANTEED)
                return q, why
        return None, []

    # ------------------------------------------------------------------ flow

    def start(self) -> Move:
        """Start the clock. The interviewer greets the candidate."""
        if self._clock.started is None:
            self._clock.started = self.clock()
        return Move(MoveKind.GREET, Phase.INTRO, reason=(Why.START,))

    def after_answer(
        self, decision: ProbeDecision | None = None, *, has_question: bool = True
    ) -> list[Move]:
        """The moves the interviewer makes after the candidate's turn.

        `decision` is the interviewer model's choice after an answer in CORE; it is ignored
        when the probe limit or the CORE time is used up. `has_question` tells, in the candidate
        questions phase, whether the candidate asked something.
        """
        if self.ended:
            return []
        if self.phase == Phase.WRAP_UP:
            self.ended = True
            return []
        if self.elapsed_ms >= self.total_ms:
            if self.phase == Phase.CANDIDATE_QUESTIONS and has_question:
                # No time to answer: the closing line acknowledges the question.
                return [
                    self._wrap_up(
                        Why.SESSION_TIME_UP, Why.CANDIDATE_QUESTION_LEFT_OPEN, open_question=True
                    )
                ]
            return [self._wrap_up(Why.SESSION_TIME_UP)]
        if self.phase == Phase.INTRO and not self._skipped(Phase.SMALL_TALK):
            self.phase = Phase.SMALL_TALK
            return [Move(MoveKind.SMALL_TALK, Phase.SMALL_TALK, reason=(Why.NEXT_PHASE,))]
        if self.phase in (Phase.INTRO, Phase.SMALL_TALK):
            self.phase = Phase.AGENDA
            agenda = Move(
                MoveKind.AGENDA, Phase.AGENDA, expects_answer=False, reason=(Why.NEXT_PHASE,)
            )
            return [agenda, *self._next_core(Why.NEXT_PHASE)]
        if self.phase == Phase.CORE:
            if decision is not None and decision.action == "probe" and self.needs_decision:
                missing = tuple(dict.fromkeys(decision.missing))  # in order, no duplicates
                if self.probes_used > 0:
                    # A later follow-up must aim at a gap not asked about yet. If the answer
                    # still lacks only what was already probed, asking again in new words does
                    # not help: move on.
                    missing = tuple(m for m in missing if m not in self.probed_missing)
                    if not missing:
                        return self._next_core(Why.SAME_GAP_NOT_FILLED)
                self.probes_used += 1
                self.probed_missing.extend(missing)
                return [
                    Move(
                        MoveKind.PROBE,
                        Phase.CORE,
                        self.question,
                        missing,
                        pushback=self.brief.pushback,
                        reason=(Why.MODEL_CHOSE_PROBE,),
                    )
                ]
            return self._next_core(self._moved_on_because(decision))
        if self.phase == Phase.CANDIDATE_QUESTIONS:
            in_time = self.elapsed_ms < self._deadline[Phase.CANDIDATE_QUESTIONS]
            if has_question and in_time and self.candidate_questions < MAX_CANDIDATE_QUESTIONS:
                self.candidate_questions += 1
                return [
                    Move(
                        MoveKind.ANSWER_QUESTION,
                        Phase.CANDIDATE_QUESTIONS,
                        reason=(Why.CANDIDATE_ASKED,),
                    )
                ]
            if not has_question:
                return [self._wrap_up(Why.CANDIDATE_HAD_NO_QUESTION)]
            why = Why.CANDIDATE_QUESTIONS_TIME_UP if not in_time else Why.CANDIDATE_QUESTIONS_LIMIT
            # The session still has time: answer this last question briefly, then close. The
            # wrap-up comes right after, so the answer does not invite more questions.
            self.candidate_questions += 1
            last_answer = Move(
                MoveKind.ANSWER_QUESTION,
                Phase.CANDIDATE_QUESTIONS,
                expects_answer=False,
                reason=(why, Why.ANSWER_BEFORE_CLOSE),
                closing=True,
            )
            return [last_answer, self._wrap_up(why)]
        return [self._wrap_up(Why.UNEXPECTED_PHASE)]  # AGENDA has no answer; recover by closing

    def _moved_on_because(self, decision: ProbeDecision | None) -> Why:
        """Why CORE left the current question (for the admin traces)."""
        if self.question is not None and self.probes_used >= self.probe_limit:
            return Why.PROBE_LIMIT_REACHED
        if self.elapsed_ms >= self._deadline[Phase.CORE]:
            return Why.CORE_TIME_UP
        if not self._probe_fits():
            return Why.PROBES_CUT_FOR_MUST_ASK
        if decision is None:
            return Why.NO_DECISION
        return Why.MODEL_CHOSE_MOVE_ON

    def conduct_strike(self, conduct: AnswerConduct) -> Move:
        """IV-12: the candidate's turn was outside the interview or inappropriate.

        Returns a WARN move while warnings are left; the question and the phase stay. Else the
        closing WRAP_UP, and the session has ended.
        """
        self.conduct_strikes += 1
        if self.conduct_strikes <= MAX_CONDUCT_WARNINGS:
            return Move(
                MoveKind.WARN,
                self.phase,
                self.question if self.phase == Phase.CORE else None,
                reason=(Why.CONDUCT_WARNING,),
                conduct=conduct,
                last_warning=self.conduct_strikes == MAX_CONDUCT_WARNINGS,
            )
        move = self._wrap_up(Why.CONDUCT_LIMIT)
        self.ended = True
        return Move(
            move.kind, move.phase, expects_answer=False, reason=move.reason, conduct=conduct
        )

    def end_now(self) -> Move:
        """Close the session early, for example when the candidate wants to stop."""
        return self._wrap_up(Why.ENDED_EARLY)

    def _core_left_ms(self) -> int:
        return self._deadline[Phase.CORE] - self.elapsed_ms

    def _next_core(self, why: Why) -> list[Move]:
        self.phase = Phase.CORE
        self.probes_used = 0
        self.probed_missing = []
        self.hints_used = 0
        enough_time = self._core_left_ms() >= MIN_QUESTION_MS
        if self.custom:  # the curveball must leave time for the must-ask questions (CU-4)
            enough_time = self._core_left_ms() >= MIN_QUESTION_MS + self._must_reserve_ms(1)
        curveball_due = (
            self.brief.curveball
            and not self.mini
            and not self.curveball_used
            and len(self.asked) == 1
        )
        if curveball_due and enough_time and self.brief.curveball:
            self.curveball_used = True
            self.question = self._curveball(self.brief.curveball)
            self.asked.append(CURVEBALL_REF)
            return [
                Move(MoveKind.CURVEBALL, Phase.CORE, self.question, reason=(why, Why.CURVEBALL_DUE))
            ]
        if self.custom:
            picked, extra = self._pick_custom()
            if picked is not None:
                self.question = picked
                self.asked.append(picked.id)
                reason = (why, *extra, Why.NEXT_QUESTION)
                return [Move(MoveKind.ASK, Phase.CORE, picked, reason=reason)]
        elif self._queue and enough_time:
            self.question = self._queue.pop(0)
            self.asked.append(self.question.id)
            return [Move(MoveKind.ASK, Phase.CORE, self.question, reason=(why, Why.NEXT_QUESTION))]
        stop = Why.NO_QUESTIONS_LEFT if not self._queue else Why.CORE_TIME_LEFT_UNDER_MIN
        self.dropped.extend(q.id for q in self._queue)
        self._queue = []
        self.question = None
        if self._skipped(Phase.CANDIDATE_QUESTIONS):
            return [self._wrap_up(why, stop, Why.NO_CANDIDATE_QUESTIONS_PHASE)]
        self.phase = Phase.CANDIDATE_QUESTIONS
        return [Move(MoveKind.INVITE_QUESTIONS, Phase.CANDIDATE_QUESTIONS, reason=(why, stop))]

    def _curveball(self, text: str) -> BriefQuestion:
        return BriefQuestion(
            id=CURVEBALL_REF,
            text=text,
            competencies=self.brief.target_competencies[:1],
            priority=99,
        )

    def _wrap_up(self, *why: Why, open_question: bool = False) -> Move:
        if self.phase == Phase.CORE:
            self.dropped.extend(q.id for q in self._queue)
            self._queue = []
        self.phase = Phase.WRAP_UP
        self.question = None
        return Move(MoveKind.WRAP_UP, Phase.WRAP_UP, reason=why, open_question=open_question)

    # ------------------------------------------------------------------ dropped connection (IV-9)

    def rebuild(self, turns: Sequence[Turn]) -> None:
        """IV-9: catch a new controller up with a saved transcript, for a resume that rebuilds
        the runner. The question bookkeeping comes from the interviewer turns' question_refs,
        not from memory: questions asked leave the queue (so `must_ask_left` holds), questions
        passed over before the last one asked are dropped, and the phase, the open question,
        its follow-up count and the session time go on from the last turn.
        """
        if not turns:
            return
        asked = list(
            dict.fromkeys(
                t.question_ref
                for t in turns
                if t.speaker == Speaker.INTERVIEWER and t.phase == Phase.CORE and t.question_ref
            )
        )
        by_id = {q.id: q for q in self.brief.questions}
        order = [q.id for q in self._order(self.brief.questions)]
        last_pos = max((order.index(ref) for ref in asked if ref in by_id), default=-1)
        self.asked = asked
        self.curveball_used = CURVEBALL_REF in asked
        self.dropped = [ref for ref in order[: last_pos + 1] if ref not in asked]
        self._queue = [by_id[ref] for ref in order[last_pos + 1 :]]
        last = turns[-1]
        self.phase = last.phase
        self.question = None
        self.probes_used = 0
        self.probed_missing = []
        self.hints_used = 0
        if last.phase == Phase.CORE and asked:
            current = asked[-1]
            if current == CURVEBALL_REF and self.brief.curveball:
                self.question = self._curveball(self.brief.curveball)
            else:
                self.question = by_id.get(current)
            said = [
                t for t in turns if t.speaker == Speaker.INTERVIEWER and t.question_ref == current
            ]
            self.probes_used = max(0, len(said) - 1)  # the ask, then one turn per follow-up
        if self._clock.started is None:
            self._clock.started = self.clock() - last.end_ms

    def hold(self) -> None:
        """Stop the clock while the candidate is disconnected. Allowed in every mode."""
        if self._clock.started is not None and self._clock.paused_at is None:
            self._clock.paused_at = self.clock()

    def release(self) -> None:
        """Restart the clock after a reconnect."""
        if self._clock.paused_at is not None:
            self._clock.paused_total += self.clock() - self._clock.paused_at
            self._clock.paused_at = None

    # ------------------------------------------------------------------ Coach mode (IV-8)

    def _coach(self) -> None:
        if not self.brief.coach_help:
            raise CoachNotAllowedError("pause, hint and redo exist only in Coach mode")

    def pause(self) -> None:
        self._coach()
        if self._clock.paused_at is None:
            self._clock.paused_at = self.clock()

    def resume(self) -> None:
        self._coach()
        if self._clock.paused_at is not None:
            self._clock.paused_total += self.clock() - self._clock.paused_at
            self._clock.paused_at = None

    def hint(self) -> Move | None:
        """A short nudge on the current question, never the answer. None when not allowed."""
        self._coach()
        if self.phase != Phase.CORE or self.question is None:
            return None
        if self.hints_used >= MAX_HINTS_PER_QUESTION:
            return None
        self.hints_used += 1
        return Move(MoveKind.HINT, Phase.CORE, self.question, reason=(Why.COACH_REQUEST,))

    def redo(self) -> Move | None:
        """Ask the current question again, so the candidate can give a new answer."""
        self._coach()
        if self.phase != Phase.CORE or self.question is None:
            return None
        self.probes_used = 0
        self.probed_missing = []
        return Move(MoveKind.REDO, Phase.CORE, self.question, reason=(Why.COACH_REQUEST,))
