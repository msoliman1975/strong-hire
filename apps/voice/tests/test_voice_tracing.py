"""LLM tracing of voice interviews (LT-3, LT-6, LT-7): one trace per turn, with its timings."""

from __future__ import annotations

import io
import math
import wave
from collections.abc import Awaitable, Callable
from typing import Any

from strong_core.config import Settings
from strong_core.gateway import Message, Role, build_gateway
from strong_core.tracing import TraceTags, collect_turns, trace_context
from strong_core.tracing.testing import InMemoryExporter, trace_capture
from strong_voice.agent import trace_turns
from strong_voice.latency import LatencyRecorder, TurnLatency, turn_attributes

__all__ = ["trace_capture"]

TAGS = TraceTags(session_id="s-voice", sim_run_id="run-v", service="voice", content="full")
USER = {"end_of_turn_delay": 0.30, "transcription_delay": 0.10}
ASSISTANT = {"e2e_latency": 0.80, "llm_node_ttft": 0.25, "tts_node_ttfb": 0.15}


class FakeJobContext:
    def __init__(self) -> None:
        self.on_shutdown: list[Callable[[], Awaitable[None]]] = []

    def add_shutdown_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        self.on_shutdown.append(callback)


def _wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def test_lt6_turn_attributes_are_the_latency_row() -> None:
    """LT-6: the trace carries OB-3's timings; a step LiveKit did not report is left out."""
    row = TurnLatency(
        timestamp=0.0,
        session="room",
        profile="fake",
        turn=3,
        total_ms=800.0,
        turn_detection_ms=200.0,
        stt_ms=100.0,
        llm_ttft_ms=250.0,
        tts_ttfb_ms=math.nan,
        other_ms=250.0,
        interrupted=False,
    )
    assert turn_attributes(row) == {
        "e2e_ms": 800.0,
        "turn_detection_ms": 200.0,
        "stt_ms": 100.0,
        "llm_ttft_ms": 250.0,
        "other_ms": 250.0,
        "interrupted": False,
    }


def test_lt6_a_failing_trace_hook_never_breaks_the_recorder() -> None:
    """LT-5: an error while tracing a turn is logged, and the row is still kept."""
    recorder = LatencyRecorder(None, session="room", profile="fake")

    def broken(row: TurnLatency) -> None:
        raise RuntimeError("tracing down")

    recorder.trace_turn = broken
    recorder.on_message("user", USER)
    recorder.on_message("assistant", ASSISTANT)
    assert len(recorder.turns) == 1


async def test_lt6_each_voice_turn_is_one_trace_with_its_calls_and_timings(
    trace_capture: InMemoryExporter,
) -> None:
    """LT-6, LT-7: STT, interviewer and TTS of a turn are the children of its `turn` trace."""
    gateway = build_gateway(Settings(model_profile="fake"))
    ctx = FakeJobContext()
    recorder = LatencyRecorder(None, session="session-x", profile="fake")
    with trace_context(TAGS), collect_turns(flush_on_exit=False) as collector:
        assert collector is not None
        trace_turns(ctx, recorder, collector)  # type: ignore[arg-type]
        await gateway.synthesize("Hello, thanks for joining.")  # the greeting: no user turn yet
        for answer in ("First answer.", "Second answer."):
            await gateway.transcribe(_wav(1.0))
            reply = [
                c
                async for c in gateway.stream(
                    Role.INTERVIEWER, [Message(role="user", content=answer)]
                )
            ]
            assert reply
            await gateway.synthesize("".join(reply))
            recorder.on_message("user", USER)
            recorder.on_message("assistant", ASSISTANT)
    assert len(trace_capture.traces) == 2  # the greeting waits for the end of the session
    for index, trace in enumerate(trace_capture.traces, start=1):
        root = trace.root
        assert root.name == "turn" and root.attributes["turn.kind"] == "voice"
        assert root.attributes["turn.index"] == index
        assert root.attributes["e2e_ms"] == 800.0 and root.attributes["llm_ttft_ms"] == 250.0
        assert root.attributes["tts_ttfb_ms"] == 150.0 and root.attributes["interrupted"] is False
        assert trace.tags is TAGS
    first, second = trace_capture.traces
    assert [c.name for c in first.root.children] == [
        "gateway.tts",  # the greeting finished before the first cut, so it joins turn 1
        "gateway.stt",
        "gateway.interviewer",
        "gateway.tts",
    ]
    assert [c.name for c in second.root.children] == [
        "gateway.stt",
        "gateway.interviewer",
        "gateway.tts",
    ]
    (shutdown,) = ctx.on_shutdown
    await shutdown()  # nothing left: no extra trace
    assert len(trace_capture.traces) == 2


async def test_lt6_what_is_left_is_sent_when_the_session_ends(
    trace_capture: InMemoryExporter,
) -> None:
    """LT-6: calls after the last measured turn are sent by the shutdown callback."""
    gateway = build_gateway(Settings(model_profile="fake"))
    ctx = FakeJobContext()
    recorder = LatencyRecorder(None, session="session-x", profile="fake")
    with trace_context(TAGS), collect_turns(flush_on_exit=False) as collector:
        assert collector is not None
        trace_turns(ctx, recorder, collector)  # type: ignore[arg-type]
        await gateway.synthesize("Thanks, that is all for today.")
    assert trace_capture.traces == []
    for callback in ctx.on_shutdown:
        await callback()
    (rest,) = trace_capture.traces
    assert rest.root.attributes["turn.rest"] is True
    assert [c.name for c in rest.root.children] == ["gateway.tts"]


