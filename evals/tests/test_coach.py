"""Coach evals (CO-9): the suite runs on the fake model, the code checks catch invented facts,
and off the fake profile the judge runs (here on a scripted function model, never a real one)."""

from __future__ import annotations

import json

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from strong_api.coach.schemas import AskFor
from strong_core.config import find_repo_root
from strong_core.gateway import ModelGateway, load_models_config
from strong_core.schemas import AnswerConduct, CoachStyle, StoryPart, StoryVersions
from strong_evals.coach import (
    CoachRun,
    CoachStep,
    load_candidates,
    low_overlap_parts,
    one_question_count,
    unbacked_updates,
    untraced_numbers,
    versions_unbacked,
)
from strong_evals.coach_judge import RULES
from strong_evals.runner import run_suite
from strong_evals.suites import CoachSpec, Suite, load_suite

REPO = find_repo_root()
STRONG_FIRST = "we were moving checkout to the new payments provider"


def _run(candidate_turns: list[str], story: dict[str, str | None], kept: list[dict]) -> CoachRun:  # type: ignore[type-arg]
    spec = load_candidates()["strong"]
    steps = [
        CoachStep(t, "What did you do yourself?", AskFor.OWN_ROLE, AnswerConduct.OK)
        for t in candidate_turns
    ]
    steps[-1].kept = kept
    parts = {p.value: story.get(p.value) for p in StoryPart}
    return CoachRun(spec, CoachStyle.GENTLE, "Let's build one story.", steps, parts, ended=False)


def test_co9_candidates_cover_the_four_kinds() -> None:
    kinds = {c.kind.value for c in load_candidates().values()}
    assert kinds == {"vague", "overclaim", "off_topic", "strong"}
    suite = load_suite("coach")
    assert {(c.candidate, c.style) for c in suite.coach} == {
        (k, s) for k in load_candidates() for s in CoachStyle
    }
    assert {c.id for c in load_suite("full").coach} == {c.id for c in suite.coach}


async def test_co9_coach_suite_runs_on_fake() -> None:
    """The CI suite: structure only. Code checks gate; judge metrics are not measured."""
    report = await run_suite(load_suite("coach"), "fake")
    assert report.errors == 0
    metrics = {m.key: m for m in report.metrics}
    assert metrics["coach_invented_facts"].passed is True
    assert metrics["coach_invented_facts"].threshold == "<= 0"
    assert metrics["coach_one_question"].passed is True
    for key in ("coach_iv3_followup", "coach_judge_pass", "coach_style_distinct"):
        assert metrics[key].value is None, key
    strong = next(c for c in report.coach if c.spec.id == "coach-strong-gentle")
    assert strong.run is not None and strong.run.story["context"]  # the kept-update path ran
    vague = next(c for c in report.coach if c.spec.id == "coach-vague-gentle")
    assert vague.run is not None and not any(vague.run.story.values())  # nothing to back it
    assert all(s.dropped for s in vague.run.steps)  # the engine dropped the fixture's parts
    assert not vague.run.versions_asked  # no versions of an empty story
    assert strong.run.versions is not None and strong.versions_unbacked == []
    assert metrics["coach_versions_faithful"].passed is True


def test_co9_unbacked_update_and_untraced_number_are_counted() -> None:
    kept = [
        {"part": "result", "text": "Sales went up 40%.", "quotes": ["sales went up a lot"]},
        {"part": "context", "text": "They moved checkout.", "quotes": [STRONG_FIRST]},
    ]
    run = _run(
        [f"Last year {STRONG_FIRST}.", "Sales went up a lot after that."],
        {"context": "They moved checkout.", "result": "Sales went up 40%."},
        kept,
    )
    assert unbacked_updates(run) == ["turn 2, result: number not in the quotes: 40"]
    assert untraced_numbers(run) == ["result: 40"]


