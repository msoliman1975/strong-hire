"""Turn taking for the voice interview: one reply at a time, and requests for time to think.

When the candidate asks for a moment ("give me 30 seconds", "let me think"), the interviewer says
one short line and waits. The request is not an answer, so the question stays open.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Protocol

log = logging.getLogger(__name__)

# Only the end of the turn counts, and only in a short turn, so an answer that mentions
# "a few minutes" is not taken as a request.
TAIL_WORDS = 12
MAX_WORDS = 25

_THINKING = re.compile(
    r"\b(give me|let me have|can i (have|take|get)|i need|just|one|wait)\s+"
    r"(a|one|two|three|a few|a couple of|\d+|a quick)?\s*"
    r"(sec|secs|second|seconds|moment|moments|minute|minutes|min)\b"
    r"|\blet me (think|organi[sz]e|gather|collect)\b"
    r"|\b(organi[sz]e|gather|collect) my thoughts\b"
    r"|\bhold on\b"
    r"|\bthink (about it|about that|for a (sec|second|moment))\b",
    re.IGNORECASE,
)


def is_thinking_request(text: str) -> bool:
    """True when a short turn ends with a request for time to think."""
    words = text.split()
    if not words or len(words) > MAX_WORDS:
        return False
    return bool(_THINKING.search(" ".join(words[-TAIL_WORDS:])))


class Interview(Protocol):
    """The part of VoiceInterview that CandidateTurns uses."""

    async def on_candidate(
        self, text: str, spoken_s: float | None = None, superseded: Callable[[], bool] | None = None
    ) -> list[str] | None: ...

    async def on_thinking(self, text: str, spoken_s: float | None = None) -> list[str]: ...

    async def check_in(self) -> list[str]: ...


Speak = Callable[[list[str]], Awaitable[None]]


class CandidateTurns:
    """Holds the candidate's words until the interviewer's reply to them is spoken.

    LiveKit calls `on_turn` at each end of turn, one call at a time, and `on_user_state` when the
    candidate starts or stops speaking.
    - One reply at a time: replies are prepared under a lock.
    - If the candidate starts speaking again while a reply is prepared, the reply is taken back
      and their words wait. They are answered together with the next turn. If no next turn comes
      (the sound was not speech), they are answered `resume_wait_s` after the candidate stops.
    - "Give me a moment" gets one short line. After `thinking_wait_s` of silence the interviewer
      checks in once.
    """

    def __init__(
        self, interview: Interview, speak: Speak, *, thinking_wait_s: float, resume_wait_s: float
    ) -> None:
        self.interview = interview
        self._speak = speak
        self.thinking_wait_s = thinking_wait_s
        self.resume_wait_s = resume_wait_s
        self.pending: list[str] = []
        self._pending_s = 0.0
        self._preparing = False
        self._spoke_again = False
        self._lock = asyncio.Lock()
        self._think_timer: asyncio.Task[None] | None = None
        self._resume_timer: asyncio.Task[None] | None = None
        self.taken_back = 0  # replies taken back, for logs and tests

    async def on_turn(self, text: str, spoken_s: float | None = None) -> None:
        self._cancel_resume()
        if text.strip():
            self.pending.append(text.strip())
            self._pending_s += spoken_s or 0.0
        await self._reply()

    def on_user_state(self, state: str) -> None:
        if state == "speaking":
            self._cancel_think()
            self._cancel_resume()
            if self._preparing:
                self._spoke_again = True
        elif state == "listening" and self.pending and not self._preparing:
            self._cancel_resume()
            self._resume_timer = asyncio.create_task(self._answer_held())

    def close(self) -> None:
        self._cancel_think()
        self._cancel_resume()

    async def _reply(self) -> None:
        async with self._lock:
            if not self.pending:
                return
            text, spoken = " ".join(self.pending), self._pending_s
            if is_thinking_request(text):
                self._clear()
                lines = await self.interview.on_thinking(text, spoken)
                await self._speak(lines)
                self._start_think_timer()
                return
            self._preparing, self._spoke_again = True, False
            try:
                result = await self.interview.on_candidate(
                    text, spoken, superseded=lambda: self._spoke_again
                )
            finally:
                self._preparing = False
            if result is None:
                self.taken_back += 1
                log.info("candidate went on talking; reply taken back, words kept")
                return
            self._clear()
        await self._speak(result)

    async def _answer_held(self) -> None:
        await asyncio.sleep(self.resume_wait_s)
        await self._reply()

    async def _check_in(self) -> None:
        await asyncio.sleep(self.thinking_wait_s)
        async with self._lock:
            if self.pending:
                return
            lines = await self.interview.check_in()
        await self._speak(lines)

    def _start_think_timer(self) -> None:
        self._cancel_think()
        self._think_timer = asyncio.create_task(self._check_in())

    def _clear(self) -> None:
        self.pending.clear()
        self._pending_s = 0.0

    def _cancel_think(self) -> None:
        if self._think_timer is not None and not self._think_timer.done():
            self._think_timer.cancel()
        self._think_timer = None

    def _cancel_resume(self) -> None:
        if self._resume_timer is not None and not self._resume_timer.done():
            self._resume_timer.cancel()
        self._resume_timer = None
