"""LLM tracing (LT-1 to LT-6, LT-11, LT-14): spans in memory, never MLflow or the network."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
import uuid
import wave
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from strong_core.config import Settings, find_repo_root, get_settings
from strong_core.gateway import (
    Message,
    ModelGateway,
    Role,
    UsageRecord,
    build_gateway,
    load_models_config,
    set_usage_sink,
    usage_context,
)
from strong_core.gateway.client import _needed_retry
from strong_core.schemas import JobPosting, SessionTraceSettings
from strong_core.tracing import (
    SpanRecord,
    TraceRecord,
    TraceTags,
    is_active,
    set_exporter_override,
    span,
    start_gateway_call,
    trace_context,
    turn_span,
)
from strong_core.tracing.__main__ import cutoff_ms, prune
from strong_core.tracing.__main__ import main as tracing_main
from strong_core.tracing.mlflow_export import MlflowExporter
from strong_core.tracing.testing import InMemoryExporter, trace_capture

__all__ = ["trace_capture"]  # the fixture, imported for pytest

REPO = find_repo_root()
SECRET = "Candidate Jane Roe led the Kafka migration at Acme in 2023."
MESSAGES = [
    Message(role="system", content="You parse postings.", prompt_ref="extractor/job.v2"),
    Message(role="user", content=SECRET),
]
FULL = TraceTags(session_id="s-1", sim_run_id="run-1", scenario="backend", content="full")
REDACTED = TraceTags(session_id="s-2", content="redacted")


@pytest.fixture
def fake() -> ModelGateway:
    return build_gateway(Settings(model_profile="fake"))


@pytest.fixture
def records() -> Iterator[list[UsageRecord]]:
    got: list[UsageRecord] = []

    async def sink(record: UsageRecord) -> None:
        got.append(record)

    previous = set_usage_sink(sink)
    yield got
    set_usage_sink(previous)


def _wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def _dump(record: SpanRecord) -> str:
    return json.dumps(
        {"attributes": record.attributes, "inputs": record.inputs, "outputs": record.outputs},
        default=str,
    )


# --- LT-1: off by default ----------------------------------------------------------------------


def test_lt1_inactive_without_flag_uri_or_with_fake_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-1: LLM_TRACING=on, a URI and a real profile are all needed."""
    cases = [
        (
            {"LLM_TRACING": "off", "MLFLOW_TRACKING_URI": "http://x", "MODEL_PROFILE": "local"},
            False,
        ),
        ({"LLM_TRACING": "on", "MODEL_PROFILE": "local"}, False),
        ({"LLM_TRACING": "on", "MLFLOW_TRACKING_URI": "http://x", "MODEL_PROFILE": "fake"}, False),
        ({"LLM_TRACING": "on", "MLFLOW_TRACKING_URI": "http://x", "MODEL_PROFILE": "local"}, True),
    ]
    for env, expected in cases:
        for key in ("LLM_TRACING", "MLFLOW_TRACKING_URI", "MODEL_PROFILE"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        assert is_active() is expected, env
    get_settings.cache_clear()


def test_lt1_fake_profile_makes_no_span_and_never_imports_mlflow(tmp_path: Path) -> None:
    """LT-1: with MODEL_PROFILE=fake, even with tracing on, nothing is traced or imported."""
    script = (
        "import asyncio, sys\n"
        "from strong_core.config import Settings\n"
        "from strong_core.gateway import Message, Role, build_gateway\n"
        "from strong_core.tracing import TraceTags, trace_context\n"
        "import strong_core.tracing as t\n"
        "async def main():\n"
        "    gw = build_gateway(Settings(model_profile='fake'))\n"
        "    with trace_context(TraceTags(session_id='s', content='full')):\n"
        "        await gw.complete(Role.INTERVIEWER, [Message(role='user', content='hi')])\n"
        "asyncio.run(main())\n"
        "assert t._exporter is None, 'an exporter was created'\n"
        "assert not any(m == 'mlflow' or m.startswith('mlflow.') for m in sys.modules), 'mlflow'\n"
        "print('clean')\n"
    )
    env = {
        **os.environ,
        "MODEL_PROFILE": "fake",
        "LLM_TRACING": "on",
        "MLFLOW_TRACKING_URI": "http://127.0.0.1:9",
    }
    done = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert "clean" in done.stdout


# --- LT-2: one span per gateway call -------------------------------------------------------------


async def test_lt2_complete_with_output_type_makes_one_span(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-2: role, alias, tier, prompt refs, output type, retry flag, tokens, cost, duration."""
    with trace_context(FULL):
        done = await fake.complete(Role.EXTRACTOR, MESSAGES, output_type=JobPosting)
    (trace,) = trace_capture.traces
    assert trace.tags is FULL
    root = trace.root
    assert root.name == "gateway.extractor" and root.kind == "CHAT_MODEL" and root.status == "OK"
    a = root.attributes
    assert a["role"] == "extractor" and a["alias"] == done.model
    assert a["model_profile"] == "fake"
    assert a["prompt_refs"] == ["extractor/job.v2"]
    assert a["output_type"] == "JobPosting"
    assert a["structured_retry"] is False
    assert a["input_tokens"] == done.usage.input_tokens
    assert a["output_tokens"] == done.usage.output_tokens
    assert a["cost_usd"] == 0.0 and a["cost_known"] is False
    assert a["duration_ms"] >= 0
    assert root.outputs == done.output.model_dump(mode="json")


async def test_lt2_stream_records_first_token_and_text(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-2: a stream's span has ttft_ms and the whole reply."""
    with trace_context(FULL):
        chunks = [c async for c in fake.stream(Role.INTERVIEWER, MESSAGES)]
    (trace,) = trace_capture.traces
    a = trace.root.attributes
    assert a["stream"] is True and a["role"] == "interviewer"
    assert 0 <= a["ttft_ms"] <= a["duration_ms"]
    assert trace.root.outputs == "".join(chunks)


async def test_lt2_stream_stopped_early_is_marked(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-2: barge-in closes the stream; the span ends, marked stopped_early, with no usage."""
    with trace_context(FULL):
        gen = fake.stream(Role.INTERVIEWER, MESSAGES)
        await gen.__anext__()
        await gen.aclose()
    (trace,) = trace_capture.traces
    assert trace.root.attributes["stopped_early"] is True
    assert "input_tokens" not in trace.root.attributes


async def test_lt2_speech_calls_make_spans(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-2: transcribe, synthesize and synthesize_stream each make one span."""
    with trace_context(FULL):
        text = await fake.transcribe(_wav(1.5))
        wav = await fake.synthesize("Hello there.")
        pcm = b"".join([c async for c in fake.synthesize_stream("Hello there.")])
    stt, tts, tts_stream = (t.root for t in trace_capture.traces)
    assert stt.name == "gateway.stt" and stt.inputs == {
        "audio_bytes": len(_wav(1.5)),
        "audio_seconds": 1.5,
    }
    assert stt.outputs == text
    assert tts.name == "gateway.tts" and tts.outputs == {"audio_bytes": len(wav)}
    assert tts.inputs == {"text": "Hello there.", "characters": 12}
    assert tts_stream.attributes["stream"] is True
    assert tts_stream.attributes["first_chunk_ms"] >= 0
    assert tts_stream.outputs == {"audio_bytes": len(pcm)}
    for s in (stt, tts, tts_stream):
        assert "audio" not in json.dumps(s.outputs).replace("audio_bytes", "")


async def test_lt2_span_cost_equals_the_usage_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    records: list[UsageRecord],
    trace_capture: InMemoryExporter,
) -> None:
    """LT-2: the span copies the cost written to usage_events (OB-2), not a second sum."""
    (tmp_path / "litellm.local.yaml").write_text(
        "model_list:\n"
        "  - model_name: local-small\n"
        "    model_info: {input_cost_per_token: 0.001, output_cost_per_token: 0.002}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    get_settings.cache_clear()

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="Tell me about a migration.")])

    config = load_models_config(REPO / "config", "local")
    gw = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(reply))
    with usage_context(uuid.uuid4()), trace_context(FULL):
        await gw.complete(Role.INTERVIEWER, MESSAGES)
    (rec,) = records
    (trace,) = trace_capture.traces
    a = trace.root.attributes
    assert a["alias"] == "local-small" and a["tier"] == config.capabilities(Role.INTERVIEWER).tier
    assert a["cost_known"] is True
    assert Decimal(f"{a['cost_usd']:.6f}") == rec.cost_usd
    assert a["input_tokens"] == rec.input_tokens and a["output_tokens"] == rec.output_tokens


