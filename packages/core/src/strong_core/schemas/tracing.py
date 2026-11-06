"""How a sim session is traced (LT-14, docs/llm-tracing/spec.md)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from strong_core.schemas.base import Contract

TraceContent = Literal["full", "redacted"]
"""full: spans keep message text (fixture personas only). redacted: a hash and a length (D-6)."""


class SessionTraceSettings(Contract):
    """Stored in sessions.trace_json for a sim user's session. NULL for every other session."""

    sim_run_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    scenario: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    content: TraceContent = "redacted"
