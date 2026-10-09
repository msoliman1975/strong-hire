"""LiveKit glue for a real interview session (P7, IV-1, IV-8, IV-9).

A room named "session-<uuid>" is a real interview. The agent loads the session's brief, runs
strong_interview through VoiceInterview, and speaks what it returns. LiveKit's own LLM reply is
skipped (StopResponse): the interviewer and the controller decide what is said.

From the browser, on the data channel (topic "coach"): {"command": "hint" | "redo" | "pause" |
"resume" | "end"}. "end" means the candidate clicked End interview.
To the browser (topic "session"):
  {"type": "state", "phase", "paused", "elapsed_ms", "said": [lines]}  after each interviewer turn
  {"type": "ended"}                                                     when the session is over
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, StopResponse, llm
from livekit.agents.voice.room_io import RoomOptions

from strong_core.db import get_sessionmaker
from strong_core.gateway import get_gateway
from strong_core.sim import gateway_for_org
from strong_interview import (
    CoachNotAllowedError,
    Interviewer,
    InterviewRunner,
    SessionController,
)
from strong_interview.trace_store import SqlTraceSink
from strong_voice.interview import VoiceInterview
from strong_voice.session_store import (
    AgentApiSettings,
    ApiFinisher,
    SqlSessionStore,
    load_session,
    session_id_from_room,
)
from strong_voice.settings import get_voice_settings
from strong_voice.turns import CandidateTurns

log = logging.getLogger("strong_voice.interview")

COACH_TOPIC = "coach"
SESSION_TOPIC = "session"
COACH_COMMANDS = {"hint", "redo", "pause", "resume"}


def state_message(interview: VoiceInterview, said: list[str]) -> bytes:
    """What the browser shows: the phase, the clock and the interviewer's words (captions)."""
    controller = interview.runner.controller
    return json.dumps(
        {
            "type": "state",
            "phase": controller.phase.value,
            "paused": controller.paused,
            "elapsed_ms": controller.elapsed_ms,
            "said": said,
        }
    ).encode()


class InterviewAgent(Agent):
    def __init__(self, interview: VoiceInterview, on_ended: Any, notify: Any) -> None:
        super().__init__(instructions="Unused: strong_interview decides what is said.")
        self.interview = interview
        self._on_ended = on_ended
        self._notify = notify
        settings = get_voice_settings()
        self.turns = CandidateTurns(
            interview,
            self.speak,
            thinking_wait_s=settings.thinking_wait_s,
            # Longer than the longest end-of-turn wait, so a real next turn comes first.
            resume_wait_s=settings.endpointing_max_delay_s + 1.0,
        )

    async def speak(self, lines: list[str]) -> None:
        await self._notify(lines)
        handle = None
        for line in lines:
            handle = self.session.say(line)
        if self.interview.ended:
            if handle is not None:
                await handle.wait_for_playout()
            await self._on_ended()

    async def on_enter(self) -> None:
        await self.speak(await self.interview.opening())

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        text = new_message.text_content or ""
        metrics: Any = getattr(new_message, "metrics", None) or {}
        start, stop = metrics.get("started_speaking_at"), metrics.get("stopped_speaking_at")
        spoken_s = stop - start if isinstance(start, float) and isinstance(stop, float) else None
        await self.turns.on_turn(text, spoken_s)
        raise StopResponse()


async def run_session(ctx: JobContext, build_session: Any) -> bool:
    """Run a real interview if the room is a session room. Returns False for other rooms."""
    session_id = session_id_from_room(ctx.room.name)
    if session_id is None:
        return False
    maker = get_sessionmaker()
    loaded = await load_session(maker, session_id)
    if loaded is None:
        log.warning("session %s has no brief or has ended; leaving the room", session_id)
        ctx.shutdown("session not ready")
        return True

    async with maker() as db:  # the sim user's sessions use the sim budget (P13)
        gateway = await gateway_for_org(db, loaded.org_id, get_gateway())
    runner = InterviewRunner(
        SessionController(loaded.brief),
        Interviewer(gateway, loaded.brief, facts=loaded.facts),
        trace=SqlTraceSink(maker, loaded.org_id, session_id),  # admin traces (R2), background
    )
    interview = VoiceInterview(
        session_id=session_id,
        runner=runner,
        store=SqlSessionStore(maker, loaded.org_id),
        finisher=ApiFinisher(AgentApiSettings()),
        now=time.monotonic,
    )
    agent_session: AgentSession[None] = build_session()

    async def ended() -> None:
        agent.turns.close()
        await interview.finish(interrupted=False)
        payload = json.dumps({"type": "ended"}).encode()
        await ctx.room.local_participant.publish_data(payload, reliable=True, topic=SESSION_TOPIC)
        ctx.shutdown("interview ended")

    async def notify(lines: list[str]) -> None:
        try:
            await ctx.room.local_participant.publish_data(
                state_message(interview, lines), reliable=True, topic=SESSION_TOPIC
            )
        except Exception:
            log.warning("could not send the session state to the browser", exc_info=True)

    agent = InterviewAgent(interview, ended, notify)

    @agent_session.on("user_state_changed")
    def _on_user_state(event: Any) -> None:
        agent.turns.on_user_state(event.new_state)

    tasks: set[asyncio.Task[None]] = set()

    def background(coro: Any) -> None:
        # Keep a reference until the task is done, so it is not garbage-collected early.
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @ctx.room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        if packet.topic != COACH_TOPIC:
            return
        try:
            command = json.loads(packet.data.decode()).get("command")
        except ValueError:
            return
        if command == "end":
            background(ended())
        elif command in COACH_COMMANDS:
            background(_coach(command))

    async def _coach(command: Any) -> None:
        try:
            await agent.speak(await interview.coach(command))
        except CoachNotAllowedError:
            log.info("coach command %s refused: Realistic mode", command)

    @ctx.room.on("participant_disconnected")
    def _on_left(_: rtc.RemoteParticipant) -> None:
        interview.on_disconnect()
        background(_watch_reconnect())

    @ctx.room.on("participant_connected")
    def _on_back(_: rtc.RemoteParticipant) -> None:
        lines = interview.on_reconnect()
        if lines:
            background(agent.speak(lines))

    async def _watch_reconnect() -> None:
        while interview.disconnected_at is not None and not interview.ended:
            if interview.reconnect_expired():
                log.info("session %s: no reconnect within the window; ending", session_id)
                await interview.finish(interrupted=True)
                ctx.shutdown("candidate did not reconnect")
                return
            await asyncio.sleep(1)

    await agent_session.start(
        agent=agent, room=ctx.room, room_options=RoomOptions(close_on_disconnect=False)
    )
    return True
