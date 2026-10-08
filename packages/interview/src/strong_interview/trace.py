"""Interviewer traces (R2): one record per interviewer model call or fixed line.

The runner writes a TraceRecord to an optional TraceSink after each call: the controller's move
and reason, the timer state, the prompt messages, the raw reply, the spoken text, tokens, cost
and latency. The admin area shows them for users who turned on training consent.

`TraceSink.write` is synchronous and must not block: a sink that stores records does the I/O in
the background (see strong_interview.trace_store.SqlTraceSink). The runner catches and logs any
error from a sink, so tracing can never break an interview. Without a sink nothing is traced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from strong_core.gateway.types import Message
from strong_core.schemas import Phase

TraceCall = Literal["say", "decide", "line", "rollback"]


@dataclass(frozen=True)
class ModelCall:
    """What the interviewer sent to the model and got back, for one call."""

    messages: tuple[Message, ...]
    raw_reply: str | None
    model: str | None
    prompt_refs: tuple[str, ...]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    error: str | None = None


@dataclass(frozen=True)
class TraceRecord:
    seq: int
    turn_index: int
    call: TraceCall
    move: str
    reason: dict[str, Any]
    phase: Phase
    elapsed_ms: int
    phase_deadline_ms: int | None
    question_ref: str | None = None
    messages: list[dict[str, Any]] | None = None
    raw_reply: str | None = None
    spoken_text: str | None = None
    model: str | None = None
    prompt_refs: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int | None = None
    error: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TraceSink(Protocol):
    def write(self, record: TraceRecord) -> None:
        """Take one record. Must return at once; do slow I/O in the background."""


@dataclass
class ListTraceSink:
    """Keeps records in memory. For tests and the eval harness."""

    records: list[TraceRecord] = field(default_factory=list)

    def write(self, record: TraceRecord) -> None:
        self.records.append(record)


def message_dicts(messages: tuple[Message, ...]) -> list[dict[str, Any]]:
    return [{"role": m.role, "content": m.content, "prompt_ref": m.prompt_ref} for m in messages]
