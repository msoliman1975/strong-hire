"""Scoring a Custom session (docs/custom-interview-spec.md: CU-6).

Each question is scored on its own competencies from the session's pool (the union over its
categories), with the same rubric for own and planner questions, and the hire signal uses the
normal weights and hard rules.
"""

from __future__ import annotations

from typing import Any

from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.profiles import generic_profile
from strong_core.schemas import Competency, InterviewerBrief, Turn
from strong_worker.scoring.scorer import SessionScorer, interview_type_text
from strong_worker.scoring.testing import (
    RATIONALE,
    ScriptedBackend,
    first_answers,
    load_scripted,
    quote_from,
    scorecard_reply,
)

C = Competency


def gateway(backend: ScriptedBackend) -> ModelGateway:
    return ModelGateway(fake_models_config(), fake=backend)


def custom_brief() -> tuple[InterviewerBrief, list[Turn]]:
    """beh-01 as a Custom session: behavioral and technical_qa. q1 is the candidate's own
    must-ask question; q2 is a technical question."""
    brief, turns = load_scripted("beh-01")
    data: dict[str, Any] = brief.model_dump(mode="json")
    q1 = data["questions"][0]
    data["session"] |= {
        "interview_type": "custom",
        "custom": {
            "categories": [
                {"category": "behavioral", "share": 0.5, "focus": ["ownership"]},
                {"category": "technical_qa", "share": 0.5, "focus": []},
            ],
            "questions": [
                {
                    "text": q1["text"],
                    "category": "behavioral",
                    "competencies": q1["competencies"],
                }
            ],
        },
    }
    for q in data["questions"]:
        q["category"] = "behavioral"
    q1 |= {"source": "candidate", "must_ask": True}
    q2 = data["questions"][1]
    q2 |= {"category": "technical_qa", "competencies": ["clarity_of_explanation"]}
    return InterviewerBrief.model_validate(data), turns


async def test_cu6_custom_session_scores_on_the_session_competency_pool() -> None:
    """CU-6: a technical competency counts in a behavioral + technical Custom session; a case
    competency, outside the session's categories, is dropped."""
    brief, turns = custom_brief()
    reply = scorecard_reply(brief, turns, 3)
    answer = quote_from(first_answers(turns)["q1"])
    reply["per_question"][0]["scores"].append(
        {"competency": "problem_framing", "score": 1, "justification": "x", "quotes": [answer]}
    )
    backend = ScriptedBackend([reply, RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    scored = {c.competency for c in outcome.scorecard.competency_scores}
    assert C.CLARITY_OF_EXPLANATION in scored
    assert C.PROBLEM_FRAMING not in scored
    q2 = next(q for q in outcome.scorecard.per_question if q.question_ref == "q2")
    assert [s.competency for s in q2.scores] == [C.CLARITY_OF_EXPLANATION]


async def test_cu6_own_questions_get_the_same_rubric_and_signal() -> None:
    """CU-6: the scorer is not told which questions the candidate wrote, so own questions get
    no softer standard; the same scores give the same hire signal as a standard session."""
    brief, turns = custom_brief()
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    rubric_input = backend.calls[0][0][1].content
    assert "Interview type: custom, mixing behavioral, technical_qa questions" in rubric_input
    assert "q2 (technical_qa): " in rubric_input and "q1 (behavioral): " in rubric_input
    assert (
        "candidate"
        not in rubric_input.split("Questions that were asked")[1].split("Transcript:")[0]
    )
    assert outcome.scorecard.rubric_version == "scorer/rubric.v1"
    assert "q1" in [q.question_ref for q in outcome.scorecard.per_question]

    standard, std_turns = load_scripted("beh-01")
    std_backend = ScriptedBackend([scorecard_reply(standard, std_turns, 3), RATIONALE])
    std = await SessionScorer(gateway(std_backend)).score(standard, std_turns, generic_profile())
    assert outcome.scorecard.hire_signal == std.scorecard.hire_signal
    assert outcome.signal.rules == std.signal.rules


def test_cu6_interview_type_text_for_standard_sessions_is_unchanged() -> None:
    standard, _ = load_scripted("beh-01")
    assert interview_type_text(standard) == "behavioral"
