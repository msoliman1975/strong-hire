"""The harness runs gap analysis over the P2 fixtures, and sessions use the real planner (P6)."""

from __future__ import annotations

from strong_core.config import Settings
from strong_core.gateway import build_gateway
from strong_core.schemas import SessionConfig
from strong_evals.candidate import Persona
from strong_evals.gap import INPUTS_DIR, POSTING_FOR_RESUME, GapPlanner, load_profile
from strong_evals.report import render_html, report_data
from strong_evals.runner import run_suite
from strong_evals.suites import load_suite
from strong_evals.transcripts import Quality


def test_gap_suite_covers_the_p2_fixtures() -> None:
    suite = load_suite("gap")
    resumes = {p.stem for p in (INPUTS_DIR / "resumes").glob("*.json")}
    assert {g.resume for g in suite.gap} == resumes
    assert {g.fit for g in suite.gap} == {"match", "mismatch"}
    assert set(POSTING_FOR_RESUME) == resumes
    assert any(g.profile for g in suite.gap)
    assert len(load_suite("full").gap) == len(suite.gap)


async def test_gap_suite_runs_on_fake() -> None:
    """GA-1: the report shows each pair's scores and the spread across runs."""
    report = await run_suite(load_suite("gap"), "fake")
    assert report.errors == 0
    assert all(len(g.scores) == g.spec.runs for g in report.gap)
    metrics = {m.key: m for m in report.metrics}
    assert metrics["gap_score_spread"].value == 0  # the fake model always gives the same ratings
    assert metrics["gap_score_spread"].passed is True
    assert metrics["gap_fit_order"].passed is not None
    assert "planner/gap_analysis.v1" in report.prompt_refs
    company = next(g for g in report.gap if g.spec.profile)
    assert company.generic_mode is False
    assert "<h2>Gap analysis</h2>" in render_html(report)
    assert report_data(report)["gap"][0]["scores"]


def test_load_profile_company_and_generic() -> None:
    assert load_profile(None).generic
    company = load_profile("examples/example-corp.json")
    assert company.company_name == "Example Corp" and company.version is not None


async def test_real_planner_builds_the_session_brief() -> None:
    gateway = build_gateway(Settings(model_profile="fake"))
    persona = Persona.from_resume_fixture("backend-senior", Quality("average"), "Ada Venn")
    config = SessionConfig.model_validate(
        {
            "interview_type": "behavioral",
            "difficulty": "tough",
            "mode": "realistic",
            "duration_min": 30,
            "level": "senior",
        }
    )
    brief = await GapPlanner(gateway).brief(config, persona)
    assert brief.curveball and brief.pushback
    assert brief.probe_areas  # from the gap analysis
    assert sum(p.minutes for p in brief.time_plan) == 30
