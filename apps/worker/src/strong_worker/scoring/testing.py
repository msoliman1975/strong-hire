"""Test helpers for the scorer, shared by the worker, API and eval test suites.

Nothing here runs in production.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from strong_core.config import find_repo_root
from strong_core.gateway import FakeBackend, Message, Role, TokenUsage
from strong_core.schemas import InterviewerBrief, Phase, Speaker, Turn

TRANSCRIPTS_DIR = find_repo_root() / "evals" / "transcripts"


def load_scripted(transcript_id: str) -> tuple[InterviewerBrief, list[Turn]]:
    """Brief and turns of an eval transcript (evals/transcripts/<id>.json)."""
    data = json.loads((TRANSCRIPTS_DIR / f"{transcript_id}.json").read_text(encoding="utf-8"))
    brief = InterviewerBrief.model_validate(data["brief"])
    return brief, [Turn.model_validate(t) for t in data["turns"]]


def first_answers(turns: Sequence[Turn]) -> dict[str, str]:
    """question_ref -> the candidate's first CORE answer to it."""
    out: dict[str, str] = {}
    for t in turns:
        if t.phase == Phase.CORE and t.speaker == Speaker.CANDIDATE and t.question_ref:
            out.setdefault(t.question_ref, t.text)
    return out


def quote_from(text: str, words: int = 6) -> str:
    return " ".join(text.split()[:words])


def scorecard_reply(
    brief: InterviewerBrief,
    turns: Sequence[Turn],
    scores: dict[str, int] | int = 3,
    *,
    values: bool = True,
    hire_signal: str = "Strong Hire",
    quote: str | None = None,
) -> dict[str, Any]:
    """A model reply (Scorecard JSON) that quotes the transcript correctly.

    `scores` is one score for everything, or competency/value name -> score. `quote` replaces
    every quote, to test bad quotes.
    """
    answers = first_answers(turns)

    def score_for(name: str) -> int:
        return scores if isinstance(scores, int) else scores.get(name, 3)

    per_question = []
    overall: dict[str, dict[str, Any]] = {}
    overall_values: dict[str, dict[str, Any]] = {}
    for q in brief.questions:
        if q.id not in answers:
            continue
        q_quote = quote or quote_from(answers[q.id])
        comp: list[dict[str, Any]] = [
            {
                "competency": c.value,
                "score": score_for(c.value),
                "justification": f"Evidence for {c.value} on {q.id}.",
                "quotes": [q_quote],
            }
            for c in q.competencies
        ]
        vals: list[dict[str, Any]] = [
            {
                "value": v,
                "score": score_for(v),
                "justification": f"Evidence for {v} on {q.id}.",
                "quotes": [q_quote],
            }
            for v in (q.values if values else [])
        ]
        for item in comp:
            overall.setdefault(item["competency"], item)
        for item in vals:
            overall_values.setdefault(item["value"], item)
        per_question.append(
            {
                "question_ref": q.id,
                "question_text": q.text,
                "scores": comp,
                "value_scores": vals,
                "strengths": [f"Clear example on {q.id}."],
                "misses": [f"No trade-off named on {q.id}."],
            }
        )
    return {
        "hire_signal": hire_signal,
        "rationale": "Placeholder.",
        "competency_scores": list(overall.values()),
        "value_scores": list(overall_values.values()),
        "per_question": per_question,
        "scorer_model": "pending",
        "rubric_version": "pending",
    }


RATIONALE = (
    "The candidate gave specific examples with a clear personal role. "
    "Results were measured in numbers on most answers. "
    "Trade-offs were named but not always weighed against each other."
)


class ScriptedBackend(FakeBackend):
    """Fake model that returns the given replies in order, and keeps every request.

    A reply is a dict (structured output) or a str (text). When the list runs out, structured
    calls repeat the last dict and text calls repeat the last str.
    """

    def __init__(self, replies: Sequence[dict[str, Any] | str], fixtures_dir: Path | None = None):
        super().__init__(fixtures_dir)
        self.replies = list(replies)
        self.calls: list[tuple[list[Message], type[BaseModel] | None]] = []

    def complete(
        self, role: Role, messages: Sequence[Message], output_type: type[BaseModel] | None
    ) -> tuple[object, TokenUsage]:
        self.calls.append((list(messages), output_type))
        want = str if output_type is None else dict
        index = next((i for i, r in enumerate(self.replies) if isinstance(r, want)), None)
        if index is None:
            raise AssertionError(f"no scripted {want.__name__} reply left")
        reply = self.replies[index]
        if sum(isinstance(r, want) for r in self.replies) > 1:
            self.replies.pop(index)
        if output_type is None:
            return str(reply), TokenUsage(100, 50)
        return output_type.model_validate(reply), TokenUsage(1000, 400)
