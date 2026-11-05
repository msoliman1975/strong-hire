"""One MLflow run per sim run (LT-8 to LT-10, LT-13, docs/llm-tracing/spec.md).

A suite from sim-run.ps1 and a single admin sim (SM) are each one run in the `sim` experiment,
named after the sim run id. Every session the run creates carries that id (X-Sim-Run), so the
traces the main server records for it have the tag `sim_run_id`. When the run ends:

- params say what made the run different: suite, source, model profile, the alias and tier of
  each role and the prompt refs it used (read from the run's traces), git SHA, scenario count;
- metrics sum it up: sessions done and failed, cost per session, turn latency, first-token time
  for each role, retries, validation failures, gateway errors, and each judge rule's pass rate;
- the report and the per-session rows are artifacts;
- each session's judge verdict is attached to its judge trace, one assessment per rule.

Nothing here may fail a sim run (LT-13): every MLflow call is wrapped, and a failure is logged
once. With tracing off (no LLM_TRACING=on and tracking URI), the log does nothing at all.
"""

from __future__ import annotations

import functools
import logging
import math
import os
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway
from strong_core.ops.heartbeat import release
from strong_core.tracing import flush, is_active
from strong_sim.judge import RULES, JudgeResult
from strong_sim.report import SessionRow

log = logging.getLogger("strong_sim.mlflow")

TRACE_WAIT_S = 30.0
TRACE_POLL_S = 3.0
TRACE_PAGE = 200
SERVER_SERVICES = ("api", "worker", "voice")


@dataclass(frozen=True)
class SpanView:
    """What the run's metrics need from one span, whatever MLflow version returned it."""

    name: str
    attributes: dict[str, Any]
    status: str


@dataclass(frozen=True)
class TraceView:
    trace_id: str
    name: str
    tags: dict[str, str]
    spans: list[SpanView]


class RunBackend(Protocol):
    """The MLflow calls the run log makes. MlflowBackend in production, a fake in tests."""

    def start_run(self, experiment: str, name: str, tags: dict[str, str]) -> str: ...

    def log(self, run_id: str, params: dict[str, str], metrics: dict[str, float]) -> None: ...

    def log_file(self, run_id: str, path: Path) -> None: ...

    def log_json(self, run_id: str, data: dict[str, Any], name: str) -> None: ...

    def end_run(self, run_id: str, status: str) -> None: ...

    def traces(self, experiment: str, sim_run_id: str) -> list[TraceView]: ...

    def assess(
        self, trace_id: str, name: str, value: str, rationale: str, source_id: str
    ) -> None: ...


