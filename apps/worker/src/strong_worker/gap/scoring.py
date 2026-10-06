"""Match score rules (GA-1). The planner model rates; this code turns ratings into numbers.

The model never returns the match score. It rates each requirement and each competency on a
0 to 3 scale. The score is a weighted average of fixed points per rating, so:

- the number is explainable: every requirement and competency shows its own points, and
- the number is stable: a rating can move only in steps, and one step on one requirement moves
  the total by a known, small amount.

Formula:

    points(rating)     = 0, 35, 70 or 100 for ratings 0, 1, 2 and 3
    requirement score  = weighted mean of requirement points (must-have weight 2, nice-to-have 1)
    competency score   = weighted mean of competency points (company profile weights; generic
                         mode uses equal weights)
    match score        = round(0.7 * requirement score + 0.3 * competency score)

A rating of 2 or 3 needs resume evidence. If the evidence is missing, or cannot be found in the
resume, the rating is capped at 1.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from strong_core.schemas import Competency, RequirementKind

POINTS: tuple[int, int, int, int] = (0, 35, 70, 100)
REQUIREMENT_WEIGHTS: dict[RequirementKind, float] = {
    RequirementKind.MUST_HAVE: 2.0,
    RequirementKind.NICE_TO_HAVE: 1.0,
}
REQUIREMENT_SHARE = 0.7
UNVERIFIED_CAP = 1
EVIDENCE_MATCH = 0.6  # share of evidence words that must appear in the resume

_WORD = re.compile(r"[a-z0-9][a-z0-9+#.%]*")


def points(rating: int) -> int:
    return POINTS[max(0, min(3, rating))]


def words(text: str) -> set[str]:
    return {w.rstrip(".") for w in _WORD.findall(text.lower())} - {""}


def evidence_in_resume(evidence: str | None, resume_words: set[str]) -> bool:
    """True when most words of the quoted evidence appear in the resume.

    Small models often shorten a quote, so this checks words, not the exact string.
    """
    if not evidence:
        return False
    found = words(evidence)
    if not found:
        return False
    return len(found & resume_words) / len(found) >= EVIDENCE_MATCH


def checked_rating(rating: int, evidence: str | None, resume_words: set[str]) -> int:
    """The rating after the evidence rule: 2 or 3 needs evidence found in the resume."""
    if rating > UNVERIFIED_CAP and not evidence_in_resume(evidence, resume_words):
        return UNVERIFIED_CAP
    return rating


@dataclass(frozen=True)
class Scored:
    requirement_score: float | None
    competency_score: float | None
    match_score: int


def weighted_mean(pairs: Iterable[tuple[float, float]]) -> float | None:
    """Mean of (value, weight) pairs. None when the weights add up to 0."""
    total = weight = 0.0
    for value, w in pairs:
        total += value * w
        weight += w
    return total / weight if weight > 0 else None


def match_score(
    requirements: Sequence[tuple[RequirementKind, int]],
    competencies: Sequence[tuple[Competency, int]],
    weights: Mapping[Competency, float],
) -> Scored:
    """Combine requirement and competency ratings (after the evidence rule) into GA-1 scores."""
    req = weighted_mean((points(r), REQUIREMENT_WEIGHTS[kind]) for kind, r in requirements)
    comp = weighted_mean((points(r), weights.get(c, 1.0)) for c, r in competencies)
    if req is None and comp is None:
        total = 0.0
    elif req is None:
        total = comp or 0.0
    elif comp is None:
        total = req
    else:
        total = REQUIREMENT_SHARE * req + (1 - REQUIREMENT_SHARE) * comp
    return Scored(req, comp, round(total))
