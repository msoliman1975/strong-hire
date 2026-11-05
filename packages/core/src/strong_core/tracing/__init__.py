"""LLM tracing to MLflow (LT-1 to LT-7, docs/llm-tracing/spec.md).

Spans are recorded in plain Python while the code runs. When a trace's root span ends, the
finished tree goes to an exporter. The MLflow exporter replays it on a background thread, so the
call path never waits on the network and never sees a tracing error (D-10, LT-5).

Code that knows whose work a call is sets a trace context; gateway calls inside it are traced:

    with trace_context(TraceTags(session_id=str(sid), sim_run_id=run, content="full")):
        with turn_span("text", index=3):
            done = await gateway.complete(Role.INTERVIEWER, messages)

Without a trace context nothing is recorded (LT-3). Tracing is active only with LLM_TRACING=on,
an MLFLOW_TRACKING_URI and a MODEL_PROFILE other than fake (LT-1); tests install an in-memory
exporter instead (strong_core.tracing.testing).

MLflow is imported here and in strong_sim only (LT-15), and only when the exporter starts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol

from strong_core.schemas.tracing import TraceContent

if TYPE_CHECKING:
    from strong_core.gateway.types import Message

log = logging.getLogger(__name__)

SpanKind = Literal["CHAT_MODEL", "LLM", "CHAIN", "TASK", "AGENT", "UNKNOWN"]
SpanStatus = Literal["OK", "ERROR"]
ERROR_MESSAGE_CHARS = 300


# --- context ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceTags:
    """What a trace belongs to. Every value becomes an MLflow trace tag (LT-7)."""

    session_id: str | None = None
    sim_run_id: str | None = None
    scenario: str | None = None
    content: TraceContent = "redacted"
    service: str | None = None
    release: str | None = None
    model_profile: str | None = None
    experiment: str | None = None
    """MLflow experiment name; None means MLFLOW_EXPERIMENT."""

    def as_tags(self) -> dict[str, str]:
        out = {
            "session_id": self.session_id,
            "sim_run_id": self.sim_run_id,
            "scenario": self.scenario,
            "content": self.content,
            "service": self.service,
            "release": self.release,
            "model_profile": self.model_profile,
        }
        return {k: v for k, v in out.items() if v}


_tags: ContextVar[TraceTags | None] = ContextVar("strong_trace_tags", default=None)
_current: ContextVar[SpanRecord | None] = ContextVar("strong_trace_span", default=None)


@contextmanager
def trace_context(tags: TraceTags) -> Iterator[TraceTags]:
    """Trace gateway calls made inside this block, tagged with `tags`."""
    token = _tags.set(tags)
    try:
        yield tags
    finally:
        _tags.reset(token)


def current_trace_tags() -> TraceTags | None:
    return _tags.get()


# --- records ---------------------------------------------------------------------------------


@dataclass
class SpanRecord:
    """One finished or running span. Times are wall-clock nanoseconds."""

    name: str
    kind: SpanKind
    start_ns: int
    attributes: dict[str, Any] = field(default_factory=dict)
    inputs: Any = None
    outputs: Any = None
    end_ns: int | None = None
    status: SpanStatus = "OK"
    children: list[SpanRecord] = field(default_factory=list)
    _mono_start: float = field(default=0.0, repr=False)

    def walk(self) -> Iterator[SpanRecord]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class TraceRecord:
    """A finished trace: its tags and its root span."""

    trace_id: str
    tags: TraceTags
    root: SpanRecord

    def spans(self) -> list[SpanRecord]:
        return list(self.root.walk())


class Exporter(Protocol):
    def submit(self, trace: TraceRecord) -> None:
        """Take a finished trace. Must return at once and never raise."""


# --- activation (LT-1) ----------------------------------------------------------------------

_exporter: Exporter | None = None
_override: Exporter | None = None


def set_exporter_override(exporter: Exporter | None) -> Exporter | None:
    """Tests: send traces to `exporter` whatever the settings say. Returns the previous one."""
    global _override
    previous, _override = _override, exporter
    return previous


def _active_exporter() -> Exporter | None:
    if _override is not None:
        return _override
    if not is_active():
        return None
    global _exporter
    if _exporter is None:
        from strong_core.tracing.mlflow_export import MlflowExporter

        _exporter = MlflowExporter()
    return _exporter


def flush(timeout_s: float = 10.0) -> bool:
    """Wait until finished traces have been sent (or dropped). True when nothing is left.

    For a process about to read its own traces back, like the sim at the end of a run (LT-9).
    Never raises.
    """
    exporter = _override or _exporter
    wait = getattr(exporter, "flush", None)
    if wait is None:
        return True
    try:
        return bool(wait(timeout_s))
    except Exception:
        warn_once("tracing: flush failed")
        return False


def is_active() -> bool:
    """LLM_TRACING=on, a tracking URI, and not the fake profile (LT-1). Tests may override."""
    if _override is not None:
        return True
    try:
        from strong_core.config import ModelProfile, get_settings

        s = get_settings()
        return bool(
            s.llm_tracing and s.mlflow_tracking_uri and s.model_profile != ModelProfile.FAKE
        )
    except Exception:
        return False


def _recording() -> TraceTags | None:
    """The tags to record under, or None when nothing should be recorded."""
    tags = _tags.get()
    if tags is None:
        return None
    return tags if is_active() else None


# --- spans -----------------------------------------------------------------------------------


def _new_span(name: str, kind: SpanKind, attributes: dict[str, Any] | None) -> SpanRecord:
    return SpanRecord(
        name=name,
        kind=kind,
        start_ns=time.time_ns(),
        attributes=dict(attributes or {}),
        _mono_start=time.perf_counter(),
    )


def _close(span: SpanRecord) -> None:
    span.end_ns = time.time_ns()
    span.attributes.setdefault(
        "duration_ms", round((time.perf_counter() - span._mono_start) * 1000, 1)
    )


def _emit(tags: TraceTags, root: SpanRecord) -> None:
    exporter = _active_exporter()
    if exporter is None:
        return
    try:
        exporter.submit(TraceRecord(uuid.uuid4().hex, tags, root))
    except Exception:
        warn_once("trace exporter rejected a trace")


class SpanHandle:
    """A running span that callers can annotate. A no-op when nothing is recorded."""

    def __init__(self, record: SpanRecord | None) -> None:
        self.record = record

    def set(self, **attributes: Any) -> None:
        if self.record is None:
            return
        self.record.attributes.update({k: v for k, v in attributes.items() if v is not None})


@contextmanager
def span(
    name: str, kind: SpanKind = "CHAIN", attributes: dict[str, Any] | None = None
) -> Iterator[SpanHandle]:
    """A parent span: gateway calls and spans opened inside it become its children.

    The first span opened in a trace context is the trace's root; the trace is sent when it ends.
    """
    tags = _recording()
    if tags is None:
        yield SpanHandle(None)
        return
    record = _new_span(name, kind, attributes)
    parent = _current.get()
    if parent is not None:
        parent.children.append(record)
    token = _current.set(record)
    try:
        yield SpanHandle(record)
    except BaseException as exc:
        record.status = "ERROR"
        record.attributes.update(_error_attributes(exc, tags))
        raise
    finally:
        _current.reset(token)
        _close(record)
        if parent is None:
            _emit(tags, record)


@contextmanager
def turn_span(kind: Literal["voice", "text"], index: int) -> Iterator[SpanHandle]:
    """One interviewer turn (LT-6). The caller sets the turn's timings on the handle."""
    with span("turn", "CHAIN", {"turn.kind": kind, "turn.index": index}) as handle:
        yield handle


