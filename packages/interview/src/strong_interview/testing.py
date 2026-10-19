"""Helpers for tests: briefs built in code and a clock the test moves by hand."""

from __future__ import annotations

from dataclasses import dataclass

from strong_core.schemas import (
    MINI_DURATION_MIN,
    MINI_MAX_PROBES,
    BriefQuestion,
    Competency,
    CustomCategory,
    CustomQuestion,
    CustomSessionSpec,
    Difficulty,
    InterviewerBrief,
    InterviewType,
    Level,
    Mode,
    PersonaBrief,
    QuestionSource,
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
    mini = duration == MINI_DURATION_MIN  # no curveball, at most 1 probe (as brief.py builds it)
    curveball = "What would you do if the budget were cut in half?"
    return InterviewerBrief(
        session=SessionConfig(
            interview_type=InterviewType.BEHAVIORAL,
            difficulty=difficulty,
            mode=mode,
            duration_min=duration,
            level=Level.SENIOR,
        ),
        generic_mode=True,
        target_competencies=COMPETENCIES[:2] if mini else COMPETENCIES,
        questions=[
            BriefQuestion(
                id=f"q{i}",
                text=f"Question {i}?",
                competencies=[COMPETENCIES[i % 2 if mini else i % 4]],
                priority=i,
            )
            for i in range(1, questions + 1)
        ],
        persona=PersonaBrief(tone="warm", pushback_style="polite", closing_style="brief"),
        max_probes_per_question=min(max_probes, MINI_MAX_PROBES) if mini else max_probes,
        curveball=curveball if tough and not mini else None,
        pushback=tough,
        coach_help=mode == Mode.COACH,
    )


# A Custom session (CU-1): Technical, then Behavioral, then Hiring manager. Priorities mix the
# categories on purpose, so priority order alone would not give the category order.
TECH = InterviewType.TECHNICAL_QA
BEHAVIORAL = InterviewType.BEHAVIORAL
MANAGER = InterviewType.HIRING_MANAGER
CUSTOM_CATEGORIES = (TECH, BEHAVIORAL, MANAGER)
# id, category, competency, source, must_ask, verbatim, priority, text
_CUSTOM_QUESTIONS: tuple[
    tuple[str, InterviewType, Competency, QuestionSource, bool, bool, int, str], ...
] = (
    (
        "own1",
        TECH,
        Competency.TRADE_OFFS,
        QuestionSource.CANDIDATE,
        True,
        True,
        1,
        "How would you shard a Postgres table that has outgrown a single node?",
    ),
    (
        "p_beh1",
        BEHAVIORAL,
        Competency.OWNERSHIP,
        QuestionSource.PLANNER,
        False,
        False,
        2,
        "Tell me about a project you owned end to end.",
    ),
    (
        "own2",
        BEHAVIORAL,
        Competency.CONFLICT_HANDLING,
        QuestionSource.CANDIDATE,
        True,
        False,
        3,
        "Tell me about a time you disagreed with your manager.",
    ),
    (
        "p_tech1",
        TECH,
        Competency.TECHNICAL_DEPTH,
        QuestionSource.PLANNER,
        False,
        False,
        4,
        "How does a database index speed up reads?",
    ),
    (
        "p_hm1",
        MANAGER,
        Competency.MOTIVATION,
        QuestionSource.PLANNER,
        False,
        False,
        5,
        "Why this role, and why now?",
    ),
    (
        "own3",
        MANAGER,
        Competency.SCOPE_AT_LEVEL,
        QuestionSource.CANDIDATE,
        True,
        False,
        6,
        "What is the largest scope you have owned so far?",
    ),
    (
        "p_beh2",
        BEHAVIORAL,
        Competency.IMPACT,
        QuestionSource.PLANNER,
        False,
        False,
        7,
        "What result are you proudest of?",
    ),
    (
        "own4",
        TECH,
        Competency.REASONING,
        QuestionSource.CANDIDATE,
        False,
        False,
        8,
        "How do you debug a slow API endpoint?",
    ),
)
CUSTOM_ORDER = ["own1", "p_tech1", "own4", "p_beh1", "own2", "p_beh2", "p_hm1", "own3"]
"""The order a Custom session from `make_custom_brief` asks its questions in (CU-4)."""
CUSTOM_MUST_ASK = ["own1", "own2", "own3"]


def make_custom_brief(
    *,
    difficulty: Difficulty = Difficulty.REALISTIC,
    mode: Mode = Mode.REALISTIC,
    duration: int = 30,
    max_probes: int = 3,
) -> InterviewerBrief:
    """A Custom brief with three categories, own and planner questions, must-ask questions and
    one verbatim question (own1)."""
    own = [q for q in _CUSTOM_QUESTIONS if q[3] == QuestionSource.CANDIDATE]
    custom = CustomSessionSpec(
        categories=[CustomCategory(category=c, share=1 / 3) for c in CUSTOM_CATEGORIES],
        questions=[
            CustomQuestion(
                text=text, category=cat, competencies=[comp], must_ask=must, verbatim=verbatim
            )
            for _, cat, comp, _, must, verbatim, _, text in own
        ],
    )
    tough = difficulty == Difficulty.TOUGH
    return InterviewerBrief(
        session=SessionConfig(
            interview_type=InterviewType.CUSTOM,
            difficulty=difficulty,
            mode=mode,
            duration_min=30 if duration == 30 else 45,
            level=Level.SENIOR,
            custom=custom,
        ),
        generic_mode=True,
        target_competencies=list(dict.fromkeys(q[2] for q in _CUSTOM_QUESTIONS))[:6],
        questions=[
            BriefQuestion(
                id=qid,
                text=text,
                competencies=[comp],
                priority=priority,
                source=source,
                category=cat,
                must_ask=must,
                verbatim=verbatim,
            )
            for qid, cat, comp, source, must, verbatim, priority, text in _CUSTOM_QUESTIONS
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
