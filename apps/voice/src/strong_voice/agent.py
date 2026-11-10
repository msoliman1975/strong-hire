"""Voice spike: a LiveKit Agents worker that runs a hard-coded two-question interview.

Pipeline per turn: Silero VAD and the LiveKit turn detector find the end of the candidate's
turn, the final speech segment goes to the stt role, the interviewer role streams its reply,
and each sentence goes to the tts role as soon as it is complete. Barge-in is on: the
candidate's speech stops the agent's audio. The real interviewer logic arrives in P7.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import ExitStack

from livekit.agents import Agent, AgentSession, JobContext, JobProcess, llm
from livekit.agents.voice.events import ConversationItemAddedEvent
from livekit.plugins import silero
from livekit.plugins.turn_detector.english import EnglishModel

from strong_core.db import get_sessionmaker
from strong_core.gateway import Role, get_gateway, make_db_usage_sink, set_usage_sink, usage_context
from strong_core.ops.logs import log_context
from strong_core.prompts import load_prompt
from strong_core.schemas import Speaker
from strong_core.tracing import TraceTags, TurnCollector, collect_turns, record_turn_content
from strong_core.tracing.scrub import Scrubber
from strong_core.tracing.sessions import maybe_trace, trace_tags_for, turn_content_allowed
from strong_voice.coach_agent import coach_entrypoint
from strong_voice.interview_agent import run_session
from strong_voice.latency import WARMUP_ROOM_PREFIX, LatencyRecorder, TurnLatency, turn_attributes
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

    # A room named coach-<uuid> is a voice coach session (CO-6) on the same voice loop. Its LLM
    # is never called (the API's coach decides what is said), so the session is built as is.
    def coach_session() -> AgentSession[None]:
        recorder = LatencyRecorder(None, session=room_name, profile=get_gateway().profile)
        return build_session(ctx.proc, recorder)

    if await coach_entrypoint(ctx, coach_session):
        return
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
    # LT-3, LT-6: a sim user's interview is traced, one trace per turn. Like the usage context,
    # the trace context and the turn collector are set before the room connects, so every task
    # the session starts has them. None for everyone else, and when tracing is off.
    tags = None
    if org_id is not None:
        tags = await trace_tags_for(org_id=org_id, session_id=session_id, service="voice")
    with ExitStack() as stack:
        stack.enter_context(log_context(session_id=session_id))
        if org_id is not None:
            stack.enter_context(usage_context(org_id, session_id=session_id))
        stack.enter_context(maybe_trace(tags))
        collector = stack.enter_context(collect_turns(flush_on_exit=False))
        await ctx.connect()
        gateway = get_gateway()
        recorder = LatencyRecorder(None, session=room_name, profile=gateway.profile)
        if collector is not None:
            trace_turns(ctx, recorder, collector)
        await run_session(ctx, lambda: build_session(ctx.proc, recorder), recorder=recorder)


def trace_turns(ctx: JobContext, recorder: LatencyRecorder, collector: TurnCollector) -> None:
    """Send each turn of the interview as a `turn` trace with its timings (LT-6), and what is
    left when the session ends. For a real user who gave tracing consent, also the turn's text,
    scrubbed, as a `turn.content` trace (LT-21), off the audio path."""
    content = _TurnContent(collector.tags, recorder)

    def cut(row: TurnLatency) -> None:
        collector.cut("voice", row.turn, turn_attributes(row))
        content.after_cut(row.turn)

    async def flush() -> None:
        collector.flush()
        await content.drain()

    recorder.trace_turn = cut
    ctx.add_shutdown_callback(flush)


class _TurnContent:
    """The text of each voice turn since the last cut, for consenting users only (LT-21)."""

    def __init__(self, tags: TraceTags, recorder: LatencyRecorder) -> None:
        self.tags = tags
        self.recorder = recorder
        self.seen = 0
        self.scrubber: Scrubber | None = None
        self.tasks: set[asyncio.Task[None]] = set()

    def after_cut(self, index: int) -> None:
        source = self.recorder.turns_source
        if not self.tags.turn_content or not self.tags.org_id or source is None:
            return
        try:
            turns = list(source())
            new, self.seen = turns[self.seen :], len(turns)
            candidate = " ".join(t.text for t in new if t.speaker == Speaker.CANDIDATE)
            interviewer = " ".join(t.text for t in new if t.speaker == Speaker.INTERVIEWER)
            if not (candidate or interviewer):
                return
            task = asyncio.get_running_loop().create_task(
                self._record(index, interviewer, candidate)
            )
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except Exception:
            log.warning("could not keep the content of voice turn %d", index)

    async def _record(self, index: int, interviewer: str, candidate: str) -> None:
        """Consent is read again for each turn, so turning it off stops content from the next
        turn (LT-24). Never raises (LT-31)."""
        try:
            org_id = uuid.UUID(str(self.tags.org_id))
            if not await turn_content_allowed(org_id):
                return
            if self.scrubber is None:
                async with get_sessionmaker()() as db:
                    self.scrubber = await Scrubber.for_org(db, org_id)
            record_turn_content(
                self.tags, index, "voice", interviewer, candidate, self.scrubber.scrub
            )
        except Exception:
            log.warning("could not keep the content of voice turn %d", index)

    async def drain(self) -> None:
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


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
