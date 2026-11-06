"""In-memory tracing for tests: no MLflow, no network.

from strong_core.tracing.testing import trace_capture  # noqa: F401  (a pytest fixture)

async def test_x(trace_capture: InMemoryExporter) -> None:
    with trace_context(TraceTags(session_id="s1")):
        await gateway.complete(...)
    (trace,) = trace_capture.traces
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from strong_core.tracing import SpanRecord, TraceRecord, set_exporter_override


class InMemoryExporter:
    def __init__(self) -> None:
        self.traces: list[TraceRecord] = []

    def submit(self, trace: TraceRecord) -> None:
        self.traces.append(trace)

    def spans(self) -> list[SpanRecord]:
        return [s for t in self.traces for s in t.spans()]

    def clear(self) -> None:
        self.traces.clear()


@pytest.fixture
def trace_capture() -> Iterator[InMemoryExporter]:
    """Turn tracing on for one test and collect its finished traces."""
    exporter = InMemoryExporter()
    previous = set_exporter_override(exporter)
    try:
        yield exporter
    finally:
        set_exporter_override(previous)
