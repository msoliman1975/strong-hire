"""The coach judge: the judge role checks what code cannot (CO-9, CO-4, CO-5).

Per session (`prompts/evals/coach_judge`): invented facts, writing the story for the candidate,
IV-3 follow-ups, style, staying on the story, checking big claims. Per pair of sessions with the
same candidate in both styles (`prompts/evals/coach_judge_style`): which one is direct.

The fake profile has no judge fixtures; the runner skips the judge there (structure only).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from strong_core.gateway import ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import CoachStyle, Contract
from strong_evals.coach import CandidateKind, CoachRun, render_story, render_transcript

PROMPT_ROLE = "evals"
RULES = (
    "invented_facts",
    "wrote_for_candidate",
    "iv3_followup",
    "style",
    "stays_on_story",
    "checks_claims",
)
Verdict = Literal["pass", "fail", "not_applicable"]
_KIND_LINE = {
    CandidateKind.VAGUE: "vague: general terms, no numbers, one fact at a time when pressed",
    CandidateKind.OVERCLAIM: "overclaims: says they did everything, then gives the real facts",
    CandidateKind.OFF_TOPIC: "drifts off topic: asks unrelated questions on some turns",
    CandidateKind.STRONG: "clear: answers each question with real facts and numbers",
}


class CoachRuleResult(Contract):
    rule: str = Field(description="One of: " + ", ".join(RULES))
    verdict: Verdict
    reason: str = Field(description="Short; quote or point to the turn number.")


class CoachJudgeVerdict(Contract):
    rules: list[CoachRuleResult] = Field(description="One entry per rule, in the order given.")


class StyleVerdict(Contract):
    direct: Literal["A", "B", "same"]
    reason: str


@dataclass
class CoachJudgeResult:
    rubric: str
    rules: list[CoachRuleResult]

    def verdict(self, rule: str) -> Verdict | None:
        return next((r.verdict for r in self.rules if r.rule == rule), None)

    @property
    def failed(self) -> list[str]:
        return [r.rule for r in self.rules if r.verdict == "fail"]


@dataclass
class StylePick:
    rubric: str
    direct_was: Literal["A", "B"]
    picked: Literal["A", "B", "same"]
    reason: str

    @property
    def correct(self) -> bool:
        return self.picked == self.direct_was


def _style_guide(style: CoachStyle) -> str:
    return load_prompt("coach", f"style_{style.value}").render()


async def judge_session(run: CoachRun, gateway: ModelGateway) -> CoachJudgeResult:
    prompt = load_prompt(PROMPT_ROLE, "coach_judge")
    message = prompt.message(
        "user",
        style=run.style.value,
        style_guide=_style_guide(run.style),
        kind=_KIND_LINE[run.candidate.kind],
        transcript=render_transcript(run, asked_for=True),
        story=render_story(run),
    )
    done = await gateway.complete(Role.JUDGE, [message], output_type=CoachJudgeVerdict)
    by_rule = {r.rule: r for r in done.output.rules}
    rules = [
        by_rule.get(name)
        or CoachRuleResult(rule=name, verdict="fail", reason="the judge gave no verdict")
        for name in RULES
    ]
    return CoachJudgeResult(rubric=prompt.ref, rules=rules)


def _direct_slot(candidate_id: str) -> Literal["A", "B"]:
    """Put the direct session first for about half the candidates, the same way every run."""
    return "A" if hashlib.sha256(candidate_id.encode()).digest()[0] % 2 else "B"


async def judge_styles(gentle: CoachRun, direct: CoachRun, gateway: ModelGateway) -> StylePick:
    """CO-5: can the judge tell the direct coach from the gentle one on the same candidate?"""
    prompt = load_prompt(PROMPT_ROLE, "coach_judge_style")
    slot = _direct_slot(gentle.candidate.id)
    a, b = (direct, gentle) if slot == "A" else (gentle, direct)
    message = prompt.message(
        "user",
        gentle_guide=_style_guide(CoachStyle.GENTLE),
        direct_guide=_style_guide(CoachStyle.DIRECT),
        a=render_transcript(a),
        b=render_transcript(b),
    )
    done = await gateway.complete(Role.JUDGE, [message], output_type=StyleVerdict)
    return StylePick(prompt.ref, slot, done.output.direct, done.output.reason)
