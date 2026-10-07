"""Session controller: the conversation state machine and the clock (IV-3, IV-4, IV-7, IV-8).

INTRO -> SMALL_TALK -> AGENDA -> CORE (question, answer, follow-ups) -> CANDIDATE_QUESTIONS ->
WRAP_UP. The controller decides every phase change and when the session ends; the model never
does. The interviewer model only chooses what to say, and in CORE whether to probe. The
controller caps probes per question by difficulty, so a weak model cannot loop.

Time: each phase gets minutes from the brief's time_plan (or a default plan). CORE stops
starting new questions when less than MIN_QUESTION_MS is left; lower-priority questions are
dropped. Coach mode can pause the clock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from strong_core.schemas import (
    BriefQuestion,
    Difficulty,
    InterviewerBrief,
    Phase,
    ProbeDecision,
    ProbeTrigger,
)

# IV-3: most follow-ups per question. The brief's max_probes_per_question can only lower it.
PROBE_LIMIT: dict[Difficulty, int] = {
    Difficulty.FRIENDLY: 1,
    Difficulty.REALISTIC: 2,
    Difficulty.TOUGH: 3,
}
# Minutes per phase when the brief has no time_plan (IV-7). Each plan adds up to the duration.
DEFAULT_PLAN: dict[int, dict[Phase, int]] = {
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


@dataclass(frozen=True)
class Move:
    kind: MoveKind
    phase: Phase
    question: BriefQuestion | None = None
    missing: tuple[ProbeTrigger, ...] = ()
    pushback: bool = False
    expects_answer: bool = True

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

    def __post_init__(self) -> None:
        self._clock = _Clock(self.clock)
        self._queue = sorted(self.brief.questions, key=lambda q: q.priority)
        minutes = self._plan()
        self._deadline: dict[Phase, int] = {}
        total = 0
        for phase in ORDER:
            total += minutes.get(phase, 0) * 60 * 1000
            self._deadline[phase] = total
        self.total_ms = self.brief.session.duration_min * 60 * 1000

    def _plan(self) -> dict[Phase, int]:
        if self.brief.time_plan:
            return {p.phase: p.minutes for p in self.brief.time_plan}
        return DEFAULT_PLAN[self.brief.session.duration_min]

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
    def probe_limit(self) -> int:
        return min(self.brief.max_probes_per_question, PROBE_LIMIT[self.brief.session.difficulty])

    @property
    def needs_decision(self) -> bool:
        """True after an answer in CORE when the interviewer may still probe this question."""
        return (
            not self.ended
            and self.phase == Phase.CORE
            and self.question is not None
            and self.probes_used < self.probe_limit
            and self.elapsed_ms < self._deadline[Phase.CORE]
        )

    # ------------------------------------------------------------------ flow

    def start(self) -> Move:
        """Start the clock. The interviewer greets the candidate."""
        if self._clock.started is None:
            self._clock.started = self.clock()
        return Move(MoveKind.GREET, Phase.INTRO)

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
            return [self._wrap_up()]
        if self.phase == Phase.INTRO:
            self.phase = Phase.SMALL_TALK
            return [Move(MoveKind.SMALL_TALK, Phase.SMALL_TALK)]
        if self.phase == Phase.SMALL_TALK:
            self.phase = Phase.AGENDA
            return [Move(MoveKind.AGENDA, Phase.AGENDA, expects_answer=False), *self._next_core()]
        if self.phase == Phase.CORE:
            if decision is not None and decision.action == "probe" and self.needs_decision:
                self.probes_used += 1
                return [
                    Move(
                        MoveKind.PROBE,
                        Phase.CORE,
                        self.question,
                        tuple(decision.missing),
                        pushback=self.brief.pushback,
                    )
                ]
            return self._next_core()
        if self.phase == Phase.CANDIDATE_QUESTIONS:
            in_time = self.elapsed_ms < self._deadline[Phase.CANDIDATE_QUESTIONS]
            if has_question and in_time and self.candidate_questions < MAX_CANDIDATE_QUESTIONS:
                self.candidate_questions += 1
                return [Move(MoveKind.ANSWER_QUESTION, Phase.CANDIDATE_QUESTIONS)]
            return [self._wrap_up()]
        return [self._wrap_up()]  # AGENDA has no answer; recover by closing

    def end_now(self) -> Move:
        """Close the session early, for example when the candidate wants to stop."""
        return self._wrap_up()

    def _core_left_ms(self) -> int:
        return self._deadline[Phase.CORE] - self.elapsed_ms

    def _next_core(self) -> list[Move]:
        self.phase = Phase.CORE
        self.probes_used = 0
        self.hints_used = 0
        enough_time = self._core_left_ms() >= MIN_QUESTION_MS
        curveball_due = self.brief.curveball and not self.curveball_used and len(self.asked) == 1
        if curveball_due and enough_time and self.brief.curveball:
            self.curveball_used = True
            self.question = BriefQuestion(
                id=CURVEBALL_REF,
                text=self.brief.curveball,
                competencies=self.brief.target_competencies[:1],
                priority=99,
            )
            self.asked.append(CURVEBALL_REF)
            return [Move(MoveKind.CURVEBALL, Phase.CORE, self.question)]
        if self._queue and enough_time:
            self.question = self._queue.pop(0)
            self.asked.append(self.question.id)
            return [Move(MoveKind.ASK, Phase.CORE, self.question)]
        self.dropped.extend(q.id for q in self._queue)
        self._queue = []
        self.question = None
        self.phase = Phase.CANDIDATE_QUESTIONS
        return [Move(MoveKind.INVITE_QUESTIONS, Phase.CANDIDATE_QUESTIONS)]

    def _wrap_up(self) -> Move:
        if self.phase == Phase.CORE:
            self.dropped.extend(q.id for q in self._queue)
            self._queue = []
        self.phase = Phase.WRAP_UP
        self.question = None
        return Move(MoveKind.WRAP_UP, Phase.WRAP_UP)

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
        return Move(MoveKind.HINT, Phase.CORE, self.question)

    def redo(self) -> Move | None:
        """Ask the current question again, so the candidate can give a new answer."""
        self._coach()
        if self.phase != Phase.CORE or self.question is None:
            return None
        self.probes_used = 0
        return Move(MoveKind.REDO, Phase.CORE, self.question)