async def test_lt2_structured_output_retry_is_flagged(trace_capture: InMemoryExporter) -> None:
    """LT-2: an invalid first structured reply that Pydantic AI retries sets structured_retry."""
    valid = JobPosting.model_validate_json(
        (
            REPO / "packages/core/src/strong_core/gateway/fixtures/extractor/JobPosting.json"
        ).read_text(encoding="utf-8")
    ).model_dump(mode="json")
    calls = {"n": 0}

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        args: dict[str, Any] = {"bogus": True} if calls["n"] == 1 else valid
        if info.output_tools:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])
        return ModelResponse(parts=[TextPart(content=json.dumps(args))])

    config = load_models_config(REPO / "config", "local")
    gw = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(reply))
    with trace_context(FULL):
        await gw.complete(Role.EXTRACTOR, MESSAGES, output_type=JobPosting)
    assert calls["n"] == 2
    (trace,) = trace_capture.traces
    assert trace.root.attributes["structured_retry"] is True


def test_lt2_needed_retry_reads_retry_prompts() -> None:
    """LT-2: the retry flag comes from Pydantic AI's retry prompts."""
    assert not _needed_retry([ModelResponse(parts=[TextPart(content="ok")])])
    retry = ModelRequest(parts=[RetryPromptPart(content="invalid")])
    assert _needed_retry([ModelResponse(parts=[TextPart(content="x")]), retry])


