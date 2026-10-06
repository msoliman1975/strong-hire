"""Metric functions (IV-3 follow-ups, coverage, scorer agreement, cost per session)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from strong_core.gateway import TokenUsage
from strong_core.schemas import HireSignal, Phase, Speaker, Turn, UsageComponent
from strong_evals.metrics import (
    competency_coverage,
    cost_per_session,
    follow_ups_on_vague,
    is_vague,
    missing_elements,
    signal_agreement,
)
from strong_evals.transcripts import load_transcripts
from strong_evals.usage import load_prices, usage_event

STRONG = (
    "I led the payout rebuild at my last job. I chose a queue instead of cron because retries "
    "were the real problem, which cost us two extra weeks. I wrote the design, split the work "
    "across three engineers, and failed payouts dropped 38 percent in two months."
)


def test_vague_detector() -> None:
    """IV-3: own role, measurable result, concrete example, trade-off reasoning."""
    assert missing_elements(STRONG) == []
    assert not is_vague(STRONG)
    assert is_vague("We usually just work together and it goes fine.")
    assert set(missing_elements("We usually just work together.")) == {
        "own_role",
        "result",
        "example",
        "trade_off",
    }


def _turn(speaker: Speaker, phase: Phase, ref: str | None, i: int) -> Turn:
    return Turn(
        speaker=speaker, phase=phase, text="x", start_ms=i * 10, end_ms=i * 10 + 5, question_ref=ref
    )


def test_follow_up_counting_respects_the_probe_cap() -> None:
    """IV-3: a vague answer counts only while probes are left; a probe is the same question."""
    i, c, core = Speaker.INTERVIEWER, Speaker.CANDIDATE, Phase.CORE
    turns = [
        _turn(i, core, "q1", 0),
        _turn(c, core, "q1", 1),  # vague, probed
        _turn(i, core, "q1", 2),
        _turn(c, core, "q1", 3),  # vague, but the cap of 1 probe is used
        _turn(i, core, "q2", 4),
        _turn(c, core, "q2", 5),  # vague, not probed
        _turn(i, Phase.WRAP_UP, None, 6),
    ]
    count = follow_ups_on_vague(turns, [1, 3, 5], max_probes=1)
    assert (count.probed, count.eligible) == (1, 2)


def test_coverage_on_a_scripted_transcript() -> None:
    [t] = load_transcripts(["beh-01"])
    # q1 to q3 are asked: ownership, impact, collaboration, communication, learning_from_failure.
    assert competency_coverage(t.brief, t.turns) == 1.0
    assert competency_coverage(t.brief, t.turns[:8]) == 2 / 5


def test_signal_agreement_within_one_band() -> None:
    """Spec, Calibration: within one band means the ranks differ by at most one."""
    a = signal_agreement(
        [
            (HireSignal.HIRE, HireSignal.HIRE),
            (HireSignal.HIRE, HireSignal.LEAN_HIRE),
            (HireSignal.STRONG_HIRE, HireSignal.LEAN_HIRE),
            (HireSignal.NO_HIRE, HireSignal.LEAN_NO_HIRE),
        ]
    )
    assert (a.n, a.exact, a.within_one) == (4, 1, 3)
    assert a.within_one_rate == 0.75


def test_cost_per_session_sums_usage_events() -> None:
    """Spec, Metrics: cost per session is the sum of its UsageEvents."""
    prices = load_prices()
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    llm = prices.llm("hosted-scorer", TokenUsage(1_000_000, 0))
    events = [
        usage_event(s1, UsageComponent.LLM, Decimal(1_000_000), llm),
        usage_event(s1, UsageComponent.STT, Decimal(10), prices.stt("hosted-stt", Decimal(10))),
        usage_event(s2, UsageComponent.LLM, Decimal(5), Decimal(0)),
    ]
    totals = cost_per_session(events)
    assert totals[s1] == Decimal("0.907")
    assert totals[s2] == 0
    assert prices.llm("local-mid", TokenUsage(10**6, 10**6)) == 0
