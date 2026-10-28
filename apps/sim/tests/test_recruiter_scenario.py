"""Recruiter screen eval scenarios (RS-1, RS-2): the text-recruiter suite for the AI candidate."""

from __future__ import annotations

from strong_core.schemas import InterviewType, Mode
from strong_sim.scenarios import load_suite


def test_rs1_recruiter_suite_runs_recruiter_screens() -> None:
    """RS-1: every scenario is a 30-minute recruiter screen, in both modes and every quality."""
    suite = load_suite("text-recruiter")
    for s in suite.scenarios:
        s.check()
        config = s.session_config()
        assert config.interview_type == InterviewType.RECRUITER_SCREEN
        assert config.duration_min == 30
    assert {s.quality.value for s in suite.scenarios} == {"strong", "average", "weak"}
    assert {s.mode for s in suite.scenarios} == set(Mode)
    # The scorer order check needs scenarios that differ only in quality.
    assert len([s for s in suite.scenarios if s.id in {"rs-strong", "rs-average", "rs-weak"}]) == 3
