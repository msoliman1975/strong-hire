"""Helpers for tests: a brief built in code and a clock the test moves by hand."""

from __future__ import annotations

from dataclasses import dataclass

from strong_core.schemas import (
    BriefQuestion,
    Competency,
    Difficulty,
    InterviewerBrief,
    InterviewType,
    Level,
    Mode,
    PersonaBrief,
    SessionConfig,
)

COMPETENCIES = [
    Competency.OWNERSHIP,
    Competency.IMPACT,
    Competency.COLLABORATION,
    Competency.COMMUNICATION,
]


def make_brief(
    *,
    difficulty: Difficulty = Difficulty.REALISTIC,
    mode: Mode = Mode.REALISTIC,
    duration: int = 30,
    questions: int = 6,
    max_probes: int = 3,
) -> InterviewerBrief:
    tough = difficulty == Difficulty.TOUGH
    return InterviewerBrief(
        session=SessionConfig(
            interview_type=InterviewType.BEHAVIORAL,
            difficulty=difficulty,
            mode=mode,
            duration_min=duration,
            level=Level.SENIOR,
        ),
        generic_mode=True,
        target_competencies=COMPETENCIES,
        questions=[
            BriefQuestion(
                id=f"q{i}",
                text=f"Question {i}?",
                competencies=[COMPETENCIES[i % 4]],
                priority=i,
            )
            for i in range(1, questions + 1)
        ],
        persona=PersonaBrief(tone="warm", pushback_style="polite", closing_style="brief"),
        max_probes_per_question=max_probes,
        curveball="What would you do if the budget were cut in half?" if tough else None,
        pushback=tough,
        coach_help=mode == Mode.COACH,
    )


@dataclass
class FakeClock:
    """Milliseconds the test moves by hand."""

    now_ms: int = 0

    def __call__(self) -> int:
        return self.now_ms

    def advance(self, minutes: float = 0, ms: int = 0) -> None:
        self.now_ms += int(minutes * 60 * 1000) + ms
