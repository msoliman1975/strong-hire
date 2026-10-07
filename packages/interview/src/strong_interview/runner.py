"""Runs one interview turn by turn and keeps the transcript (text only; audio never comes here).

The voice agent, the text-mode session API and the tests use the same runner: they pass in the
candidate's text and get back the interviewer's turns. Each Turn gets its phase, its timing in
session time and, in CORE, the question it belongs to.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Literal

from strong_core.schemas import Phase, Speaker, Turn
from strong_interview.controller import Move, SessionController
from strong_interview.interviewer import Interviewer

MS_PER_WORD = 400  # about 150 spoken words per minute, for text-mode timings
_NO_QUESTION = re.compile(
    r"^\s*(no|nope|not really|nothing|none|i'?m good|i am good|that'?s (all|it)|no more)\b",
    re.IGNORECASE,
)

TurnHook = Callable[[Turn], Awaitable[None] | None]


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
    ) -> None:
        self.controller = controller
        self.interviewer = interviewer
        self.on_turn = on_turn
        self.turns: list[Turn] = []

    @property
    def ended(self) -> bool:
        return self.controller.ended

    async def _add(self, turn: Turn) -> Turn:
        self.turns.append(turn)
        if self.on_turn is not None:
            result = self.on_turn(turn)
            if inspect.isawaitable(result):
                await result
        return turn

    async def _say(self, move: Move) -> Turn:
        text = await self.interviewer.say(move, self.turns)
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
            decision = await self.interviewer.decide(ctl.question, text, self.turns)
        moves = ctl.after_answer(decision, has_question=wants_to_ask(text))
        return [await self._say(move) for move in moves]

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
