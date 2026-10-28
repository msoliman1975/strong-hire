"""LiveKit glue for a voice coach session (CO-6).

A room named "coach-<uuid>" is a coach session. It runs on the interview's voice loop: the same
STT, TTS, turn detection, barge-in and turn taking (strong_voice.turns.CandidateTurns), and the
same reconnect window. The coach's words come from the API's coach turn logic (VoiceCoach), not
from LiveKit's LLM reply (StopResponse) and not from the interviewer.

From the browser, on the data channel (topic "coach"):
  {"command": "end"}           the candidate ended the session
  {"command": "take_start"}    start recording a take: the coach stays quiet
  {"command": "take_end"}      stop it; the take goes to the browser for scoring
  {"command": "take_cancel"}   drop it
To the browser (topic "session"):
  {"type": "coach_turn", "said": [lines], "result": CoachTurnResult | null}
                                              after each coach line; `result` after an API turn
  {"type": "take", "recording": bool}         when a take starts or stops
  {"type": "take_done", "text", "duration_s"} the take's transcript, for POST /stories/{id}/takes
  {"type": "ended"}                           when the session is over
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, StopResponse, llm
from livekit.agents.voice.room_io import RoomOptions

from strong_core.db import get_sessionmaker
from strong_core.gateway import get_gateway, make_db_usage_sink, set_usage_sink, usage_context
from strong_core.ops.logs import log_context
from strong_voice.coach import VoiceCoach, VoiceTake
from strong_voice.coach_store import ApiCoach, coach_session_id_from_room, load_coach_session
from strong_voice.interview_agent import COACH_TOPIC, SESSION_TOPIC, interviewer_attributes
from strong_voice.plugins import GatewaySTT
from strong_voice.radar import (
    attach_radar,
    gateway_complete,
    get_radar_settings,
    load_radar_stories,
)
from strong_voice.session_store import AgentApiSettings
from strong_voice.settings import get_voice_settings
from strong_voice.turns import CandidateTurns

log = logging.getLogger("strong_voice.coach")


def turn_message(lines: list[str], result: dict[str, Any] | None) -> bytes:
    return json.dumps({"type": "coach_turn", "said": lines, "result": result}).encode()


def take_message(take: VoiceTake) -> bytes:
    return json.dumps(
        {"type": "take_done", "text": take.text, "duration_s": take.duration_s}
    ).encode()


class CoachAgent(Agent):
    def __init__(self, coach: VoiceCoach, on_ended: Any, notify: Any) -> None:
        super().__init__(instructions="Unused: the API's coach decides what is said.")
        self.coach = coach
        self._on_ended = on_ended
        self._notify = notify
        settings = get_voice_settings()
        self.turns = CandidateTurns(
            coach,
            self.speak,
            thinking_wait_s=settings.thinking_wait_s,
            resume_wait_s=settings.endpointing_max_delay_s + 1.0,
        )

    async def speak(self, lines: list[str]) -> None:
        result, self.coach.last_result = self.coach.last_result, None
        if lines or result is not None:
            await self._notify(turn_message(lines, result))
        handle = None
        for line in lines:
            handle = self.session.say(line)
        if self.coach.ended:
            if handle is not None:
                await handle.wait_for_playout()
            await self._on_ended()

    async def on_enter(self) -> None:
        if isinstance(self.session.stt, GatewaySTT):  # replies wait for a late transcript
            self.turns.stt = self.session.stt
        await self.speak(await self.coach.opening())

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        text = new_message.text_content or ""
        metrics: Any = getattr(new_message, "metrics", None) or {}
        start, stop = metrics.get("started_speaking_at"), metrics.get("stopped_speaking_at")
        spoken_s = stop - start if isinstance(start, float) and isinstance(stop, float) else None
        await self.turns.on_turn(text, spoken_s)
        raise StopResponse()


async def coach_entrypoint(ctx: JobContext, build_session: Any) -> bool:
    """Run a voice coach session if the room is a coach room. Returns False for other rooms."""
    session_id = coach_session_id_from_room(ctx.job.room.name)
    if session_id is None:
        return False
    maker = get_sessionmaker()
    loaded = await load_coach_session(maker, session_id)
    if loaded is None:
        log.warning("coach session %s is not an active voice session; leaving", session_id)
        ctx.shutdown("coach session not ready")
        return True
    # STT and TTS calls write usage_events rows for the org (OB-2); the coach role's own calls
    # are made, and counted, by the API.
    set_usage_sink(make_db_usage_sink(maker))
    with log_context(session_id=session_id), usage_context(loaded.org_id):
        await ctx.connect()
        await run_coach(ctx, session_id, loaded.opener, build_session)
    return True


async def run_coach(
    ctx: JobContext, session_id: uuid.UUID, opener: str | None, build_session: Any
) -> None:
    coach = VoiceCoach(
        session_id=session_id,
        api=ApiCoach(AgentApiSettings()),
        now=time.monotonic,
        opener=opener,
    )
    agent_session: AgentSession[None] = build_session()

    async def publish(payload: bytes) -> None:
        try:
            await ctx.room.local_participant.publish_data(
                payload, reliable=True, topic=SESSION_TOPIC
            )
        except Exception:
            log.warning("could not send a coach message to the browser", exc_info=True)

    async def ended() -> None:
        agent.turns.close()
        await coach.finish()
        await publish(json.dumps({"type": "ended"}).encode())
        ctx.shutdown("coach session ended")

    agent = CoachAgent(coach, ended, publish)

    # SR-1 spike: the story radar reads the captions in its own task, off the turn path.
    if get_radar_settings().enabled:
        stories = await load_radar_stories(get_sessionmaker(), session_id)
        radar = attach_radar(agent_session, stories, gateway_complete(get_gateway()), publish)
        ctx.add_shutdown_callback(radar.close)

    @agent_session.on("user_state_changed")
    def _on_user_state(event: Any) -> None:
        agent.turns.on_user_state(event.new_state)

    tasks: set[asyncio.Task[None]] = set()

    def background(coro: Any) -> None:
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def _recording(lines: list[str]) -> None:
        await publish(json.dumps({"type": "take", "recording": coach.recording}).encode())
        await agent.speak(lines)

    async def _take_end() -> None:
        take, lines = coach.end_take()
        if take is not None:
            await publish(take_message(take))
        await _recording(lines)

    @ctx.room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        if packet.topic != COACH_TOPIC:
            return
        try:
            command = json.loads(packet.data.decode()).get("command")
        except (ValueError, AttributeError):
            return
        if command == "end":
            background(ended())
        elif command == "take_start":
            background(_recording(coach.start_take()))
        elif command == "take_end":
            background(_take_end())
        elif command == "take_cancel":
            background(_recording(coach.cancel_take()))

    @ctx.room.on("participant_disconnected")
    def _on_left(_: rtc.RemoteParticipant) -> None:
        coach.on_disconnect()
        background(_watch_reconnect())

    @ctx.room.on("participant_connected")
    def _on_back(_: rtc.RemoteParticipant) -> None:
        lines = coach.on_reconnect()
        if lines:
            background(agent.speak(lines))

    async def _watch_reconnect() -> None:
        while coach.disconnected_at is not None and not coach.ended:
            if coach.reconnect_expired():
                log.info("coach session %s: no reconnect within the window; ending", session_id)
                agent.turns.close()
                await coach.finish()
                ctx.shutdown("candidate did not reconnect")
                return
            await asyncio.sleep(1)

    try:
        await ctx.room.local_participant.set_attributes(interviewer_attributes())
    except Exception:
        log.warning("could not send the coach voice to the browser", exc_info=True)

    await agent_session.start(
        agent=agent, room=ctx.room, room_options=RoomOptions(close_on_disconnect=False)
    )