class GatewayCall:
    """The span of one gateway call (LT-2). Never becomes the current span, so it is safe to
    hold across the yields of a streaming call. Every method swallows its own errors."""

    def __init__(
        self,
        tags: TraceTags,
        record: SpanRecord,
        parent: SpanRecord | None,
    ) -> None:
        self._tags = tags
        self._record = record
        self._parent = parent
        self._done = False

    @property
    def content(self) -> TraceContent:
        return self._tags.content

    def first_token(self, attribute: str = "ttft_ms") -> None:
        try:
            if attribute not in self._record.attributes:
                ms = (time.perf_counter() - self._record._mono_start) * 1000
                self._record.attributes[attribute] = round(ms, 1)
        except Exception:
            warn_once("tracing: first-token time failed")

    def finish(self, outputs: Any = None, **attributes: Any) -> None:
        try:
            if self._done:
                return
            self._record.outputs = outputs
            self._record.attributes.update({k: v for k, v in attributes.items() if v is not None})
            self._end()
        except Exception:
            warn_once("tracing: finishing a gateway span failed")

    def fail(self, exc: BaseException, **attributes: Any) -> None:
        try:
            if self._done:
                return
            self._record.status = "ERROR"
            self._record.attributes.update(_error_attributes(exc, self._tags))
            self._record.attributes.update({k: v for k, v in attributes.items() if v is not None})
            self._end()
        except Exception:
            warn_once("tracing: failing a gateway span failed")

    def _end(self) -> None:
        self._done = True
        _close(self._record)
        if self._parent is None:
            _emit(self._tags, self._record)


