"""Eval metrics: scorer agreement, follow-up rate, competency coverage, cost per session.

Each function is pure, so the same code can later read real sessions and UsageEvent rows.
"""

from __future__ import annotations

import re
import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from strong_core.db.models import UsageEvent
from strong_core.schemas import (
    Competency,
    HireSignal,
    InterviewerBrief,
    Phase,
    Scorecard,
    Speaker,
    Turn,
)

# --- vague answers (IV-3) -----------------------------------------------------------------------

OWN_ROLE = re.compile(r"\b(I|I'm|I've|I'd|I'll)\b|\b(my|me|myself)\b")
RESULT = re.compile(
    r"\d|percent|\b(half|double|twice|triple|ten|twenty|thirty|forty|fifty|hundred|thousand|"
    r"million|billion)\b",
    re.IGNORECASE,
)
TRADE_OFF = re.compile(
    r"trade-?off|instead|rather than|versus|\bvs\b|option|alternative|downside|\bchose\b|"
    r"\bchoose\b|\bcost\b|\brisk",
    re.IGNORECASE,
)
EXAMPLE_MIN_WORDS = 35
ELEMENTS = ("own_role", "result", "example", "trade_off")


def missing_elements(answer: str) -> list[str]:
    """Which of the four follow-up triggers from the spec an answer lacks, in a fixed order."""
    missing = []
    if not OWN_ROLE.search(answer):
        missing.append("own_role")
    if not RESULT.search(answer):
        missing.append("result")
    if len(answer.split()) < EXAMPLE_MIN_WORDS:
        missing.append("example")
    if not TRADE_OFF.search(answer):
        missing.append("trade_off")
    return missing


def is_vague(answer: str) -> bool:
    """A heuristic: vague when two or more of the four elements are missing."""
    return len(missing_elements(answer)) >= 2


def vague_answer_indexes(turns: Sequence[Turn]) -> list[int]:
    return [
        i
        for i, t in enumerate(turns)
        if t.speaker == Speaker.CANDIDATE and t.phase == Phase.CORE and is_vague(t.text)
    ]


@dataclass(frozen=True)
class FollowUpCount:
    probed: int
    eligible: int


def follow_ups_on_vague(
    turns: Sequence[Turn], vague: Iterable[int], max_probes: int
) -> FollowUpCount:
    """How many vague answers got a follow-up on the same question.

    A vague answer is not eligible when the interviewer already used all probes on that question.
    """
    probed = eligible = 0
    for i in vague:
        ref = turns[i].question_ref
        asks = sum(
            1
            for t in turns[:i]
            if t.speaker == Speaker.INTERVIEWER and t.phase == Phase.CORE and t.question_ref == ref
        )
        if asks - 1 >= max_probes:
            continue
        eligible += 1
        nxt = next((t for t in turns[i + 1 :] if t.speaker == Speaker.INTERVIEWER), None)
        if nxt is not None and nxt.phase == Phase.CORE and nxt.question_ref == ref:
            probed += 1
    return FollowUpCount(probed, eligible)


# --- competency coverage ------------------------------------------------------------------------


def covered_competencies(brief: InterviewerBrief, turns: Sequence[Turn]) -> set[Competency]:
    asked = {
        t.question_ref
        for t in turns
        if t.phase == Phase.CORE and t.speaker == Speaker.INTERVIEWER and t.question_ref
    }
    covered = {c for q in brief.questions if q.id in asked for c in q.competencies}
    return covered & set(brief.target_competencies)


def competency_coverage(brief: InterviewerBrief, turns: Sequence[Turn]) -> float:
    return len(covered_competencies(brief, turns)) / len(brief.target_competencies)


# --- scorer agreement ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Agreement:
    n: int
    exact: int
    within_one: int

    @property
    def exact_rate(self) -> float:
        return self.exact / self.n if self.n else 0.0

    @property
    def within_one_rate(self) -> float:
        return self.within_one / self.n if self.n else 0.0


def signal_agreement(pairs: Iterable[tuple[HireSignal, HireSignal]]) -> Agreement:
    """Pairs of (scorer, human) hire signals. Within one band means ranks differ by 0 or 1."""
    n = exact = within = 0
    for scorer, human in pairs:
        n += 1
        gap = abs(scorer.rank - human.rank)
        exact += gap == 0
        within += gap <= 1
    return Agreement(n, exact, within)


def rubric_pairs(
    card: Scorecard, human: dict[tuple[str, Competency], int]
) -> list[tuple[int, int]]:
    """(scorer, human) pairs for each question and competency both of them scored."""
    scorer = {(q.question_ref, s.competency): s.score for q in card.per_question for s in q.scores}
    return [(scorer[k], v) for k, v in sorted(human.items()) if k in scorer]


def value_pairs(card: Scorecard, human: dict[tuple[str, str], int]) -> list[tuple[int, int]]:
    """(scorer, human) pairs for each question and company value both of them scored."""
    scorer = {(q.question_ref, v.value): v.score for q in card.per_question for v in q.value_scores}
    return [(scorer[k], v) for k, v in sorted(human.items()) if k in scorer]


def score_agreement(pairs: Iterable[tuple[int, int]]) -> Agreement:
    n = exact = within = 0
    for a, b in pairs:
        n += 1
        exact += a == b
        within += abs(a - b) <= 1
    return Agreement(n, exact, within)


# --- cost ---------------------------------------------------------------------------------------


def cost_per_session(events: Iterable[UsageEvent]) -> dict[uuid.UUID, Decimal]:
    totals: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for e in events:
        if e.session_id is not None:
            totals[e.session_id] += Decimal(e.cost_usd)
    return dict(totals)


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0
