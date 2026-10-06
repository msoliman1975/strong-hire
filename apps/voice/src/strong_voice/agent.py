"""Voice spike: a LiveKit Agents worker that runs a hard-coded two-question interview.

Pipeline per turn: Silero VAD and the LiveKit turn detector find the end of the candidate's
turn, the final speech segment goes to the stt role, the interviewer role streams its reply,
and each sentence goes to the tts role as soon as it is complete. Barge-in is on: the
candidate's speech stops the agent's audio. The real interviewer logic arrives in P7.
"""

from __future__ import annotations

import logging

from livekit.agents import Agent, AgentSession, JobContext, JobProcess, llm
from livekit.agents.voice.events import ConversationItemAddedEvent
from livekit.plugins import silero
from livekit.plugins.turn_detector.english import EnglishModel

from strong_core.gateway import Role, get_gateway
from strong_core.prompts import load_prompt
from strong_voice.latency import WARMUP_ROOM_PREFIX, LatencyRecorder
from strong_voice.plugins import GatewayLLM, GatewaySTT, GatewayTTS
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
                "min_delay": settings.endpointing_min_delay_s,
                "max_delay": settings.endpointing_max_delay_s,
            },
            "interruption": {
                "enabled": True,
                "mode": "vad",
                "min_duration": settings.interruption_min_duration_s,
            },
            "preemptive_generation": {"enabled": False},
        },
    )


async def entrypoint(ctx: JobContext) -> None:
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
