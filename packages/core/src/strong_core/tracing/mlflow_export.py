"""Send finished traces to MLflow from a background thread (D-10, LT-5).

`submit` only puts the trace on a bounded queue: it never blocks and never raises. One daemon
thread replays each trace into MLflow with its real start and end times. A full queue drops the
trace; an unreachable server loses traces, logs at most once a minute, and costs the call path
nothing.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
from typing import TYPE_CHECKING, Any

from strong_core.tracing import SpanRecord, TraceRecord, warn_once

if TYPE_CHECKING:
    from mlflow.entities import LiveSpan

QUEUE_SIZE = 1000
SESSION_METADATA = "mlflow.trace.session"


class MlflowExporter:
    def __init__(
        self,
        tracking_uri: str | None = None,
        default_experiment: str | None = None,
        *,
        queue_size: int = QUEUE_SIZE,
    ) -> None:
        from strong_core.config import get_settings

        settings = get_settings()
        self.tracking_uri = tracking_uri or settings.mlflow_tracking_uri or ""
        self.default_experiment = default_experiment or settings.mlflow_experiment
        self._queue: queue.Queue[TraceRecord | None] = queue.Queue(maxsize=queue_size)
        self._experiments: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._configured = False

    # --- the call path -----------------------------------------------------------------------

    def submit(self, trace: TraceRecord) -> None:
        try:
            self._ensure_thread()
            self._queue.put_nowait(trace)
        except queue.Full:
            warn_once("tracing: export queue full, dropping traces")
        except Exception:
            warn_once("tracing: could not queue a trace")

    def flush(self, timeout_s: float = 10.0) -> bool:
        """Wait until every queued trace has been sent or dropped. True when the queue drained."""
        deadline = time.monotonic() + timeout_s
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout_s: float = 10.0) -> None:
        """Send what is queued, then stop the thread. Later traces are dropped."""
        thread = self._thread
        if not isinstance(thread, threading.Thread):
            return
        try:
            self._queue.put(None, timeout=timeout_s)
        except queue.Full:
            return
        thread.join(timeout_s)

    # --- the background thread ---------------------------------------------------------------

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="strong-trace-export", daemon=True
                )
                self._thread.start()
                atexit.register(self.flush, 5.0)

    def _run(self) -> None:
        while True:
            trace = self._queue.get()
            if trace is None:  # close()
                self._queue.task_done()
                return
            try:
                self._send(trace)
            except Exception:
                warn_once("tracing: sending a trace to MLflow failed")
            finally:
                self._queue.task_done()

    def _configure(self) -> None:
        if self._configured:
            return
        # Traces are already off the call path here; MLflow's own async logging would only add
        # a second queue.
        os.environ.setdefault("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
        # A down server should cost a few seconds per trace here, not minutes of retries.
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")  # no assistant hint in our logs
        import mlflow

        mlflow.set_tracking_uri(self.tracking_uri)
        self._configured = True

    def _experiment_id(self, name: str) -> str:
        if name not in self._experiments:
            import mlflow

            self._experiments[name] = mlflow.set_experiment(name).experiment_id
        return self._experiments[name]

    def _send(self, trace: TraceRecord) -> None:
        self._configure()
        import mlflow

        experiment_id = self._experiment_id(trace.tags.experiment or self.default_experiment)
        metadata = {SESSION_METADATA: trace.tags.session_id} if trace.tags.session_id else {}
        root = trace.root
        live = mlflow.start_span_no_context(
            root.name,
            span_type=root.kind,
            inputs=root.inputs,
            attributes=_attributes(root),
            tags=trace.tags.as_tags(),
            metadata=metadata,
            experiment_id=experiment_id,
            start_time_ns=root.start_ns,
        )
        for child in root.children:
            self._send_span(child, live)
        _end(live, root)

    def _send_span(self, record: SpanRecord, parent: LiveSpan) -> None:
        import mlflow

        live = mlflow.start_span_no_context(
            record.name,
            span_type=record.kind,
            parent_span=parent,
            inputs=record.inputs,
            attributes=_attributes(record),
            start_time_ns=record.start_ns,
        )
        for child in record.children:
            self._send_span(child, live)
        _end(live, record)


def _attributes(record: SpanRecord) -> dict[str, Any]:
    """MLflow keeps attributes as JSON; anything else becomes its string form."""
    out: dict[str, Any] = {}
    for key, value in record.attributes.items():
        try:
            json.dumps(value)
            out[key] = value
        except TypeError:
            out[key] = str(value)
    return out


def _end(live: LiveSpan, record: SpanRecord) -> None:
    end_ns = record.end_ns or record.start_ns
    live.end(outputs=record.outputs, status=record.status, end_time_ns=end_ns)
