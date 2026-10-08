"""The voice interview without LiveKit: what to say, the transcript, reconnect and the end (P7).

The LiveKit agent (strong_voice.interview_agent) passes in the candidate's final transcript of each
turn and speaks what this returns. The same InterviewRunner as the text channel runs the
interview, so the controller, the interviewer and the prompts are shared.

Only text is kept: each Turn is saved through the SessionStore. Audio is never written here.

Turn taking: the agent can take back a reply that was not spoken yet, when the candidate goes on
talking while the reply is prepared (`superseded`). The candidate's words are then answered
together with what they say next. A request for time to think ("give me a moment") gets one
short line, and the question stays open; after a long silence the interviewer checks in once.

Reconnect (IV-9): when the candidate drops, the session clock stops. If they come back within
RECONNECT_S, the interviewer says a short line and repeats its last turn, so the session goes on
at the same phase and question. If not, the session ends as interrupted and is billed for the
minutes used (the API does the billing and starts scoring).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from strong_core.schemas import Speaker, Turn, UsageComponent
from strong_interview import InterviewRunner

log = logging.getLogger(__name__)

RECONNECT_S = 120
TRACE_FLUSH_S = 5.0
WELCOME_BACK = "Welcome back. Let me repeat where we were."
TAKE_YOUR_TIME = "Sure, take your time. Go ahead whenever you are ready."
CHECK_IN = "No rush. Go ahead whenever you are ready, or ask me to repeat the question."


class SessionStore(Protocol):
    """Where the voice interview keeps its text-only record."""

    async def save_turn(self, session_id: uuid.UUID, turn: Turn) -> None: ...

    async def save_usage(
        self, session_id: uuid.UUID, component: UsageComponent, units: float, cost_usd: float = 0.0
    ) -> None: ...

    async def save_provenance(self, session_id: uuid.UUID, prompt_version: str | None) -> None: ...


class SessionFinisher(Protocol):
    """Ends the session in the API: bills the minutes and starts scoring."""

    async def finish(self, session_id: uuid.UUID, *, interrupted: bool) -> None: ...


@dataclass
class VoiceInterview:
    session_id: uuid.UUID
    runner: InterviewRunner
    store: SessionStore
    finisher: SessionFinisher
    now: Callable[[], float]
    reconnect_s: float = RECONNECT_S
    disconnected_at: float | None = None
    finished: bool = False
    _saved: int = field(default=0, init=False)

    @property
    def ended(self) -> bool:
        return self.runner.ended or self.finished

    async def _flush(self) -> list[str]:
        """Save turns not saved yet; return the new interviewer lines to speak."""
        new = self.runner.turns[self._saved :]
        self._saved = len(self.runner.turns)
        for turn in new:
            await self.store.save_turn(self.session_id, turn)
        return [t.text for t in new if t.speaker == Speaker.INTERVIEWER]

    async def opening(self) -> list[str]:
        await self.runner.open()
        return await self._flush()

    def _timing(self, spoken_s: float | None) -> tuple[int, int]:
        end = self.runner.controller.elapsed_ms
        return max(0, end - int((spoken_s or 0) * 1000)), end

    async def on_candidate(
        self,
        text: str,
        spoken_s: float | None = None,
        superseded: Callable[[], bool] | None = None,
    ) -> list[str] | None:
        """The candidate's final transcript of one turn. Returns what the interviewer says.

        `spoken_s` is how long the candidate spoke; it sets the turn's timing and the STT usage.
        If `superseded()` is true once the reply is ready, the candidate went on talking: the turn
        and the reply are taken back and None is returned. Nothing is saved for them.
        """
        if self.ended or not text.strip():
            return []
        start, end = self._timing(spoken_s)
        checkpoint = self.runner.checkpoint()
        await self.runner.respond(text, start_ms=start, end_ms=end)
        if superseded is not None and superseded():
            self.runner.rollback(checkpoint)
            return None
        lines = await self._flush()
        if self.runner.ended:
            await self.finish(interrupted=False)
        return lines

    async def on_thinking(self, text: str, spoken_s: float | None = None) -> list[str]:
        """The candidate asked for time to think. Say one short line; the question stays open."""
        if self.ended or not text.strip():
            return []
        start, end = self._timing(spoken_s)
        await self.runner.note(text, start_ms=start, end_ms=end)
        await self.runner.line(TAKE_YOUR_TIME, kind="take_your_time")
        return await self._flush()

    async def check_in(self) -> list[str]:
        """A long silence after a request for time: one gentle line, no new question."""
        if self.ended or self.disconnected_at is not None:
            return []
        await self.runner.line(CHECK_IN, kind="check_in")
        return await self._flush()

    async def coach(self, command: Literal["pause", "resume", "hint", "redo"]) -> list[str]:
        """Coach mode only (IV-8); raises CoachNotAllowedError in Realistic mode."""
        if self.ended:
            return []
        if command == "pause":
            self.runner.pause()
            return []
        if command == "resume":
            self.runner.resume()
            return []
        await self.runner.coach(command)
        return await self._flush()

    def on_disconnect(self) -> None:
        if self.ended or self.disconnected_at is not None:
            return
        self.disconnected_at = self.now()
        self.runner.controller.hold()

    def on_reconnect(self) -> list[str]:
        """Back within the window: same phase and question. Returns the lines to say again."""
        if self.ended or self.disconnected_at is None:
            return []
        self.disconnected_at = None
        self.runner.controller.release()
        last = next(
            (t.text for t in reversed(self.runner.turns) if t.speaker == Speaker.INTERVIEWER),
            None,
        )
        self.runner.trace_line("welcome_back", WELCOME_BACK)
        return [WELCOME_BACK, last] if last else [WELCOME_BACK]

    def reconnect_expired(self) -> bool:
        return (
            self.disconnected_at is not None
            and not self.ended
            and self.now() - self.disconnected_at >= self.reconnect_s
        )

    async def _flush_traces(self) -> None:
        """Wait (a short time) for trace rows still being written. Never raises."""
        flush = getattr(self.runner.trace, "flush", None)
        if flush is None:
            return
        try:
            result = flush()
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=TRACE_FLUSH_S)
        except Exception:
            log.warning("could not flush the traces of session %s", self.session_id, exc_info=True)

    async def finish(self, *, interrupted: bool) -> None:
        """End once: save usage and provenance, then let the API bill and start scoring."""
        if self.finished:
            return
        self.finished = True
        await self._flush()
        interviewer = self.runner.interviewer
        turns = self.runner.turns
        heard_s = sum(
            (t.end_ms - t.start_ms) / 1000 for t in turns if t.speaker == Speaker.CANDIDATE
        )
        spoken_chars = sum(len(t.text) for t in turns if t.speaker == Speaker.INTERVIEWER)
        tokens = interviewer.input_tokens + interviewer.output_tokens
        await self.store.save_usage(
            self.session_id, UsageComponent.LLM, tokens, cost_usd=round(interviewer.cost_usd, 6)
        )
        for component, units in (
            (UsageComponent.STT, round(heard_s, 2)),
            (UsageComponent.TTS, spoken_chars),
        ):
            await self.store.save_usage(self.session_id, component, units)
        refs = ",".join(sorted(interviewer.prompt_refs))[:200] or None
        await self.store.save_provenance(self.session_id, refs)
        await self._flush_traces()
        try:
            await self.finisher.finish(self.session_id, interrupted=interrupted)
        except Exception:
            log.exception("could not end session %s in the API", self.session_id)
