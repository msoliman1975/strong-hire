"""SG-7: the no-new-facts eval covers tune a story, new story, improve a resume line and review.
On the fake profile, replies from the user's words are kept and replies that add a fact are
rejected; a fact that gets through fails the metric."""

from __future__ import annotations

from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_evals.runner import run_suite
from strong_evals.suggestions import invented_facts, load_cases, run_case
from strong_evals.suites import load_suite


async def test_sg7_suite_passes_on_good_fixtures_and_rejects_fact_adding_ones() -> None:
    report = await run_suite(load_suite("suggestions"), "fake")
    assert report.errors == 0
    assert {r.case.kind for r in report.suggestions} == {
        "tune_story",
        "new_story",
        "improve_resume_line",
        "review",
    }
    for r in report.suggestions:
        assert r.outcome == r.case.expect, r.case.id
    assert {r.case.expect for r in report.suggestions} == {"kept", "rejected"}
    (metric,) = [m for m in report.metrics if m.key == "suggestions_invented_facts"]
    assert metric.passed is True


async def test_sg7_a_fact_adding_reply_that_got_through_fails_the_metric() -> None:
    """The check is what stands between the model and the user: expecting a fact-adding reply
    to be kept is counted as an invented fact."""
    gateway = ModelGateway(fake_models_config())
    cases = load_cases()
    bad = cases["tune-adds-a-number"]
    result = await run_case(bad.model_copy(update={"expect": "kept"}), gateway)
    assert result.outcome == "rejected"
    assert invented_facts([result], fake=True) == 1
    good = await run_case(cases["tune-result-number"], gateway)
    assert good.outcome == "kept" and good.unbacked == []
    assert invented_facts([good], fake=True) == 0


def test_sg7_full_suite_includes_the_suggestion_cases() -> None:
    assert load_suite("full").suggestions == "all"