class _NoCall(GatewayCall):
    def __init__(self) -> None:
        self._done = True

    @property
    def content(self) -> TraceContent:
        return "redacted"

    def first_token(self, attribute: str = "ttft_ms") -> None:
        return None

    def finish(self, outputs: Any = None, **attributes: Any) -> None:
        return None

    def fail(self, exc: BaseException, **attributes: Any) -> None:
        return None


NO_CALL: GatewayCall = _NoCall()


def start_gateway_call(name: str, kind: SpanKind, attributes: dict[str, Any]) -> GatewayCall:
    """Open the span of one gateway call, or return a no-op when nothing is recorded.

    `attributes` may hold "inputs": the call's inputs, already shaped by `content_of`.
    """
    try:
        tags = _recording()
        if tags is None:
            return NO_CALL
        attrs = dict(attributes)
        inputs = attrs.pop("inputs", None)
        record = _new_span(name, kind, {k: v for k, v in attrs.items() if v is not None})
        record.inputs = inputs
        parent = _current.get()
        if parent is not None:
            parent.children.append(record)
        return GatewayCall(tags, record, parent)
    except Exception:
        warn_once("tracing: opening a gateway span failed")
        return NO_CALL


# --- turns assembled after the fact (voice, LT-6) --------------------------------------------


class TurnCollector:
    """Groups the gateway spans of a voice session into one trace per turn (LT-6).

    LiveKit runs STT, the interviewer and TTS in tasks of its own, so no single block of code
    can open a turn span around them. Instead the collector is the parent of every gateway span
    in the session (set before the room connects, so every task inherits it), and the voice agent
    calls `cut()` when a turn's metrics arrive: the spans that have finished since the last cut
    become the children of one `turn` trace. A span still running waits for the next cut.
    """

    def __init__(self, tags: TraceTags) -> None:
        self.tags = tags
        self.record = _new_span("voice.session", "CHAIN", None)

    def cut(self, kind: Literal["voice", "text"], index: int, attributes: dict[str, Any]) -> None:
        """Send the finished spans as turn `index`, with `attributes`. Never raises."""
        try:
            done = [c for c in self.record.children if c.end_ns is not None]
            if not done and not attributes:
                return
            self.record.children = [c for c in self.record.children if c.end_ns is None]
            now = time.time_ns()
            start = min((c.start_ns for c in done), default=now)
            turn = SpanRecord(
                name="turn",
                kind="CHAIN",
                start_ns=start,
                end_ns=now,
                attributes={"turn.kind": kind, "turn.index": index},
                children=done,
            )
            turn.attributes.update({k: v for k, v in attributes.items() if v is not None})
            turn.attributes.setdefault("duration_ms", round((now - start) / 1e6, 1))
            _emit(self.tags, turn)
        except Exception:
            warn_once("tracing: cutting a turn failed")

    def flush(self) -> None:
        """Send what is left when the session ends (the greeting, a last unanswered turn)."""
        try:
            done = [c for c in self.record.children if c.end_ns is not None]
            if done:
                self.cut("voice", -1, {"turn.rest": True})
        except Exception:
            warn_once("tracing: flushing turns failed")


