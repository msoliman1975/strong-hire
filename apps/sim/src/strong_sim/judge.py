"""The judge: a model (role `judge`) that checks the interviewer in one finished transcript.

The rubric is prompts/judge/transcript.v<N>.txt; its ref is stored with each verdict.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.gateway import ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_interview.controller import PROBE_LIMIT
from strong_sim.cost import CostMeter
from strong_sim.scenarios import Scenario
from strong_sim.transcript import Line, for_judge

RULES = (
    "probe_limit",
    "phases",
    "tone",
    "no_coaching",
    "injection",
    "behavior_handling",
    "no_repetition",
    "stays_in_role",
)

Verdict = Literal["pass", "fail", "not_applicable"]


class RuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str = Field(description="One of: " + ", ".join(RULES))
    verdict: Verdict
    reason: str = Field(description="Short; quote or point to the turn time.")


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str = Field(description="Turn time, mm:ss.")
    problem: str


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[RuleResult] = Field(description="One entry per rule, in the order given.")
    problems: list[Problem] = Field(default_factory=list, max_length=5)


class JudgeResult(BaseModel):
    rubric: str
    model: str
    rules: list[RuleResult]
    problems: list[Problem]

    @property
    def failed(self) -> list[str]:
        return [r.rule for r in self.rules if r.verdict == "fail"]

    @property
    def passed(self) -> bool:
        return not self.failed


async def judge(
    scenario: Scenario,
    lines: list[Line],
    gateway: ModelGateway,
    meter: CostMeter,
    *,
    stopped_early: bool = False,
) -> JudgeResult:
    prompt = load_prompt("judge", "transcript")
    behavior = scenario.behavior.value.replace("_", " ")
    if stopped_early:
        behavior += " (the harness stopped this session early)"
    message = prompt.message(
        "user",
        interview_type=scenario.interview_type.value.replace("_", " "),
        difficulty=scenario.difficulty.value,
        mode=scenario.mode.value,
        duration_min=scenario.duration_min,
        max_probes=PROBE_LIMIT[scenario.difficulty],
        channel=scenario.channel,
        behavior=behavior,
        quality=scenario.quality.value,
        brief="(not available to the test harness)",
        transcript=for_judge(lines),
    )
    done = await gateway.complete(Role.JUDGE, [message], output_type=JudgeVerdict)
    meter.add(done)
    verdict = done.output
    by_rule = {r.rule: r for r in verdict.rules}
    rules = [
        by_rule.get(name)
        or RuleResult(rule=name, verdict="not_applicable", reason="The judge gave no verdict.")
        for name in RULES
    ]
    return JudgeResult(rubric=prompt.ref, model=done.model, rules=rules, problems=verdict.problems)
