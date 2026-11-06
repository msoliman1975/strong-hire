"""One MLflow run per sim run (LT-8, LT-9, LT-13, D-6), with a fake MLflow backend."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

import strong_sim.mlflow_run as mlflow_run
from strong_core.gateway import ModelGateway
from strong_core.tracing import TraceRecord
from strong_core.tracing.testing import InMemoryExporter, trace_capture
from strong_sim.client import AppClient, trace_headers
from strong_sim.cost import CostMeter, load_prices
from strong_sim.judge import RULES
from strong_sim.mlflow_run import SimRunLog, SpanView, TraceView, run_values
from strong_sim.report import SessionRow
from strong_sim.runner import run_suite
from strong_sim.scenarios import Scenario, Suite
from strong_sim.settings import SimSettings

__all__ = ["trace_capture"]

TOKEN = "t" * 40
ALIAS = "app-interviewer"  # a gateway alias, never a model name


def _view(record: TraceRecord) -> TraceView:
    spans = [SpanView(s.name, dict(s.attributes), s.status) for s in record.spans()]
    return TraceView(record.trace_id, record.root.name, record.tags.as_tags(), spans)


def _server_turn(sid: str, run: str, ttft: float, e2e: float, retry: bool) -> TraceView:
    """What the main server would have sent for one text turn of a sim session."""
    call = {
        "role": "interviewer",
        "alias": ALIAS,
        "tier": "large",
        "prompt_refs": ["interviewer/turn.v3"],
        "ttft_ms": ttft,
        "cost_usd": 0.002,
        "structured_retry": retry,
    }
    spans = [
        SpanView("turn", {"turn.kind": "text", "turn.index": 1, "duration_ms": e2e}, "OK"),
        SpanView("gateway.interviewer", call, "OK"),
    ]
    tags = {"session_id": sid, "sim_run_id": run, "service": "api"}
    return TraceView(f"tr-{sid}-{ttft}", "turn", tags, spans)


class FakeBackend:
    """Records every MLflow call. `traces()` returns the server's traces plus the judge traces
    this process recorded."""

    def __init__(self, server: Callable[[], list[TraceView]], judges: InMemoryExporter) -> None:
        self.server = server
        self.judges = judges
        self.calls: list[tuple[str, Any]] = []
        self.params: dict[str, str] = {}
        self.metrics: dict[str, float] = {}
        self.files: list[str] = []
        self.assessments: list[tuple[str, str, str, str]] = []

    def start_run(self, experiment: str, name: str, tags: dict[str, str]) -> str:
        self.calls.append(("start_run", (experiment, name, tags)))
        return "mlflow-run-1"

    def log(self, run_id: str, params: dict[str, str], metrics: dict[str, float]) -> None:
        self.params.update(params)
        self.metrics.update(metrics)

    def log_file(self, run_id: str, path: Path) -> None:
        self.files.append(path.name)

    def log_json(self, run_id: str, data: dict[str, Any], name: str) -> None:
        self.files.append(name)

    def end_run(self, run_id: str, status: str) -> None:
        self.calls.append(("end_run", status))

    def traces(self, experiment: str, sim_run_id: str) -> list[TraceView]:
        judges = [_view(t) for t in self.judges.traces if t.tags.sim_run_id == sim_run_id]
        return self.server() + judges

    def assess(self, trace_id: str, name: str, value: str, rationale: str, source: str) -> None:
        self.assessments.append((trace_id, name, value, source))


class Broken(FakeBackend):
    def __getattribute__(self, name: str) -> Any:
        if name in {"start_run", "log", "log_file", "log_json", "end_run", "traces", "assess"}:

            def fail(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("MLflow is down")

            return fail
        return super().__getattribute__(name)


def _client(settings: SimSettings, api: Any, seen: list[httpx.Request]) -> AppClient:
    def record(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions") and request.method == "POST":
            seen.append(request)
        response: httpx.Response = api(request)
        return response

    http = httpx.AsyncClient(base_url=settings.base_url, transport=httpx.MockTransport(record))
    return AppClient(settings, http)


def _settings(tmp_path: Path) -> SimSettings:
    return SimSettings(
        base_url="https://sim.test/api", token=TOKEN, out_dir=tmp_path / "runs", upload_target=""
    )


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mlflow_run, "TRACE_POLL_S", 0.0)
    monkeypatch.setattr(mlflow_run, "TRACE_WAIT_S", 0.5)


def _suite() -> Suite:
    return Suite(
        name="lt-suite",
        scenarios=[
            Scenario(id="a", quality="strong", candidate_name="Ada Venn"),
            Scenario(id="b", quality="weak", candidate_name="Cal Dunmore"),
        ],
    )


async def test_lt8_a_suite_is_one_run_with_its_params_metrics_and_files(
    tmp_path: Path,
    fake_gateway: ModelGateway,
    fake_api: Any,
    trace_capture: InMemoryExporter,
    monkeypatch: pytest.MonkeyPatch,
    fast: None,
) -> None:
    """LT-8: params say what made the run different; metrics sum it up; files are attached."""
    api = fake_api(TOKEN)
    seen: list[httpx.Request] = []

    def server() -> list[TraceView]:
        out = []
        for i, sid in enumerate(sorted(api.sessions)):
            out.append(_server_turn(sid, "run-1", ttft=200.0 + 100 * i, e2e=900.0, retry=i == 0))
        return out

    backend = FakeBackend(server, trace_capture)
    monkeypatch.setattr(mlflow_run.MlflowBackend, "from_settings", classmethod(lambda c: backend))
    settings = _settings(tmp_path)
    client = _client(settings, api, seen)
    _, info = await run_suite(
        _suite(), settings, fake_gateway, CostMeter(load_prices()), "run-1", client
    )
    assert info["sessions_ok"] == 2

    (start,) = [c for c in backend.calls if c[0] == "start_run"]
    assert start[1][1] == "run-1" and start[1][2] == {"sim_run_id": "run-1", "source": "suite"}
    p = backend.params
    assert (p["suite"], p["source"], p["scenario_count"]) == ("lt-suite", "suite", "2")
    assert p["model_profile"] == "fake" and p["git_sha"]
    assert p["interviewer.alias"] == ALIAS and p["interviewer.tier"] == "large"
    assert p["interviewer.prompt_refs"] == "interviewer/turn.v3"
    assert "judge.prompt_refs" in p  # the sim's own judge calls are traced too
    m = backend.metrics
    assert (m["sessions"], m["sessions_ok"], m["sessions_failed"]) == (2, 2, 0)
    for rule in RULES:
        assert m[f"judge_{rule}_pass_rate"] == 1.0
    assert m["interviewer_ttft_p50_ms"] == 250.0 and m["interviewer_ttft_p95_ms"] == 295.0
    assert m["turn_latency_p50_ms"] == 900.0
    assert m["server_cost_per_session_usd"] == 0.002
    assert m["structured_retries"] == 1 and m["gateway_errors"] == 0
    assert set(backend.files) == {"report.html", "report.json", "sessions.json"}
    assert backend.calls[-1] == ("end_run", "FINISHED")

    # LT-14: every session was created with the run, its scenario and the content mode.
    assert [r.headers["x-sim-run"] for r in seen] == ["run-1", "run-1"]
    assert [r.headers["x-sim-scenario"] for r in seen] == ["a", "b"]
    assert {r.headers["x-sim-trace-content"] for r in seen} == {"full"}


async def test_lt9_each_session_verdict_is_attached_to_its_judge_trace(
    tmp_path: Path,
    fake_gateway: ModelGateway,
    fake_api: Any,
    trace_capture: InMemoryExporter,
    monkeypatch: pytest.MonkeyPatch,
    fast: None,
) -> None:
    """LT-9: one assessment per rule on the session's own judge trace, with the rubric."""
    api = fake_api(TOKEN)
    backend = FakeBackend(list, trace_capture)
    monkeypatch.setattr(mlflow_run.MlflowBackend, "from_settings", classmethod(lambda c: backend))
    settings = _settings(tmp_path)
    await run_suite(
        _suite(),
        settings,
        fake_gateway,
        CostMeter(load_prices()),
        "run-9",
        _client(settings, api, []),
    )
    judges = {t.tags.session_id: t for t in trace_capture.traces if t.root.name == "judge"}
    assert set(judges) == set(api.sessions)
    for trace in judges.values():
        assert trace.root.kind == "EVALUATOR" and trace.tags.service == "sim"
        assert trace.tags.sim_run_id == "run-9" and trace.tags.content == "full"
        assert any(c.name == "gateway.judge" for c in trace.root.children)
        mine = [a for a in backend.assessments if a[0] == trace.trace_id]
        assert [a[1] for a in mine] == list(RULES)
        assert {a[2] for a in mine} == {"pass"} and {a[3] for a in mine} == {"judge/transcript.v1"}