@contextmanager
def collect_turns(*, flush_on_exit: bool = True) -> Iterator[TurnCollector | None]:
    """Make a TurnCollector the parent of every gateway span started in this block (and in the
    tasks it starts). Yields None, and does nothing, when nothing is recorded.

    Tasks started in the block keep the collector after the block ends. When the session outlives
    the block (a LiveKit entrypoint returns once the session starts), pass flush_on_exit=False
    and call `flush()` when the session really ends."""
    tags = _recording()
    if tags is None:
        yield None
        return
    collector = TurnCollector(tags)
    token = _current.set(collector.record)
    try:
        yield collector
    finally:
        _current.reset(token)
        if flush_on_exit:
            collector.flush()


# --- content (LT-4) ---------------------------------------------------------------------------


def digest(text: str) -> dict[str, Any]:
    """What a redacted span keeps of a text: its SHA-256 and its length."""
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "len": len(text)}


def content_of(value: Any, content: TraceContent) -> Any:
    """`value` as stored on a span: as it is when content is full, else a digest of its text."""
    if content == "full":
        return value
    if isinstance(value, str):
        return digest(value)
    return digest(json.dumps(value, sort_keys=True, default=str))


def messages_of(messages: Sequence[Message], content: TraceContent) -> list[dict[str, Any]]:
    """Chat messages as stored on a span. Role and prompt ref are kept in both modes."""
    out: list[dict[str, Any]] = []
    for m in messages:
        item: dict[str, Any] = {"role": m.role}
        if m.prompt_ref:
            item["prompt_ref"] = m.prompt_ref
        if content == "full":
            item["content"] = m.content
        else:
            item.update(digest(m.content))
        out.append(item)
    return out


def _error_attributes(exc: BaseException, tags: TraceTags) -> dict[str, Any]:
    attrs: dict[str, Any] = {"error.type": type(exc).__name__}
    # The message of a validation error can quote the model's reply, so it is kept only when the
    # content may be stored.
    if tags.content == "full":
        attrs["error.message"] = str(exc)[:ERROR_MESSAGE_CHARS]
    return attrs


# --- quiet failures (D-10) -------------------------------------------------------------------

_last_warning: dict[str, float] = {}
WARN_EVERY_S = 60.0


def warn_once(message: str) -> None:
    """Log `message` at most once a minute, with the current exception if there is one."""
    now = time.monotonic()
    if now - _last_warning.get(message, -WARN_EVERY_S) < WARN_EVERY_S:
        return
    _last_warning[message] = now
    exc = sys.exc_info()[1]
    if exc is None:
        log.warning(message)
        return
    log.warning("%s (%s: %s)", message, type(exc).__name__, str(exc)[:ERROR_MESSAGE_CHARS])
    log.debug(message, exc_info=True)


def with_tags(tags: TraceTags, **changes: Any) -> TraceTags:
    return replace(tags, **changes)


__all__ = [
    "NO_CALL",
    "Exporter",
    "GatewayCall",
    "SpanHandle",
    "SpanRecord",
    "TraceRecord",
    "TraceTags",
    "TurnCollector",
    "collect_turns",
    "content_of",
    "current_trace_tags",
    "digest",
    "flush",
    "is_active",
    "messages_of",
    "set_exporter_override",
    "span",
    "start_gateway_call",
    "trace_context",
    "turn_span",
    "warn_once",
    "with_tags",
]
