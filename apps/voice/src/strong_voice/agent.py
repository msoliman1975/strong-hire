"""Voice spike: a LiveKit Agents worker that runs a hard-coded two-question interview.

Pipeline per turn: Silero VAD and the LiveKit turn detector find the end of the candidate's
turn, the final speech segment goes to the stt role, the interviewer role streams its reply,
and each sentence goes to the tts role as soon as it is complete. Barge-in is on: the
candidate's speech stops the agent's audio. The real interviewer logic arrives in P7.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack

from livekit.agents import Agent, AgentSession, JobContext, JobProcess, llm
from livekit.agents.voice.events import ConversationItemAddedEvent
from livekit.plugins import silero
from livekit.plugins.turn_detector.english import EnglishModel

from strong_core.db import get_sessionmaker
from strong_core.gateway import Role, get_gateway, make_db_usage_sink, set_usage_sink, usage_context
from strong_core.ops.logs import log_context
from strong_core.prompts import load_prompt
from strong_voice.interview_agent import run_session
from strong_voice.latency import WARMUP_ROOM_PREFIX, LatencyRecorder
from strong_voice.plugins import GatewayLLM, GatewaySTT, GatewayTTS
from strong_voice.session_store import session_id_from_room, session_org
from strong_voice.settings import get_voice_settings

log = logging.getLogger("strong_voice")


class SpikeInterviewer(Agent):
    def __init__(self) -> None:
        prompt = load_prompt(Role.INTERVIEWER, "spike")
        super().__init__(instructions=prompt.render())
        self.prompt_ref = prompt.ref

    async def on_enter(self) -> None:
        self.session.generate_reply()


def prewarm(proc: JobProcess) -> None:
    """Runs once per worker process, before any job: load the VAD model."""
    settings = get_voice_settings()
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=settings.vad_min_silence_s)


def build_session(proc: JobProcess, recorder: LatencyRecorder) -> AgentSession[None]:
    settings = get_voice_settings()
    gateway = get_gateway()
    return AgentSession(
        stt=GatewaySTT(gateway, on_recognized=recorder.on_stt),
        llm=GatewayLLM(gateway, Role.INTERVIEWER),
        tts=GatewayTTS(gateway),
        vad=proc.userdata["vad"],
        turn_handling={
            "turn_detection": EnglishModel(),
            "endpointing": {
                "mode": settings.endpointing_mode,
                "min_delay": settings.endpointing_min_delay_s,
                "max_delay": settings.endpointing_max_delay_s,
            },
            "interruption": {
                "enabled": True,
                "mode": "vad",
                "min_duration": settings.interruption_min_duration_s,
                "resume_false_interruption": True,
                "false_interruption_timeout": settings.false_interruption_timeout_s,
            },
            "preemptive_generation": {"enabled": False},
        },
    )


async def entrypoint(ctx: JobContext) -> None:
    room_name = ctx.job.room.name
    session_id = session_id_from_room(room_name)
    if session_id is None:
        await spike_entrypoint(ctx)
        return
    # A room named session-<uuid> is a real interview (P7). Every gateway call it makes (the
    # interviewer, stt, tts) writes a usage_events row for its org and session (OB-2): the
    # usage context is set before the room connects, so every task the session starts has it.
    maker = get_sessionmaker()
    set_usage_sink(make_db_usage_sink(maker))
    org_id = await session_org(maker, session_id)
    with ExitStack() as stack:
        stack.enter_context(log_context(session_id=session_id))
        if org_id is not None:
            stack.enter_context(usage_context(org_id, session_id=session_id))
        await ctx.connect()
        gateway = get_gateway()
        recorder = LatencyRecorder(None, session=room_name, profile=gateway.profile)
        await run_session(ctx, lambda: build_session(ctx.proc, recorder), recorder=recorder)


async def spike_entrypoint(ctx: JobContext) -> None:
    """Latency spike rooms: the hard-coded interview, timings to a CSV."""
    settings = get_voice_settings()
    gateway = get_gateway()
    await ctx.connect()

    label = settings.latency_label or gateway.profile
    warmup = ctx.room.name.startswith(WARMUP_ROOM_PREFIX)  # warm-up rooms are not counted
    path = None if warmup else settings.latency_dir / f"{label}.csv"
    recorder = LatencyRecorder(path, session=ctx.room.name, profile=gateway.profile)
    session = build_session(ctx.proc, recorder)

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if isinstance(item, llm.ChatMessage):
            log.info("%s: %s", item.role, (item.text_content or "")[:120])
            log.info("%s metrics: %s", item.role, sorted(item.metrics))
            before = len(recorder.turns)
            recorder.on_message(item.role, item.metrics, item.interrupted)
            if len(recorder.turns) > before:
                t = recorder.turns[-1]
                log.info(
                    "turn %d latency total=%.0f ms (turn=%.0f stt=%.0f llm=%.0f tts=%.0f)",
                    t.turn,
                    t.total_ms,
                    t.turn_detection_ms,
                    t.stt_ms,
                    t.llm_ttft_ms,
                    t.tts_ttfb_ms,
                )

    async def _report() -> None:
        if recorder.turns:
            log.info("latency for room %s\n%s", ctx.room.name, recorder.summary())

    ctx.add_shutdown_callback(_report)
    await session.start(agent=SpikeInterviewer(), room=ctx.room)