async def test_lt13_a_broken_mlflow_never_fails_the_run(
    tmp_path: Path,
    fake_gateway: ModelGateway,
    fake_api: Any,
    trace_capture: InMemoryExporter,
    monkeypatch: pytest.MonkeyPatch,
    fast: None,
) -> None:
    """LT-13: every MLflow call raising still leaves a complete run on disk."""
    api = fake_api(TOKEN)
    broken = Broken(list, trace_capture)
    monkeypatch.setattr(mlflow_run.MlflowBackend, "from_settings", classmethod(lambda c: broken))
    settings = _settings(tmp_path)
    run_dir, info = await run_suite(
        _suite(),
        settings,
        fake_gateway,
        CostMeter(load_prices()),
        "run-x",
        _client(settings, api, []),
    )
    assert info["sessions_ok"] == 2
    assert (run_dir / "report.json").exists() and (run_dir / "report.html").exists()


async def test_lt13_with_tracing_off_mlflow_is_never_touched(
    tmp_path: Path,
    fake_gateway: ModelGateway,
    fake_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-1, LT-13: no LLM_TRACING, no MLflow connection at all; the run is as before."""

    def refuse(cls: Any) -> Any:
        raise AssertionError("MLflow was contacted")

    monkeypatch.setattr(mlflow_run.MlflowBackend, "from_settings", classmethod(refuse))
    settings = _settings(tmp_path)
    _, info = await run_suite(
        _suite(), settings, fake_gateway, CostMeter(load_prices()), "run-off",
        _client(settings, fake_api(TOKEN), []),
    )  # fmt: skip
    assert info["sessions_ok"] == 2


def test_d6_a_pasted_resume_or_job_is_redacted() -> None:
    """D-6, LT-4: full content only for a fixture persona."""
    fixture = Scenario(id="f", quality="strong", candidate_name="Ada Venn")
    pasted = Scenario(id="p", quality="strong", candidate_name="Ada Venn", cv_text="My resume.")
    assert trace_headers(fixture, "r")["X-Sim-Trace-Content"] == "full"
    assert trace_headers(pasted, "r")["X-Sim-Trace-Content"] == "redacted"
    assert "X-Sim-Run" not in trace_headers(fixture, None)


def test_lt8_run_values_skip_missing_steps_and_count_failures() -> None:
    """LT-8: unreported timings are skipped, the end-of-session rest is not a turn, and
    validation failures are counted among gateway errors."""
    row = SessionRow(
        scenario_id="a", channel="voice", interview_type="behavioral", difficulty="realistic",
        mode="realistic", duration_min=10, resume="r", quality="strong", behavior="normal",
        status="ok", session_id="s", latency_p50_ms=700.0, latency_p95_ms=1200.0,
    )  # fmt: skip
    spans = [
        SpanView("turn", {"turn.index": 1, "e2e_ms": 800.0}, "OK"),
        SpanView("turn", {"turn.index": -1, "turn.rest": True, "duration_ms": 99999.0}, "OK"),
        SpanView("turn", {"turn.index": 2, "e2e_ms": math.nan}, "OK"),
        SpanView("gateway.scorer", {"role": "scorer", "error.type": "ValidationError"}, "ERROR"),
        SpanView("gateway.stt", {"role": "stt", "error.type": "GatewayError"}, "ERROR"),
    ]
    trace = TraceView("t", "turn", {"service": "voice", "session_id": "s"}, spans)
    _, metrics = run_values([row], {"per_rule": {"tone": {"pass": 3, "fail": 1}}}, [trace])
    assert metrics["turn_latency_p50_ms"] == 800.0
    assert metrics["gateway_errors"] == 2 and metrics["validation_failures"] == 1
    assert metrics["judge_tone_pass_rate"] == 0.75
    assert metrics["client_turn_latency_p50_ms"] == 700.0
    assert "scorer_ttft_p50_ms" not in metrics


def test_lt8_disabled_log_does_nothing() -> None:
    """LT-13: a disabled run log accepts every call and does nothing."""
    log = SimRunLog(None, "r")
    assert not log.enabled
    log.finish([], {}, None)