@dataclass
class SimRunLog:
    """The MLflow run of one sim run. A disabled log (no backend) does nothing."""

    backend: RunBackend | None
    sim_run_id: str
    experiment: str = "sim"
    run_id: str | None = None
    verdicts: dict[str, JudgeResult] = field(default_factory=dict)
    trace_wait_s: float = TRACE_WAIT_S
    trace_poll_s: float = TRACE_POLL_S
    sleep: Callable[[float], None] = time.sleep

    # --- start ------------------------------------------------------------------------------

    @classmethod
    def start(
        cls,
        sim_run_id: str,
        *,
        suite: str,
        source: str,
        gateway: ModelGateway,
        scenarios: int,
        backend: RunBackend | None = None,
    ) -> SimRunLog:
        """Open the run, or return a disabled log when tracing is off or MLflow fails."""
        if backend is None:
            if not is_active():
                return cls(None, sim_run_id)
            backend = _safe(MlflowBackend.from_settings, "connecting to MLflow")
            if backend is None:
                return cls(None, sim_run_id)
        experiment = get_settings().mlflow_experiment
        run = cls(
            backend, sim_run_id, experiment, trace_wait_s=TRACE_WAIT_S, trace_poll_s=TRACE_POLL_S
        )
        tags = {"sim_run_id": sim_run_id, "source": source}
        run.run_id = _safe(
            lambda: backend.start_run(experiment, sim_run_id, tags), "starting the MLflow run"
        )
        if run.run_id is None:
            return cls(None, sim_run_id)
        params = {
            "suite": suite,
            "source": source,
            "model_profile": gateway.profile,
            "git_sha": release(),
            "scenario_count": str(scenarios),
        }
        run._log(params, {})
        return run

    @property
    def enabled(self) -> bool:
        return self.backend is not None and self.run_id is not None

    # --- during the run -----------------------------------------------------------------------

    def judged(self, session_id: str, verdict: JudgeResult) -> None:
        """Keep a session's verdict; it is attached to its judge trace at the end (LT-9)."""
        if self.enabled:
            self.verdicts[session_id] = verdict

    # --- the end ------------------------------------------------------------------------------

    def finish(
        self,
        rows: Sequence[SessionRow],
        info: dict[str, Any],
        run_dir: Path | None,
        *,
        failed: bool = False,
    ) -> None:
        """Log params, metrics, artifacts and assessments, and end the run. Never raises."""
        if not self.enabled:
            return
        backend, run_id = self.backend, self.run_id
        assert backend is not None and run_id is not None
        flush(self.trace_wait_s)  # the judge traces this process made
        traces = self._wait_for_traces(len([r for r in rows if r.session_id]))
        params, metrics = run_values(rows, info, traces)
        self._log(params, metrics)
        self._assess(traces)
        if run_dir is not None:
            for name in ("report.html", "report.json"):
                path = run_dir / name
                if path.exists():
                    _safe(functools.partial(backend.log_file, run_id, path), f"logging {name}")
        sessions = {"sessions": [r.model_dump(mode="json") for r in rows]}
        _safe(lambda: backend.log_json(run_id, sessions, "sessions.json"), "logging the rows")
        status = "FAILED" if failed or not any(r.status == "ok" for r in rows) else "FINISHED"
        _safe(lambda: backend.end_run(run_id, status), "ending the MLflow run")

    def _log(self, params: dict[str, str], metrics: dict[str, float]) -> None:
        assert self.backend is not None and self.run_id is not None
        backend, run_id = self.backend, self.run_id
        _safe(lambda: backend.log(run_id, params, metrics), "logging params and metrics")

    def _wait_for_traces(self, sessions: int) -> list[TraceView]:
        """The run's traces, once their number stops growing (the main server sends them in
        the background), or after trace_wait_s."""
        assert self.backend is not None
        backend = self.backend
        deadline = time.monotonic() + self.trace_wait_s
        last: list[TraceView] = []
        while True:
            found = _safe(lambda: backend.traces(self.experiment, self.sim_run_id), "traces")
            found = found or []
            judges = sum(1 for t in found if t.name == "judge")
            if found and len(found) == len(last) and judges >= len(self.verdicts):
                return found
            last = found
            if time.monotonic() >= deadline or sessions == 0:
                return found
            self.sleep(self.trace_poll_s)

    def _assess(self, traces: Iterable[TraceView]) -> None:
        """One assessment per judge rule on each session's judge trace (LT-9)."""
        assert self.backend is not None
        backend = self.backend
        by_session = {t.tags.get("session_id"): t for t in traces if t.name == "judge" and t.tags}
        for session_id, verdict in self.verdicts.items():
            trace = by_session.get(session_id)
            if trace is None:
                log.warning("no judge trace found for session %s", session_id)
                continue
            for rule in verdict.rules:
                trace_id, rubric = trace.trace_id, verdict.rubric
                name, value, reason = rule.rule, rule.verdict, rule.reason

                def assess(
                    t: str = trace_id,
                    n: str = name,
                    v: str = value,
                    why: str = reason,
                    src: str = rubric,
                ) -> None:
                    backend.assess(t, n, v, why, src)

                _safe(assess, "logging an assessment")


# --- metrics from the report and the traces ----------------------------------------------------


