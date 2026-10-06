"""Scorer, hire signal and progress snapshots (FB-1 to FB-3, PR-1). Owned by P8."""

from strong_worker.scoring.scorer import ScoringError, ScoringOutcome, SessionScorer
from strong_worker.scoring.signal import SignalResult, compute_hire_signal

__all__ = [
    "ScoringError",
    "ScoringOutcome",
    "SessionScorer",
    "SignalResult",
    "compute_hire_signal",
]
