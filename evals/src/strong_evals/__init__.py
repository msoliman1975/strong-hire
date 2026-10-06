"""Strong Hire eval harness (P5).

Scripted transcripts, a simulated candidate, gold-set labels and metrics that tell us whether the
interviewer and the scorer are any good. Every model call goes through strong_core.gateway.
"""

from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[2]
"""The evals/ folder: transcripts/, goldset/, suites/, config/, reports/."""
