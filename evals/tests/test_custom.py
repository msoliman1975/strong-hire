"""Custom sessions in the eval harness (docs/custom-interview-spec.md: CU-1, CU-6).

A Custom session has no single interview type, so its competency pool is the union over its
categories (`session_competencies`), not `COMPETENCIES_BY_TYPE[interview_type]`.
"""

from __future__ import annotations

import json
from typing import Any

from strong_core.schemas import (
    Competency,
    CustomCategory,
    CustomSessionSpec,
    Difficulty,
    InterviewType,
    Level,
    Mode,
    SessionConfig,
    session_competencies,
)
from strong_evals.candidate import Persona
from strong_evals.stubs import StubPlanner
from strong_evals.transcripts import TRANSCRIPTS_DIR, Quality, ScriptedTranscript

CUSTOM = SessionConfig(
    interview_type=InterviewType.CUSTOM,
    difficulty=Difficulty.REALISTIC,
    mode=Mode.REALISTIC,
    duration_min=30,
    level=Level.MID,
    custom=CustomSessionSpec(
        categories=[
            CustomCategory(category=InterviewType.BEHAVIORAL, share=0.5),
            CustomCategory(category=InterviewType.TECHNICAL_QA, share=0.5),
        ]
    ),
)


async def test_cu1_stub_planner_builds_a_custom_brief() -> None:
    """CU-1: the stub planner takes questions from each category and stays in the pool."""
    persona = Persona.from_resume_fixture("backend-senior", Quality.AVERAGE, "Sam Ortega")
    brief = await StubPlanner().brief(CUSTOM, persona)
    pool = set(session_competencies(CUSTOM))
    assert {q.category for q in brief.questions} == {
        InterviewType.BEHAVIORAL,
        InterviewType.TECHNICAL_QA,
    }
    assert set(brief.target_competencies) <= pool
    assert all(set(q.competencies) <= pool for q in brief.questions)


def test_cu6_scripted_transcript_accepts_a_custom_brief() -> None:
    """CU-6: a scripted transcript with a Custom brief validates against the session pool, so a
    technical competency is allowed next to behavioral ones."""
    data: dict[str, Any] = json.loads((TRANSCRIPTS_DIR / "beh-01.json").read_text("utf-8"))
    brief = data["brief"]
    brief["session"] |= {
        "interview_type": "custom",
        "custom": CUSTOM.custom.model_dump(mode="json") if CUSTOM.custom else None,
    }
    for q in brief["questions"]:
        q["category"] = "behavioral"
    brief["questions"][1] |= {
        "category": "technical_qa",
        "competencies": [Competency.CLARITY_OF_EXPLANATION.value],
    }
    transcript = ScriptedTranscript.model_validate(data)
    assert transcript.brief.questions[1].competencies == [Competency.CLARITY_OF_EXPLANATION]
