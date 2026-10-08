"""Runs one interview turn by turn and keeps the transcript (text only; audio never comes here).

The voice agent, the text-mode session API and the tests use the same runner: they pass in the
candidate's text and get back the interviewer's turns. Each Turn gets its phase, its timing in
session time and, in CORE, the question it belongs to.

With a TraceSink (R2), each interviewer model call (say and decide), each fixed line and each
take-back is written as a TraceRecord with the controller's move, the reason and the timer
state. A sink error is logged and ignored, so tracing never breaks the interview.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from strong_core.schemas import Phase, ProbeDecision, Speaker, Turn
from strong_interview.controller import Move, SessionController
from strong_interview.interviewer import Interviewer
from strong_interview.trace import ModelCall, TraceCall, TraceRecord, TraceSink, message_dicts

log = logging.getLogger(__name__)

MS_PER_WORD = 400  # about 150 spoken words per minute, for text-mode timings
_NO_QUESTION = re.compile(
    r"^\s*(no|nope|not really|nothing|none|i'?m good|i am good|that'?s (all|it)|no more)\b",
    re.IGNORECASE,
)

TurnHook = Callable[[Turn], Awaitable[None] | None]


@dataclass(frozen=True)
class Checkpoint:
    """The transcript length and controller state before a turn (see InterviewRunner.rollback)."""

    turns: int
    controller: dict[str, object]


def wants_to_ask(text: str) -> bool:
    """In the candidate questions phase: did the candidate ask something?"""
    return "?" in text or not _NO_QUESTION.search(text)


class InterviewRunner:
    def __init__(
        self,
        controller: SessionController,
        interviewer: Interviewer,
        *,
        on_turn: TurnHook | None = None,
        trace: TraceSink | None = None,
    ) -> None:
        self.controller = controller
        self.interviewer = interviewer
        self.on_turn = on_turn
        self.trace = trace
        self.turns: list[Turn] = []
        self._seq = 0

    @property
    def ended(self) -> bool:
        return self.controller.ended

    # ------------------------------------------------------------------ traces (R2)

    def _timer(self, phase: Phase) -> dict[str, Any]:
        ctl = self.controller
        return {
            "probes_used": ctl.probes_used,
            "probe_limit": ctl.probe_limit,
            "time_left_in_phase_ms": ctl.deadline_ms(phase) - ctl.elapsed_ms,
            "time_left_in_session_ms": ctl.total_ms - ctl.elapsed_ms,
        }

    def _emit(
        self,
        call: TraceCall,
        move: str,
        reason: dict[str, Any],
        *,
        phase: Phase,
        elapsed_ms: int,
        question_ref: str | None = None,
        model_call: ModelCall | None = None,
        spoken: str | None = None,
        turn_index: int | None = None,
    ) -> None:
        if self.trace is None:
            return
        try:
            self._seq += 1
            record = TraceRecord(
                seq=self._seq,
                turn_index=len(self.turns) if turn_index is None else turn_index,
                call=call,
                move=move,
                reason=reason,
                phase=phase,
                elapsed_ms=elapsed_ms,
                phase_deadline_ms=self.controller.deadline_ms(phase),
                question_ref=question_ref,
                spoken_text=spoken,
            )
            if model_call is not None:
                record = dataclasses.replace(
                    record,
                    messages=message_dicts(model_call.messages),
                    raw_reply=model_call.raw_reply,
                    model=model_call.model,
                    prompt_refs=model_call.prompt_refs,
                    input_tokens=model_call.input_tokens,
                    output_tokens=model_call.output_tokens,
                    cost_usd=model_call.cost_usd,
                    latency_ms=model_call.latency_ms,
                    error=model_call.error,
                )
            self.trace.write(record)
        except Exception:
            log.warning("could not write an interviewer trace", exc_info=True)

    def trace_line(self, kind: str, text: str) -> None:
        """Trace a fixed line that is said but not kept in the transcript ("welcome back")."""
        ctl = self.controller
        self._emit(
            "line", kind, {"why": [kind]}, phase=ctl.phase, elapsed_ms=ctl.elapsed_ms, spoken=text
        )

    # ------------------------------------------------------------------ turns

    async def _add(self, turn: Turn) -> Turn:
        self.turns.append(turn)
        if self.on_turn is not None:
            result = self.on_turn(turn)
            if inspect.isawaitable(result):
                await result
        return turn

    async def _say(self, move: Move, decision: ProbeDecision | None = None) -> Turn:
        before = self.controller.elapsed_ms
        reason: dict[str, Any] = {
            "why": [w.value for w in move.reason],
            "missing": [m.value for m in move.missing],
            "pushback": move.pushback,
            "decision": None if decision is None else decision.model_dump(mode="json"),
            **self._timer(move.phase),
        }
        turn_index = len(self.turns)
        self.interviewer.last_call = None
        text: str | None = None
        try:
            text = await self.interviewer.say(move, self.turns)
        finally:
            self._emit(
                "say",
                move.kind.value,
                reason,
                phase=move.phase,
                elapsed_ms=before,
                question_ref=move.question_ref,
                model_call=self.interviewer.last_call,
                spoken=text,
                turn_index=turn_index,
            )
        assert text is not None
        start = self.controller.elapsed_ms
        end = start + max(1, len(text.split())) * MS_PER_WORD
        turn = Turn(
            speaker=Speaker.INTERVIEWER,
            phase=move.phase,
            text=text,
            start_ms=start,
            end_ms=end,
            question_ref=move.question_ref,
        )
        return await self._add(turn)

    async def open(self) -> list[Turn]:
        """Start the session: the interviewer greets the candidate."""
        return [await self._say(self.controller.start())]

    async def respond(
        self, text: str, *, start_ms: int | None = None, end_ms: int | None = None
    ) -> list[Turn]:
        """Record the candidate's turn and return the interviewer's next turns.

        Returns an empty list once the session has ended.
        """
        ctl = self.controller
        if ctl.ended:
            return []
        now = ctl.elapsed_ms
        start = now if start_ms is None else start_ms
        ref = ctl.question.id if ctl.phase == Phase.CORE and ctl.question else None
        await self._add(
            Turn(
                speaker=Speaker.CANDIDATE,
                phase=ctl.phase,
                text=text.strip() or "...",
                start_ms=start,
                end_ms=max(start, now if end_ms is None else end_ms),
                question_ref=ref,
            )
        )
        decision = None
        if ctl.needs_decision and ctl.question is not None:
            before = ctl.elapsed_ms
            timer = self._timer(Phase.CORE)
            self.interviewer.last_call = None
            decision = await self.interviewer.decide(ctl.question, text, self.turns)
            self._emit(
                "decide",
                "decide",
                {"decision": decision.model_dump(mode="json"), **timer},
                phase=Phase.CORE,
                elapsed_ms=before,
                question_ref=ctl.question.id,
                model_call=self.interviewer.last_call,
            )
        moves = ctl.after_answer(decision, has_question=wants_to_ask(text))
        return [await self._say(move, decision) for move in moves]

    def checkpoint(self) -> Checkpoint:
        return Checkpoint(len(self.turns), self.controller.snapshot())

    def rollback(self, checkpoint: Checkpoint) -> None:
        """Take back the turns since `checkpoint`, as if they never happened.

        Only for callers without `on_turn`: the hook has already seen the turns. The traces of
        the model calls stay, followed by a "rollback" trace.
        """
        assert self.on_turn is None, "rollback cannot undo on_turn calls"
        taken_back = len(self.turns) - checkpoint.turns
        del self.turns[checkpoint.turns :]
        self.controller.restore(checkpoint.controller)
        ctl = self.controller
        self._emit(
            "rollback",
            "rollback",
            {"why": ["candidate_kept_talking"], "turns_taken_back": taken_back},
            phase=ctl.phase,
            elapsed_ms=ctl.elapsed_ms,
        )

    async def note(
        self, text: str, *, start_ms: int | None = None, end_ms: int | None = None
    ) -> Turn:
        """Record a candidate turn that is not an answer (for example "give me a moment").

        The controller does not move on, so the question stays open.
        """
        ctl = self.controller
        now = ctl.elapsed_ms
        start = now if start_ms is None else start_ms
        return await self._add(
            Turn(
                speaker=Speaker.CANDIDATE,
                phase=ctl.phase,
                text=text.strip() or "...",
                start_ms=start,
                end_ms=max(start, now if end_ms is None else end_ms),
                question_ref=ctl.question.id if ctl.phase == Phase.CORE and ctl.question else None,
            )
        )

    async def line(self, text: str, kind: str = "fixed_line") -> Turn:
        """Record a fixed interviewer line, said without a model call. The controller stays.

        `kind` names the line in the traces, for example "take_your_time".
        """
        ctl = self.controller
        start = ctl.elapsed_ms
        ref = ctl.question.id if ctl.phase == Phase.CORE and ctl.question else None
        self._emit(
            "line",
            kind,
            {"why": [kind]},
            phase=ctl.phase,
            elapsed_ms=start,
            question_ref=ref,
            spoken=text,
        )
        return await self._add(
            Turn(
                speaker=Speaker.INTERVIEWER,
                phase=ctl.phase,
                text=text,
                start_ms=start,
                end_ms=start + max(1, len(text.split())) * MS_PER_WORD,
                question_ref=ref,
            )
        )

    async def coach(self, command: Literal["hint", "redo"]) -> list[Turn]:
        """Coach mode only (IV-8). Raises CoachNotAllowedError in Realistic mode."""
        move = self.controller.hint() if command == "hint" else self.controller.redo()
        return [] if move is None else [await self._say(move)]

    def pause(self) -> None:
        self.controller.pause()

    def resume(self) -> None:
        self.controller.resume()

    async def close(self) -> list[Turn]:
        """End early: the interviewer wraps up, and the session ends."""
        if self.controller.ended:
            return []
        turns = [await self._say(self.controller.end_now())]
        self.controller.ended = True
        return turns
