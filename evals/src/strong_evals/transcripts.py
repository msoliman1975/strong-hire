"""Scripted interview transcripts: evals/transcripts/<id>.json, one ScriptedTranscript each.

A scripted transcript is a full text interview (Turn model) with the InterviewerBrief it was run
from. Only some brief questions get asked, like in a real session. `vague_answers` lists the
indexes of candidate CORE turns that a trained interviewer would probe (IV-3). The people and
companies are synthetic.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    BriefQuestion,
    Contract,
    InterviewerBrief,
    Phase,
    RoleFamily,
    SessionConfig,
    Speaker,
    Turn,
)
from strong_evals import EVALS_DIR

TRANSCRIPTS_DIR = EVALS_DIR / "transcripts"
PHASE_ORDER = list(Phase)


class Quality(StrEnum):
    """How good the candidate's answers are meant to be."""

    STRONG = "strong"
    AVERAGE = "average"
    WEAK = "weak"


class ScriptedTranscript(Contract):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1)
    role_family: RoleFamily
    candidate_name: str = Field(min_length=1, description="Synthetic person.")
    quality: Quality
    brief: InterviewerBrief
    turns: list[Turn] = Field(min_length=4)
    vague_answers: list[int] = Field(
        default_factory=list,
        description="Indexes into turns: candidate CORE answers that are vague.",
    )
    notes: str | None = None

    @property
    def session(self) -> SessionConfig:
        return self.brief.session

    def question(self, ref: str) -> BriefQuestion:
        return next(q for q in self.brief.questions if q.id == ref)

    @model_validator(mode="after")
    def _check(self) -> ScriptedTranscript:
        allowed = set(COMPETENCIES_BY_TYPE[self.brief.session.interview_type])
        if not set(self.brief.target_competencies) <= allowed:
            raise ValueError("target_competencies must belong to the interview type")
        for q in self.brief.questions:
            if not set(q.competencies) <= allowed:
                raise ValueError(f"question {q.id}: competencies must belong to the interview type")
        refs = {q.id for q in self.brief.questions}
        last_phase = 0
        last_end = 0
        for i, t in enumerate(self.turns):
            phase = PHASE_ORDER.index(t.phase)
            if phase < last_phase:
                raise ValueError(f"turn {i}: phase {t.phase.value} goes backwards")
            last_phase = phase
            if t.start_ms < last_end:
                raise ValueError(f"turn {i}: start_ms overlaps the previous turn")
            last_end = t.end_ms
            if t.phase == Phase.CORE:
                if t.question_ref not in refs:
                    raise ValueError(f"turn {i}: CORE turns need a question_ref from the brief")
            elif t.question_ref is not None:
                raise ValueError(f"turn {i}: question_ref is only allowed in CORE")
        for i in self.vague_answers:
            if not 0 <= i < len(self.turns):
                raise ValueError(f"vague_answers: {i} is not a turn index")
            t = self.turns[i]
            if t.speaker != Speaker.CANDIDATE or t.phase != Phase.CORE:
                raise ValueError(f"vague_answers: turn {i} is not a candidate CORE answer")
        if self.turns[0].phase != Phase.INTRO or self.turns[-1].phase != Phase.WRAP_UP:
            raise ValueError("a transcript starts in INTRO and ends in WRAP_UP")
        return self

    def asked_question_refs(self) -> list[str]:
        """Question ids the interviewer asked, in order, without repeats."""
        return asked_question_refs(self.turns)


def asked_question_refs(turns: list[Turn]) -> list[str]:
    seen: dict[str, None] = {}
    for t in turns:
        if t.phase == Phase.CORE and t.speaker == Speaker.INTERVIEWER and t.question_ref:
            seen.setdefault(t.question_ref, None)
    return list(seen)


def load_transcript(path: Path) -> ScriptedTranscript:
    transcript = ScriptedTranscript.model_validate_json(path.read_text(encoding="utf-8"))
    if transcript.id != path.stem:
        raise ValueError(f"{path.name}: id {transcript.id!r} must match the file name")
    return transcript


def load_transcripts(
    ids: list[str] | None = None, folder: Path = TRANSCRIPTS_DIR
) -> list[ScriptedTranscript]:
    """All transcripts (sorted by id), or the named ones in the given order."""
    if ids is None:
        return [load_transcript(p) for p in sorted(folder.glob("*.json"))]
    return [load_transcript(folder / f"{i}.json") for i in ids]