async def test_lt2_failed_call_records_the_error(trace_capture: InMemoryExporter) -> None:
    """LT-2: a failing call ends its span with status ERROR and the exception type."""

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ConnectionError("upstream down")

    config = load_models_config(REPO / "config", "local")
    gw = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(reply))
    with trace_context(FULL), pytest.raises(ConnectionError):
        await gw.complete(Role.INTERVIEWER, MESSAGES)
    (trace,) = trace_capture.traces
    assert trace.root.status == "ERROR"
    assert trace.root.attributes["error.type"] == "ConnectionError"
    assert "upstream down" in trace.root.attributes["error.message"]


# --- LT-3: only inside a trace context -----------------------------------------------------------


async def test_lt3_no_trace_context_makes_no_span(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-3 (core half): calls and turns outside a trace context record nothing."""
    await fake.complete(Role.EXTRACTOR, MESSAGES, output_type=JobPosting)
    with turn_span("text", 1) as turn:
        turn.set(duration_ms=5)
        await fake.complete(Role.INTERVIEWER, MESSAGES)
    assert trace_capture.traces == []


async def test_lt3_context_is_scoped_to_the_block(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-3: the trace context ends with its block."""
    with trace_context(FULL):
        await fake.complete(Role.INTERVIEWER, MESSAGES)
    await fake.complete(Role.INTERVIEWER, MESSAGES)
    assert len(trace_capture.traces) == 1


# --- LT-4: redaction -----------------------------------------------------------------------------


async def test_lt4_redacted_span_holds_no_message_text(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-4: a redacted span keeps role, prompt ref, a hash and a length, never the text."""
    with trace_context(REDACTED):
        done = await fake.complete(Role.EXTRACTOR, MESSAGES, output_type=JobPosting)
        reply = "".join([c async for c in fake.stream(Role.INTERVIEWER, MESSAGES)])
        heard = await fake.transcribe(_wav(1.0))
        await fake.synthesize(SECRET)
    for trace in trace_capture.traces:
        text = _dump(trace.root)
        for secret in (SECRET, "You parse postings.", reply.strip(), heard):
            assert secret not in text, (trace.root.name, secret)
        assert done.output.title not in text
    msgs = trace_capture.traces[0].root.inputs["messages"]
    assert msgs[0]["role"] == "system" and msgs[0]["prompt_ref"] == "extractor/job.v2"
    assert set(msgs[1]) == {"role", "sha256", "len"} and msgs[1]["len"] == len(SECRET)


async def test_lt4_full_span_holds_the_text(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-4: with content="full" the messages are stored as sent."""
    with trace_context(FULL):
        await fake.complete(Role.INTERVIEWER, MESSAGES)
    assert SECRET in _dump(trace_capture.traces[0].root)


async def test_lt4_error_message_only_with_full_content(trace_capture: InMemoryExporter) -> None:
    """LT-4: an error message can quote the reply, so redacted spans keep only its type."""

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ValueError(SECRET)

    config = load_models_config(REPO / "config", "local")
    gw = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(reply))
    with trace_context(REDACTED), pytest.raises(ValueError):
        await gw.complete(Role.INTERVIEWER, MESSAGES)
    a = trace_capture.traces[0].root.attributes
    assert a["error.type"] == "ValueError" and "error.message" not in a
    assert SECRET not in _dump(trace_capture.traces[0].root)


# --- LT-5: never slows or breaks a call ----------------------------------------------------------


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_lt5_unreachable_server_never_breaks_or_slows_calls(
    fake: ModelGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-5: with MLflow down, calls succeed, nothing raises, bookkeeping p95 under 2 ms."""
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_TIMEOUT", "1")
    exporter = MlflowExporter(f"http://127.0.0.1:{_closed_port()}", "lt5-test")
    previous = set_exporter_override(exporter)
    try:
        with trace_context(FULL):
            for _ in range(20):
                await fake.complete(Role.EXTRACTOR, MESSAGES, output_type=JobPosting)
            timings = []
            for i in range(200):
                t0 = time.perf_counter()
                call = start_gateway_call(
                    "gateway.interviewer",
                    "CHAT_MODEL",
                    {
                        "role": "interviewer",
                        "inputs": {"messages": [{"role": "user", "content": SECRET}]},
                    },
                )
                call.first_token()
                call.finish(f"reply {i}", input_tokens=10, output_tokens=5)
                timings.append((time.perf_counter() - t0) * 1000)
    finally:
        set_exporter_override(previous)
        exporter.close(timeout_s=30)
    timings.sort()
    assert timings[int(len(timings) * 0.95)] < 2.0


def test_lt5_full_queue_drops_without_blocking() -> None:
    """LT-5: when the export queue is full, submit drops the trace at once."""
    exporter = MlflowExporter("http://127.0.0.1:9", "lt5-test", queue_size=1)
    exporter._thread = object()  # type: ignore[assignment]  # no thread: the queue never drains
    root = SpanRecord(name="turn", kind="CHAIN", start_ns=time.time_ns())
    t0 = time.perf_counter()
    for _ in range(100):
        exporter.submit(TraceRecord("t", FULL, root))
    assert (time.perf_counter() - t0) < 0.1
    assert exporter._queue.qsize() == 1


def test_lt5_exporter_replays_the_tree_into_mlflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """LT-5, LT-7: the exporter replays each span with its times, tags and session metadata."""
    import mlflow

    started: list[dict[str, Any]] = []
    ended: list[dict[str, Any]] = []

    class Live:
        def __init__(self, name: str) -> None:
            self.name = name

        def end(self, **kwargs: Any) -> None:
            ended.append({"name": self.name, **kwargs})

    def start(name: str, **kwargs: Any) -> Live:
        started.append({"name": name, **kwargs})
        return Live(name)

    class Experiment:
        experiment_id = "7"

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "set_experiment", lambda name: Experiment())
    monkeypatch.setattr(mlflow, "start_span_no_context", start)

    child = SpanRecord(
        name="gateway.interviewer",
        kind="CHAT_MODEL",
        start_ns=200,
        end_ns=300,
        attributes={"role": "interviewer", "obj": object()},
    )
    root = SpanRecord(name="turn", kind="CHAIN", start_ns=100, end_ns=400, children=[child])
    tags = TraceTags(session_id="s-9", sim_run_id="run-9", service="api", content="full")
    MlflowExporter("http://mlflow:5000", "sim")._send(TraceRecord("t", tags, root))

    assert [s["name"] for s in started] == ["turn", "gateway.interviewer"]
    assert started[0]["experiment_id"] == "7" and started[0]["start_time_ns"] == 100
    assert started[0]["tags"] == {
        "session_id": "s-9",
        "sim_run_id": "run-9",
        "service": "api",
        "content": "full",
    }
    assert started[0]["metadata"] == {"mlflow.trace.session": "s-9"}
    assert started[1]["parent_span"].name == "turn" and started[1]["start_time_ns"] == 200
    assert isinstance(started[1]["attributes"]["obj"], str)
    assert [(e["name"], e["end_time_ns"]) for e in ended] == [
        ("gateway.interviewer", 300),
        ("turn", 400),
    ]


# --- LT-6: turn spans ----------------------------------------------------------------------------


async def test_lt6_turn_span_parents_its_gateway_calls(
    fake: ModelGateway, trace_capture: InMemoryExporter
) -> None:
    """LT-6: one trace per turn, the gateway calls as children, timings set by the caller."""
    with trace_context(FULL):
        for i in (1, 2):
            with turn_span("voice", i) as turn:
                await fake.transcribe(_wav(0.5))
                _ = [c async for c in fake.stream(Role.INTERVIEWER, MESSAGES)]
                turn.set(e2e_ms=640.0, llm_ttft_ms=210.0, tts_ttfb_ms=None)
    assert len(trace_capture.traces) == 2
    for i, trace in enumerate(trace_capture.traces, start=1):
        root = trace.root
        assert root.name == "turn" and root.attributes["turn.kind"] == "voice"
        assert root.attributes["turn.index"] == i
        assert root.attributes["e2e_ms"] == 640.0 and "tts_ttfb_ms" not in root.attributes
        assert [c.name for c in root.children] == ["gateway.stt", "gateway.interviewer"]


async def test_lt6_nested_spans_send_one_trace(trace_capture: InMemoryExporter) -> None:
    """LT-6, LT-7: a job span holding turn spans is one trace, sent when the root ends."""
    with trace_context(FULL), span("score_session", "TASK"):
        with turn_span("text", 1):
            pass
        assert trace_capture.traces == []
    (trace,) = trace_capture.traces
    assert trace.root.name == "score_session" and [c.name for c in trace.root.children] == ["turn"]


async def test_lt6_error_in_turn_marks_the_span(trace_capture: InMemoryExporter) -> None:
    """LT-6: an exception inside a turn is recorded and still raised."""
    with trace_context(FULL), pytest.raises(KeyError), turn_span("text", 1):
        raise KeyError("x")
    assert trace_capture.traces[0].root.status == "ERROR"


# --- LT-11: prune --------------------------------------------------------------------------------


class _Deleter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def delete_traces(self, experiment_id: str, max_timestamp_millis: int | None = None) -> int:
        self.calls.append((experiment_id, max_timestamp_millis))
        return 3


def test_lt11_prune_deletes_traces_older_than_the_cutoff() -> None:
    """LT-11: dev traces older than 30 days are deleted."""
    deleter = _Deleter()
    now = 1_800_000_000.0
    assert prune(deleter, "4", 30, now_s=now) == 3
    assert deleter.calls == [("4", int((now - 30 * 86400) * 1000))]
    assert cutoff_ms(1, now_s=now) == int((now - 86400) * 1000)
    with pytest.raises(ValueError):
        prune(deleter, "4", 0)


def test_lt11_prune_without_uri_does_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """LT-11: with no MLFLOW_TRACKING_URI the command exits 0 and says so."""
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    get_settings.cache_clear()
    assert tracing_main(["prune"]) == 0
    assert "nothing to prune" in capsys.readouterr().out


# --- LT-14: session trace settings ---------------------------------------------------------------


def test_lt14_session_trace_settings_contract() -> None:
    """LT-14: redacted by default, unknown fields and bad values rejected."""
    assert SessionTraceSettings().content == "redacted"
    ok = SessionTraceSettings(
        sim_run_id="20261105-1200-text-smoke", scenario="backend-senior", content="full"
    )
    assert ok.content == "full"
    for bad in ({"content": "everything"}, {"extra": 1}, {"sim_run_id": "run id; drop"}):
        with pytest.raises(ValidationError):
            SessionTraceSettings.model_validate(bad)


def test_lt14_sessions_have_a_trace_json_column() -> None:
    """LT-14: sessions.trace_json is a nullable JSON column."""
    from strong_core.db.models import InterviewSession

    column = InterviewSession.__table__.c.trace_json
    assert column.nullable