def _percentile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(v for v in values if isinstance(v, int | float) and not math.isnan(v))
    if not clean:
        return None
    if len(clean) == 1:
        return float(clean[0])
    k = (len(clean) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return float(clean[lo] + (clean[hi] - clean[lo]) * (k - lo))


def run_values(
    rows: Sequence[SessionRow], info: dict[str, Any], traces: Sequence[TraceView]
) -> tuple[dict[str, str], dict[str, float]]:
    """The run's params and metrics (LT-8, LT-9)."""
    metrics: dict[str, float] = {}
    params: dict[str, str] = {}
    sessions = len(rows)
    ok = [r for r in rows if r.status == "ok"]
    metrics["sessions"] = sessions
    metrics["sessions_ok"] = len(ok)
    metrics["sessions_failed"] = sessions - len(ok)
    metrics["sessions_all_rules_pass"] = float(info.get("sessions_all_rules_pass") or 0)
    sim_cost = sum(r.sim_cost_usd for r in rows)
    if sessions:
        metrics["sim_cost_per_session_usd"] = round(sim_cost / sessions, 6)
    client_p50 = [r.latency_p50_ms for r in ok if r.latency_p50_ms is not None]
    client_p95 = [r.latency_p95_ms for r in ok if r.latency_p95_ms is not None]
    if client_p50:
        metrics["client_turn_latency_p50_ms"] = float(statistics.median(client_p50))
    if client_p95:
        metrics["client_turn_latency_p95_ms"] = float(max(client_p95))

    # Each judge rule's pass rate among the sessions it applied to (LT-9).
    per_rule: dict[str, dict[str, int]] = info.get("per_rule") or {}
    for rule in RULES:
        counts = per_rule.get(rule) or {}
        judged = counts.get("pass", 0) + counts.get("fail", 0)
        if judged:
            metrics[f"judge_{rule}_pass_rate"] = round(counts.get("pass", 0) / judged, 4)

    # From the traces: what the main server did for these sessions.
    spans = [s for t in traces for s in t.spans]
    gateway = [s for s in spans if s.name.startswith("gateway.")]
    server = [s for t in traces if t.tags.get("service") in SERVER_SERVICES for s in t.spans]
    server_cost = sum(
        float(s.attributes.get("cost_usd") or 0) for s in server if s.name.startswith("gateway.")
    )
    if sessions:
        metrics["server_cost_per_session_usd"] = round(server_cost / sessions, 6)
    turns = [s for s in spans if s.name == "turn"]
    turn_ms = [
        float(s.attributes.get("e2e_ms", s.attributes.get("duration_ms", math.nan)))
        for s in turns
        if s.attributes.get("turn.index", 0) != -1
    ]
    for q in (50, 95):
        value = _percentile(turn_ms, q)
        if value is not None:
            metrics[f"turn_latency_p{q}_ms"] = round(value, 1)
    by_role: dict[str, list[SpanView]] = defaultdict(list)
    for s in gateway:
        by_role[str(s.attributes.get("role") or s.name.removeprefix("gateway."))].append(s)
    for role, role_spans in sorted(by_role.items()):
        ttft = [float(s.attributes["ttft_ms"]) for s in role_spans if "ttft_ms" in s.attributes]
        for q in (50, 95):
            value = _percentile(ttft, q)
            if value is not None:
                metrics[f"{role}_ttft_p{q}_ms"] = round(value, 1)
        first = role_spans[0].attributes
        if first.get("alias"):
            params[f"{role}.alias"] = str(first["alias"])
        if first.get("tier"):
            params[f"{role}.tier"] = str(first["tier"])
        refs = sorted({str(r) for s in role_spans for r in (s.attributes.get("prompt_refs") or [])})
        if refs:
            params[f"{role}.prompt_refs"] = ",".join(refs)[:500]
    metrics["structured_retries"] = sum(
        1 for s in gateway if s.attributes.get("structured_retry") is True
    )
    errors = [s for s in gateway if s.status == "ERROR"]
    metrics["gateway_errors"] = len(errors)
    metrics["validation_failures"] = sum(
        1 for s in errors if _is_validation(str(s.attributes.get("error.type") or ""))
    )
    metrics["traces"] = len(traces)
    return params, metrics


def _is_validation(error_type: str) -> bool:
    return "Validation" in error_type or "UnexpectedModelBehavior" in error_type


def _safe(fn: Callable[[], Any], what: str) -> Any:
    try:
        return fn()
    except Exception as exc:  # LT-13: MLflow trouble never fails a sim run
        log.warning("MLflow: %s failed (%s: %s)", what, type(exc).__name__, str(exc)[:200])
        return None


# --- the real backend --------------------------------------------------------------------------


class MlflowBackend:
    """RunBackend on mlflow-skinny. Imported only when tracing is on."""

    def __init__(self, tracking_uri: str) -> None:
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        import mlflow
        from mlflow import MlflowClient

        mlflow.set_tracking_uri(tracking_uri)
        self._mlflow = mlflow
        self.client = MlflowClient(tracking_uri)
        self._experiments: dict[str, str] = {}

    @classmethod
    def from_settings(cls) -> MlflowBackend:
        uri = get_settings().mlflow_tracking_uri
        if not uri:
            raise RuntimeError("no MLFLOW_TRACKING_URI")
        return cls(uri)

    def _experiment_id(self, name: str) -> str:
        if name not in self._experiments:
            found = self.client.get_experiment_by_name(name)
            self._experiments[name] = (
                found.experiment_id if found else self.client.create_experiment(name)
            )
        return self._experiments[name]

    def start_run(self, experiment: str, name: str, tags: dict[str, str]) -> str:
        run = self.client.create_run(self._experiment_id(experiment), run_name=name, tags=tags)
        return str(run.info.run_id)

    def log(self, run_id: str, params: dict[str, str], metrics: dict[str, float]) -> None:
        from mlflow.entities import Metric, Param

        now = int(time.time() * 1000)
        self.client.log_batch(
            run_id,
            metrics=[Metric(k, float(v), now, 0) for k, v in metrics.items()],
            params=[Param(k, str(v)[:6000]) for k, v in params.items()],
            synchronous=True,
        )

    def log_file(self, run_id: str, path: Path) -> None:
        self.client.log_artifact(run_id, str(path))

    def log_json(self, run_id: str, data: dict[str, Any], name: str) -> None:
        self.client.log_dict(run_id, data, name)

    def end_run(self, run_id: str, status: str) -> None:
        self.client.set_terminated(run_id, status=status)

    def traces(self, experiment: str, sim_run_id: str) -> list[TraceView]:
        out: list[TraceView] = []
        token: str | None = None
        while True:
            page = self.client.search_traces(
                locations=[self._experiment_id(experiment)],
                filter_string=f"tags.sim_run_id = '{sim_run_id}'",
                max_results=TRACE_PAGE,
                page_token=token,
            )
            out += [_view(t) for t in page]
            token = page.token
            if not token:
                return out

    def assess(self, trace_id: str, name: str, value: str, rationale: str, source_id: str) -> None:
        from mlflow.entities import AssessmentSource, AssessmentSourceType

        self._mlflow.log_feedback(
            trace_id=trace_id,
            name=name,
            value=value,
            rationale=rationale,
            source=AssessmentSource(AssessmentSourceType.LLM_JUDGE, source_id),
            metadata={"rubric": source_id},
        )


def _view(trace: Any) -> TraceView:
    spans = [
        SpanView(
            name=s.name,
            attributes=dict(s.attributes or {}),
            status=str(getattr(s.status, "status_code", s.status)).rsplit(".", 1)[-1],
        )
        for s in trace.data.spans
    ]
    root = next((s for s in trace.data.spans if s.parent_id is None), None)
    return TraceView(
        trace_id=str(trace.info.trace_id),
        name=root.name if root is not None else "",
        tags={k: v for k, v in (trace.info.tags or {}).items() if not k.startswith("mlflow.")},
        spans=spans,
    )
