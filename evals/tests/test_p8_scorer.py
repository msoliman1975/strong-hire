"""The P8 scorer behind the harness (FB-1, FB-2, FB-3, spec Calibration)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from statistics import mean
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from strong_core.config import find_repo_root
from strong_core.gateway import ModelGateway, load_models_config
from strong_evals.goldset import load_goldset
from strong_evals.runner import resolve_scorer, run_suite
from strong_evals.suites import Suite, load_suite
from strong_evals.transcripts import load_transcripts
from strong_worker.scoring.harness import find_profile
from strong_worker.scoring.signal import compute_hire_signal
from strong_worker.scoring.testing import RATIONALE

REPO = find_repo_root()
_QUESTION = re.compile(r"^(?P<ref>[a-z0-9_-]+): .*\[(?P<comps>[^\]]*)\] \{(?P<vals>[^}]*)\}$")
_ANSWER = re.compile(r"^Candidate \[(?P<ref>[a-z0-9_-]+)\]: (?P<text>.+)$")


def test_fb1_signal_rule_matches_the_goldset_signals() -> None:
    """The hire-signal code, fed the gold-set rubric scores, reproduces the gold-set signals."""
    gold = load_goldset()
    transcripts = {t.id: t for t in load_transcripts()}
    exact = within = 0
    for tid, label in gold.items():
        comps: dict[Any, list[int]] = defaultdict(list)
        values: dict[str, list[int]] = defaultdict(list)
        for (_, c), s in label.scores.items():
            comps[c].append(s)
        for (_, v), s in label.value_scores.items():
            values[v].append(s)
        result = compute_hire_signal(
            {c: mean(s) for c, s in comps.items()},
            find_profile(transcripts[tid].brief),
            {v: mean(s) for v, s in values.items()},
        )
        gap = abs(result.signal.rank - label.hire_signal.rank)
        exact += gap == 0
        within += gap <= 1
    assert len(gold) == 30
    assert within == 30
    assert exact >= 26


def _user_text(messages: list[ModelMessage]) -> str:
    parts = [
        p.content
        for m in messages
        for p in getattr(m, "parts", [])
        if isinstance(p, UserPromptPart) and isinstance(p.content, str)
    ]
    return parts[-1]


def _quoting_reply(prompt: str) -> dict[str, Any]:
    """A scorecard that scores 3 everywhere and quotes the first answer to each question."""
    answers: dict[str, str] = {}
    questions: list[tuple[str, list[str], list[str]]] = []
    for line in prompt.splitlines():
        if m := _ANSWER.match(line):
            answers.setdefault(m["ref"], m["text"])
        elif m := _QUESTION.match(line):
            split = [x.strip() for x in m["comps"].split(",") if x.strip()]
            vals = [x.strip() for x in m["vals"].split(",") if x.strip()]
            questions.append((m["ref"], split, vals))
    per_question = []
    for ref, comps, vals in questions:
        quote = " ".join(answers[ref].split()[:6])
        per_question.append(
            {
                "question_ref": ref,
                "question_text": ref,
                "scores": [
                    {"competency": c, "score": 3, "justification": "ok", "quotes": [quote]}
                    for c in comps
                ],
                "value_scores": [
                    {"value": v, "score": 3, "justification": "ok", "quotes": [quote]} for v in vals
                ],
                "strengths": ["Specific"],
                "misses": ["No trade-off"],
            }
        )
    return {
        "hire_signal": "Hire",
        "rationale": "Pending.",
        "competency_scores": [s for q in per_question for s in q["scores"]][:1],
        "value_scores": [],
        "per_question": per_question,
        "scorer_model": "pending",
        "rubric_version": "pending",
    }


def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if info.output_tools:
        reply = _quoting_reply(_user_text(messages))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(reply))])
    return ModelResponse(parts=[TextPart(RATIONALE)])


def test_auto_scorer_choice() -> None:
    assert resolve_scorer("auto", "fake") == "stub"
    assert resolve_scorer("auto", "local") == "p8"
    assert resolve_scorer("p8", "fake") == "p8"


async def test_goldset_suite_runs_the_p8_scorer() -> None:
    """Agreement, value agreement and the FB-3 timing are reported for the real scorer."""
    config = load_models_config(REPO / "config", "local")
    gw = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(_model))
    report = await run_suite(load_suite("goldset"), "local", gateway=gw)
    assert report.scorer == "p8"
    assert report.errors == 0
    keys = {m.key: m for m in report.metrics}
    assert keys["scorer_within_one_band"].value is not None
    assert "2 company-mode transcripts" in keys["value_within_one_point"].detail
    assert keys["debrief_ready_s"].passed is True
    assert "scorer/rubric.v1" in report.prompt_refs
    assert "scorer/rationale.v1" in report.prompt_refs


async def test_single_transcript_with_p8_scorer_in_company_mode() -> None:
    config = load_models_config(REPO / "config", "local")
    gw = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(_model))
    suite = Suite(name="one", description="company mode", scripted=["beh-03"])
    report = await run_suite(suite, "local", gateway=gw, scorer="p8")
    [result] = report.scripted
    assert result.error is None
    assert result.values.n > 0  # value scores were compared with the gold set