async def test_lt3_an_untraced_session_gets_no_turn_hook(trace_capture: InMemoryExporter) -> None:
    """LT-3: without a trace context (a real user, or tracing off) there is no collector, so
    the agent never sets the hook and nothing is recorded."""
    gateway = build_gateway(Settings(model_profile="fake"))
    with collect_turns(flush_on_exit=False) as collector:
        assert collector is None
        await gateway.transcribe(_wav(0.5))
    assert trace_capture.traces == []


# --- LT-21, LT-24: voice turn content (phase 2) ---------------------------------------------------


def _turn(speaker: str, text: str, at: int) -> Any:
    from strong_core.schemas import Phase, Speaker, Turn

    return Turn(speaker=Speaker(speaker), phase=Phase.CORE, text=text, start_ms=at, end_ms=at + 1)


PROD = TraceTags(
    session_id="s-prod",
    org_id="00000000-0000-4000-8000-0000000000b1",
    service="voice",
    content="metadata",
    turn_content=True,
)


def _content_rig(
    monkeypatch: Any, *, allowed: bool, tags: TraceTags = PROD
) -> tuple[LatencyRecorder, FakeJobContext, list[Any]]:
    import strong_voice.agent as agent_module
    from strong_core.tracing.scrub import Scrubber

    async def consent(org_id: Any, db: Any = None) -> bool:
        return allowed

    async def scrubber(db: Any, org_id: Any) -> Scrubber:
        return Scrubber(names=["Jane Roe"], companies=["Acme"])

    class Session:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(agent_module, "turn_content_allowed", consent)
    monkeypatch.setattr(agent_module.Scrubber, "for_org", staticmethod(scrubber))
    monkeypatch.setattr(agent_module, "get_sessionmaker", lambda: Session)
    transcript: list[Any] = []
    recorder = LatencyRecorder(None, session="session-x", profile="fake")
    recorder.turns_source = lambda: transcript
    return recorder, FakeJobContext(), transcript


async def test_lt21_a_consenting_users_voice_turn_keeps_scrubbed_text(
    trace_capture: InMemoryExporter, monkeypatch: Any
) -> None:
    """LT-21: the turn's transcript and reply, scrubbed, in a turn.content trace with the turn's
    index; the metadata turn trace holds no text; audio is never kept."""
    recorder, ctx, transcript = _content_rig(monkeypatch, allowed=True)
    with trace_context(PROD), collect_turns(flush_on_exit=False) as collector:
        assert collector is not None
        trace_turns(ctx, recorder, collector)  # type: ignore[arg-type]
        transcript += [
            _turn("candidate", "I'm Jane Roe; at Acme I cut latency in half.", 0),
            _turn("interviewer", "How did you measure that, Jane?", 10),
        ]
        recorder.on_message("user", USER)
        recorder.on_message("assistant", ASSISTANT)
        for callback in ctx.on_shutdown:
            await callback()  # drains the content task
    content = [t for t in trace_capture.traces if t.root.name == "turn.content"]
    (kept,) = content
    assert kept.root.attributes["turn.index"] == 1 and kept.root.attributes["turn.kind"] == "voice"
    assert kept.root.inputs == {"candidate": "I'm [name]; at [company] I cut latency in half."}
    assert kept.root.outputs == {"interviewer": "How did you measure that, [name]?"}
    assert kept.tags.as_tags()["content"] == "turns"
    turns = [t for t in trace_capture.traces if t.root.name == "turn"]
    assert "latency in half" not in str([[s.inputs, s.outputs] for t in turns for s in t.spans()])


async def test_lt24_withdrawn_consent_keeps_no_voice_text(
    trace_capture: InMemoryExporter, monkeypatch: Any
) -> None:
    """LT-24: consent read at each turn; off means no content, even mid-session."""
    recorder, ctx, transcript = _content_rig(monkeypatch, allowed=False)
    with trace_context(PROD), collect_turns(flush_on_exit=False) as collector:
        assert collector is not None
        trace_turns(ctx, recorder, collector)  # type: ignore[arg-type]
        transcript.append(_turn("candidate", "An answer.", 0))
        recorder.on_message("user", USER)
        recorder.on_message("assistant", ASSISTANT)
        for callback in ctx.on_shutdown:
            await callback()
    assert [t.root.name for t in trace_capture.traces] == ["turn"]


async def test_lt21_no_voice_text_without_turn_content(
    trace_capture: InMemoryExporter, monkeypatch: Any
) -> None:
    """LT-21: a session whose tags do not allow content (no consent, or a sim session) keeps
    none, and consent is not even read."""
    no_content = TraceTags(session_id="s", org_id=PROD.org_id, content="metadata")
    recorder, ctx, transcript = _content_rig(monkeypatch, allowed=True, tags=no_content)
    with trace_context(no_content), collect_turns(flush_on_exit=False) as collector:
        assert collector is not None
        trace_turns(ctx, recorder, collector)  # type: ignore[arg-type]
        transcript.append(_turn("candidate", "An answer.", 0))
        recorder.on_message("user", USER)
        recorder.on_message("assistant", ASSISTANT)
        for callback in ctx.on_shutdown:
            await callback()
    assert [t.root.name for t in trace_capture.traces] == ["turn"]
