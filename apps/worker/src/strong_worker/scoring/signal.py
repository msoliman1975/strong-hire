"""Hire signal, computed in code from rubric scores (FB-1). The model never picks the signal.

Spec, 'Hire signal': competency averages weighted by the company profile, plus two hard rules:
- any competency at 1 caps the result at Lean No Hire;
- Strong Hire needs an average of 3.5 or more and no competency below 3.

Company values (IV-5): in company mode, `CompanyProfile.values_share` of the average comes from
the value scores (each value weighted by `Principle.weight`), the rest from the competencies.
Generic mode has no values, so the competencies give the whole average. The hard rules look at
competencies only, as the spec says.

A competency's score is the mean of its per-question scores. The rules use that mean rounded
half up to a whole rubric point, which is the number the candidate sees on the debrief.

Band floors for the weighted average. 3.5 for Strong Hire is from the spec. The other floors are
ours: they reproduce 26 of the 30 gold-set signals exactly and all 30 within one band, when the
signal is computed from the gold-set rubric scores (test_signal_matches_goldset).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from strong_core.profiles import ResolvedProfile
from strong_core.schemas import Competency, HireSignal

STRONG_HIRE_MIN = 3.5
HIRE_MIN = 3.0
LEAN_HIRE_MIN = 2.6
LEAN_NO_HIRE_MIN = 2.0

RULE_CAP_AT_ONE = "A competency scored 1, so the signal is capped at Lean No Hire."
RULE_STRONG_NEEDS_THREE = "Strong Hire needs every competency at 3 or more, so the signal is Hire."


def rubric_point(average: float) -> int:
    """Mean of rubric scores to a whole point, half up: 2.5 -> 3, 2.49 -> 2."""
    return max(1, min(4, math.floor(average + 0.5)))


def band_for(average: float) -> HireSignal:
    if average >= STRONG_HIRE_MIN:
        return HireSignal.STRONG_HIRE
    if average >= HIRE_MIN:
        return HireSignal.HIRE
    if average >= LEAN_HIRE_MIN:
        return HireSignal.LEAN_HIRE
    if average >= LEAN_NO_HIRE_MIN:
        return HireSignal.LEAN_NO_HIRE
    return HireSignal.NO_HIRE


def _weighted(averages: Mapping[str, float], weights: Mapping[str, float]) -> float:
    total = sum(weights.get(k, 1.0) for k in averages)
    return sum(avg * weights.get(k, 1.0) for k, avg in averages.items()) / total


@dataclass(frozen=True)
class SignalResult:
    signal: HireSignal
    average: float
    """The weighted average the band comes from, 1 to 4."""
    competency_average: float
    value_average: float | None
    values_share: float
    """The share of `average` that came from value scores. 0 in generic mode."""
    band: HireSignal
    """The band from the average alone, before the hard rules."""
    rules: list[str] = field(default_factory=list)


def compute_hire_signal(
    competency_averages: Mapping[Competency, float],
    profile: ResolvedProfile,
    value_averages: Mapping[str, float] | None = None,
) -> SignalResult:
    if not competency_averages:
        raise ValueError("the hire signal needs at least one competency score")
    weights = {c.value: profile.weight(c) for c in competency_averages}
    comp_avg = _weighted({c.value: a for c, a in competency_averages.items()}, weights)

    value_weights = profile.value_weights
    values = {v: a for v, a in (value_averages or {}).items() if v in value_weights}
    share = profile.values_share if values else 0.0
    value_avg = _weighted(values, value_weights) if values else None
    average = comp_avg if value_avg is None else (1 - share) * comp_avg + share * value_avg

    band = band_for(average)
    signal = band
    rules: list[str] = []
    points = [rubric_point(a) for a in competency_averages.values()]
    if signal == HireSignal.STRONG_HIRE and min(points) < 3:
        signal = HireSignal.HIRE
        rules.append(RULE_STRONG_NEEDS_THREE)
    if min(points) == 1 and signal.rank < HireSignal.LEAN_NO_HIRE.rank:
        signal = HireSignal.LEAN_NO_HIRE
        rules.append(RULE_CAP_AT_ONE)
    return SignalResult(
        signal=signal,
        average=round(average, 3),
        competency_average=round(comp_avg, 3),
        value_average=None if value_avg is None else round(value_avg, 3),
        values_share=share,
        band=band,
        rules=rules,
    )
