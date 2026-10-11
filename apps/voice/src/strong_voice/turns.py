"""Turn taking for the voice interview: one reply at a time, and requests for time to think.

When the candidate asks for a moment ("give me 30 seconds", "let me think"), the interviewer says
one short line and waits. The request is not an answer, so the question stays open.

A request for minutes ("give me 3 minutes to prepare") starts prep time instead (IV-11): the clock
stops and a timer runs. During prep, "I'm ready" or a real answer ends it; a few words said while
thinking aloud are ignored.
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


_PREP = re.compile(
    r"\b(give me|let me have|can i (have|take|get)|could i (have|take|get)|i need|i'?d like)\s+"
    r"(?P<count>a|an|one|two|three|a few|a couple of|a couple|1|2|3)\s*(more\s+)?"
    r"(minute|minutes|min|mins)\b",
    re.IGNORECASE,
)
_PREP_COUNT = {"a": 1, "an": 1, "one": 1, "1": 1, "two": 2, "2": 2, "a couple": 2, "a couple of": 2}
_READY = re.compile(
    r"\b(i'?m|i am|we'?re) (ready|done|good to go)\b"
    r"|\b(ok(ay)?|alright|right),? (ready|let'?s go)\b"
    r"|^\s*ready\b",
    re.IGNORECASE,
)
# During prep, a turn this long is an answer: prep ends and the interviewer replies.
ANSWER_WORDS = 8


def prep_request_minutes(text: str) -> int | None:
    """Minutes asked for in a short turn ("give me 3 minutes"), 1 to 3. None if not a request."""
    words = text.split()
    if not words or len(words) > MAX_WORDS:
        return None
    match = _PREP.search(" ".join(words[-TAIL_WORDS:]))
    if match is None:
        return None
    return _PREP_COUNT.get(match.group("count").lower(), 3)  # "three", "a few": the longest prep


def is_ready(text: str) -> bool:
    """True for "I'm ready", "okay, let's go" and the like, in a short turn."""
    return len(text.split()) <= MAX_WORDS and bool(_READY.search(text))


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

    @property
    def preparing(self) -> bool: ...

    async def start_prep(
        self, minutes: int, text: str | None = None, spoken_s: float | None = None
    ) -> list[str]: ...

    async def end_prep(self, *, timed_out: bool = False, say: bool = True) -> list[str]: ...


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
    - "Give me 3 minutes" (or the prep button) starts prep time with its own timer (IV-11).
    """

    def __init__(
        self,
        interview: Interview,
        speak: Speak,
        *,
        thinking_wait_s: float,
        resume_wait_s: float,
        minute_s: float = 60.0,
    ) -> None:
        self.interview = interview
        self._speak = speak
        self.thinking_wait_s = thinking_wait_s
        self.resume_wait_s = resume_wait_s
        self.minute_s = minute_s  # tests make a prep minute short
        self.pending: list[str] = []
        self._pending_s = 0.0
        self._preparing = False
        self._spoke_again = False
        self._lock = asyncio.Lock()
        self._think_timer: asyncio.Task[None] | None = None
        self._resume_timer: asyncio.Task[None] | None = None
        self._prep_timer: asyncio.Task[None] | None = None
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
        self._cancel_prep()

    async def start_prep(
        self, minutes: int, text: str | None = None, spoken_s: float | None = None
    ) -> None:
        """IV-11: from the prep button, or from a spoken request (`text`)."""
        async with self._lock:
            lines = await self._begin_prep(minutes, text, spoken_s)
        await self._speak(lines)

    async def ready(self) -> None:
        """The "I'm ready" button: prep ends and the interviewer says so."""
        async with self._lock:
            self._cancel_prep()
            lines = await self.interview.end_prep()
        await self._speak(lines)

    async def _begin_prep(
        self, minutes: int, text: str | None, spoken_s: float | None
    ) -> list[str]:
        self._cancel_think()
        lines = await self.interview.start_prep(minutes, text, spoken_s)
        if self.interview.preparing:
            self._cancel_prep()
            self._prep_timer = asyncio.create_task(
                self._prep_over(max(1, min(3, minutes)) * self.minute_s)
            )
        return lines

    async def _prep_over(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        async with self._lock:
            lines = await self.interview.end_prep(timed_out=True)
        await self._speak(lines)

    async def _reply(self) -> None:
        async with self._lock:
            if not self.pending:
                return
            text, spoken = " ".join(self.pending), self._pending_s
            if self.interview.preparing:
                if is_ready(text):
                    self._clear()
                    self._cancel_prep()
                    lines = await self.interview.end_prep()
                    await self._speak(lines)
                    return
                if len(text.split()) < ANSWER_WORDS:
                    self._clear()  # thinking aloud during prep: not an answer
                    return
                self._cancel_prep()
                await self.interview.end_prep(say=False)  # they started to answer
            minutes = prep_request_minutes(text)
            if minutes is not None:
                self._clear()
                lines = await self._begin_prep(minutes, text, spoken)
                await self._speak(lines)
                return
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

    def _cancel_prep(self) -> None:
        if (
            self._prep_timer is not None
            and not self._prep_timer.done()
            and self._prep_timer is not asyncio.current_task()
        ):
            self._prep_timer.cancel()
        self._prep_timer = None

    def _cancel_resume(self) -> None:
        if self._resume_timer is not None and not self._resume_timer.done():
            self._resume_timer.cancel()
        self._resume_timer = None
