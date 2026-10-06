"""The harness runs end to end on the fake model and writes a report (PL-1, spec Calibration)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from strong_core.config import Settings, find_repo_root
from strong_core.gateway import ModelGateway, build_gateway, load_models_config
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
from strong_evals.cli import main
from strong_evals.report import render_html
from strong_evals.runner import run_suite
from strong_evals.suites import Suite, load_suite, suite_names

REPO = find_repo_root()
SCORECARD = (DEFAULT_FIXTURES_DIR / "scorer" / "Scorecard.json").read_text(encoding="utf-8")


def test_suites_load() -> None:
    assert {"smoke", "goldset", "simulated", "full"} <= set(suite_names())
    full = load_suite("full")
    assert full.scripted == "all"
    assert len(full.simulated) == 12


async def test_smoke_suite_end_to_end_on_fake() -> None:
    report = await run_suite(load_suite("smoke"), "fake")
    assert report.errors == 0
    keys = {m.key: m for m in report.metrics}
    within = keys["scorer_within_one_band"]
    assert within.threshold == ">= 0.85"
    assert within.passed is not None
    for key in ("follow_up_rate", "competency_coverage", "cost_per_session_usd"):
        assert keys[key].passed is not None, key
    assert keys["cost_per_session_usd"].threshold == "<= 0.8"
    html = render_html(report)
    assert "Fake profile" in html
    assert "Scorer agreement, within one band" in html
    assert "PASS" in html or "FAIL" in html


def test_cli_run_writes_html_and_json(tmp_path: Path) -> None:
    code = main(["run", "--suite", "smoke", "--profile", "fake", "--out", str(tmp_path)])
    assert code == 0
    [html] = tmp_path.glob("smoke-fake-*.html")
    [data] = tmp_path.glob("smoke-fake-*.json")
    metrics = {m["key"]: m for m in json.loads(data.read_text(encoding="utf-8"))["metrics"]}
    assert set(metrics) >= {"scorer_within_one_band", "follow_up_rate", "cost_per_session_usd"}
    assert "<title>" in html.read_text(encoding="utf-8")


def test_gate_fails_when_a_metric_fails(tmp_path: Path) -> None:
    # The fake scorer gives one fixed signal, so it misses the 85% bar on the full gold set.
    args = ["run", "--suite", "goldset", "--profile", "fake", "--out", str(tmp_path), "--gate"]
    assert main(args) == 1


async def test_goldset_report_lists_company_value_agreement() -> None:
    """IV-5: company-mode transcripts add a value score agreement row to the report."""
    report = await run_suite(load_suite("goldset"), "fake")
    keys = {m.key: m for m in report.metrics}
    assert "value_within_one_point" in keys
    assert "2 company-mode transcripts" in keys["value_within_one_point"].detail


def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if info.output_tools:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, SCORECARD)])
    return ModelResponse(parts=[TextPart("I did it myself and cut costs 20 percent.")])


async def test_record_a_run_then_replay_it_on_fake(tmp_path: Path) -> None:
    """A run on a real profile records fixtures that the fake model replays exactly."""
    config = load_models_config(REPO / "config", "local")
    real = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(_model))
    suite = Suite(name="tiny", description="one transcript", scripted=["beh-01"])
    live = await run_suite(suite, "local", gateway=real, record_dir=tmp_path)
    assert live.recorded == 1
    assert live.profile == "local"
    assert live.errors == 0

    fake = build_gateway(Settings(model_profile="fake", fake_fixtures_dir=tmp_path))
    replay = await run_suite(suite, "fake", gateway=fake)
    assert replay.errors == 0
    assert replay.scripted[0].scorer == live.scripted[0].scorer
