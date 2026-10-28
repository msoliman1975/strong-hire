"""The voice coach without LiveKit: what to say, takes, reconnect and the end (CO-6).

The LiveKit agent (strong_voice.coach_agent) passes in the candidate's final transcript of each
turn and speaks what this returns. The coach's turn logic is the API's (strong_api.coach, S30):
each turn goes to its internal endpoint, which saves both turns, updates the story's parts and
returns the reply. So the text and the voice coach share the engine, the prompts and the rules.

VoiceCoach has the same interface as VoiceInterview, so the interview's turn taking
(strong_voice.turns.CandidateTurns) runs it unchanged. A coach session has no phases and no
clock: there is no prep time, and the session ends only when the candidate ends it (or the API
ends it, after the third IV-12 warning).

A reply cannot be taken back: the API saved the turn when it answered. When the candidate goes on
talking while the reply is prepared, the reply is still spoken, and their next words are a new
turn.

Takes (CO-6, CO-7): between "take_start" and "take_end" the coach stays quiet and keeps the
candidate's words. The take is one telling of the story: its transcript and length go to the
browser, which sends them to the take scoring (S33). Audio is never stored.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from strong_voice.interview import RECONNECT_S, TAKE_YOUR_TIME, WELCOME_BACK

log = logging.getLogger(__name__)

SAY_AGAIN = "Sorry, I lost that. Could you say it again?"
TAKE_STARTED = "Go ahead. Tell the whole story, and I'll stay quiet until you stop the take."
TAKE_DONE = "Thanks. That take is saved for scoring."
TAKE_EMPTY = "I didn't catch anything in that take. Start another one whenever you're ready."
TAKE_CANCELLED = "Okay, that take is dropped."


class CoachTurnError(Exception):
    """The API could not answer the turn (timeout, network). The candidate is asked again."""


class CoachApi(Protocol):
    """The API's coach turn logic, as the voice agent reaches it."""

    async def turn(self, session_id: uuid.UUID, text: str) -> dict[str, Any]: ...

    async def end(self, session_id: uuid.UUID) -> None: ...


@dataclass(frozen=True)
class VoiceTake:
    """One spoken telling of the story. Only its transcript is kept."""

    text: str
    duration_s: float


@dataclass
class VoiceCoach:
    session_id: uuid.UUID
    api: CoachApi
    now: Callable[[], float]
    opener: str | None = None
    reconnect_s: float = RECONNECT_S
    disconnected_at: float | None = None
    finished: bool = False
    last_result: dict[str, Any] | None = None
    _closed: bool = field(default=False, init=False)
    _last_line: str | None = field(default=None, init=False)
    _take: list[str] | None = field(default=None, init=False)
    _take_s: float = field(default=0.0, init=False)
    _take_started: float = field(default=0.0, init=False)

    @property
    def ended(self) -> bool:
        return self.finished

    @property
    def recording(self) -> bool:
        """True while a take is being recorded."""
        return self._take is not None

    # A coach session has no prep time (IV-11 is for interviews).
    preparing = False

    def _say(self, lines: list[str]) -> list[str]:
        if lines:
            self._last_line = lines[-1]
        return lines

    async def opening(self) -> list[str]:
        """The API wrote the coach's first line when the session started; say it."""
        return self._say([self.opener]) if self.opener else []

    async def on_candidate(
        self,
        text: str,
        spoken_s: float | None = None,
        superseded: Callable[[], bool] | None = None,
    ) -> list[str] | None:
        """The candidate's final transcript of one turn. Returns what the coach says.

        `superseded` is ignored: the API saved the turn, so the reply is never taken back."""
        if self.ended or not text.strip():
            return []
        if self._take is not None:
            self._keep(text, spoken_s)
            return []
        try:
            result = await self.api.turn(self.session_id, text.strip())
        except CoachTurnError:
            log.warning("coach turn of %s failed; asking again", self.session_id, exc_info=True)
            return self._say([SAY_AGAIN])
        self.last_result = result
        if result.get("ended"):
            self.finished = True
        message = (result.get("reply") or {}).get("message") or ""
        return self._say([message] if message else [])

    async def on_thinking(self, text: str, spoken_s: float | None = None) -> list[str]:
        """ "Let me think": one short line. During a take the words are part of the take."""
        if self.ended or not text.strip():
            return []
        if self._take is not None:
            self._keep(text, spoken_s)
            return []
        return self._say([TAKE_YOUR_TIME])

    async def check_in(self) -> list[str]:
        """The coach waits as long as the candidate needs; no check-in line."""
        return []

    async def start_prep(
        self, minutes: int, text: str | None = None, spoken_s: float | None = None
    ) -> list[str]:
        """ "Give me a minute" has no timer in a coach session: it is a request to think."""
        if text:
            return await self.on_thinking(text, spoken_s)
        return []

    async def end_prep(self, *, timed_out: bool = False, say: bool = True) -> list[str]:
        return []

    def _keep(self, text: str, spoken_s: float | None) -> None:
        assert self._take is not None
        self._take.append(text.strip())
        self._take_s += spoken_s or 0.0

    def start_take(self) -> list[str]:
        """Start recording a take. Starting again while recording does nothing."""
        if self.ended or self._take is not None:
            return []
        self._take, self._take_s, self._take_started = [], 0.0, self.now()
        return self._say([TAKE_STARTED])

    def end_take(self) -> tuple[VoiceTake | None, list[str]]:
        """Stop recording. Returns the take (None if nothing was said) and what to say."""
        if self._take is None:
            return None, []
        words, spoken = self._take, self._take_s
        self._take = None
        text = " ".join(w for w in words if w)
        if not text:
            return None, self._say([TAKE_EMPTY])
        # The take lasts from start to stop; the spoken time is the floor when the clock is off.
        duration = max(spoken, self.now() - self._take_started)
        return VoiceTake(text=text, duration_s=round(duration, 1)), self._say([TAKE_DONE])

    def cancel_take(self) -> list[str]:
        if self._take is None:
            return []
        self._take = None
        return self._say([TAKE_CANCELLED])

    def on_disconnect(self) -> None:
        if self.ended or self.disconnected_at is not None:
            return
        self.disconnected_at = self.now()

    def on_reconnect(self) -> list[str]:
        """Back within the window: the coach repeats its last line."""
        if self.ended or self.disconnected_at is None:
            return []
        self.disconnected_at = None
        last = self._last_line
        return [WELCOME_BACK, last] if last else [WELCOME_BACK]

    def reconnect_expired(self) -> bool:
        return (
            self.disconnected_at is not None
            and not self.ended
            and self.now() - self.disconnected_at >= self.reconnect_s
        )

    async def finish(self) -> None:
        """End once. The API records the minutes and drops a new story that stayed empty.

        A session the API already ended (its third IV-12 warning) is ended again: that is
        harmless in the API, and it keeps this path the same for both."""
        if self._closed:
            return
        self._closed = True
        self.finished = True
        self._take = None
        try:
            await self.api.end(self.session_id)
        except Exception:
            log.exception("could not end coach session %s in the API", self.session_id)