def test_co9_backed_story_passes_the_code_checks() -> None:
    kept = [
        {"part": "context", "text": "Moving checkout to a new provider.", "quotes": [STRONG_FIRST]}
    ]
    run = _run([f"So {STRONG_FIRST}, two weeks late."], {"context": "Moving checkout."}, kept)
    assert unbacked_updates(run) == []
    assert untraced_numbers(run) == []
    assert one_question_count(run) == (1, 1)


def test_co9_low_overlap_flags_added_content() -> None:
    run = _run(
        ["Black Friday was a month out and checkout could not break."],
        {"stakes": "A broken checkout would have cost real sales and hurt the brand badly."},
        [],
    )
    assert low_overlap_parts(run) and low_overlap_parts(run)[0].startswith("stakes")


def test_co9_versions_must_quote_the_candidate() -> None:
    """CO-8, CO-9: versions are checked against the candidate's turns, not the coach's parts."""
    quote = "we moved traffic in five percent steps"
    good = {"text": "We moved traffic in five percent steps.", "quotes": [quote]}
    bad = {"text": "We moved traffic in 7% steps.", "quotes": [quote]}
    run = _run([f"Then {quote} and not one payment failed."], {"action": "Moved traffic."}, [])
    run.versions = StoryVersions.model_validate({"sixty_second": good, "full": good})
    assert versions_unbacked(run) == []
    run.versions = StoryVersions.model_validate({"sixty_second": bad, "full": good})
    assert versions_unbacked(run) == ["sixty_second: number not in the quotes: 7"]


# --- off the fake profile: a scripted function model stands in for the hosted one -----------


def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    text = str(messages)
    if "You review a practice session" in text:
        rules = [{"rule": r, "verdict": "pass", "reason": "ok"} for r in RULES]
        out: dict[str, object] = {"rules": rules}
    elif "Which session used the direct style" in text:
        out = {"direct": "A", "reason": "A is shorter"}
    elif "You check one candidate turn" in text:
        out = {"conduct": "ok", "reason": ""}
    elif "You write two versions" in text:
        version = {
            "text": "We were moving checkout to the new payments provider.",
            "quotes": [STRONG_FIRST],
        }
        out = {"sixty_second": version, "full": version}
    elif "You are a story coach" in text:
        out = {
            "message": "What did you do yourself? And what changed?",
            "parts": [{"part": "context", "text": "Moving checkout.", "quotes": [STRONG_FIRST]}]
            if STRONG_FIRST in text.lower()
            else [],
        }
    else:  # the candidate role
        return ModelResponse(parts=[TextPart(f"Last year {STRONG_FIRST} and it was late.")])
    if info.output_tools:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(out))])
    return ModelResponse(parts=[TextPart(json.dumps(out))])  # json_mode aliases


async def test_co9_judge_runs_off_the_fake_profile() -> None:
    config = load_models_config(REPO / "config", "hosted")
    gateway = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(_model))
    suite = Suite(
        name="coach-tiny",
        description="two styles of one candidate",
        coach=[
            CoachSpec(
                id="t-strong-gentle", candidate="strong", style=CoachStyle.GENTLE, max_turns=2
            ),
            CoachSpec(
                id="t-strong-direct", candidate="strong", style=CoachStyle.DIRECT, max_turns=2
            ),
        ],
    )
    report = await run_suite(suite, "hosted", gateway=gateway)
    assert report.errors == 0
    run = report.coach[0].run
    assert run is not None
    assert all(s.coach.count("?") == 1 for s in run.steps)  # CO-4: the engine cut the second
    assert run.story["context"] == "Moving checkout."
    metrics = {m.key: m for m in report.metrics}
    assert metrics["coach_invented_facts"].passed is True
    assert metrics["coach_iv3_followup"].value == 1.0
    assert metrics["coach_judge_pass"].passed is True
    assert metrics["coach_style_distinct"].value is not None
    assert metrics["coach_versions_faithful"].value == 1.0
    assert len(report.style_picks) == 1
    assert any(r.startswith("evals/coach_judge") for r in report.prompt_refs)
