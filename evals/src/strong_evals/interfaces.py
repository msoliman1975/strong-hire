"""The interfaces the harness drives. P7 (interviewer) and P8 (scorer) plug in real versions.

Until then, strong_evals.stubs provides stubs behind the same interfaces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from strong_core.schemas import (
    BriefQuestion,
    InterviewerBrief,
    Phase,
    Scorecard,
    SessionConfig,
    Turn,
)

if TYPE_CHECKING:
    from strong_evals.candidate import Persona


@dataclass
class InterviewState:
    """What the interviewer sees before it speaks. The session controller owns the phase."""

    brief: InterviewerBrief
    phase: Phase
    turns: list[Turn] = field(default_factory=list)
    question: BriefQuestion | None = None
    probes_used: int = 0


class Interviewer(Protocol):
    async def speak(self, state: InterviewState) -> str:
        """The next interviewer line for state.phase (in CORE: ask state.question)."""
        ...

    async def follow_up(self, state: InterviewState) -> str | None:
        """A probe on state.question after the last answer, or None to move on (IV-3)."""
        ...


class Planner(Protocol):
    async def brief(self, config: SessionConfig, persona: Persona) -> InterviewerBrief: ...


class Scorer(Protocol):
    async def score(self, brief: InterviewerBrief, turns: Sequence[Turn]) -> Scorecard: ...
