"""The transcript as the sim saw it, with times from the session start."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Speaker = Literal["interviewer", "candidate"]


class Line(BaseModel):
    speaker: Speaker
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    phase: str | None = None
    question_ref: str | None = None
    note: str | None = Field(default=None, description="What the harness did, e.g. 'silence'.")


def clock(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def as_text(lines: list[Line]) -> str:
    """Readable transcript: one block per line, with a time and a speaker label."""
    out = []
    for line in lines:
        who = "Interviewer" if line.speaker == "interviewer" else "Candidate"
        extra = f" [{line.phase}]" if line.phase else ""
        note = f" ({line.note})" if line.note else ""
        out.append(f"[{clock(line.start_ms)}] {who}{extra}{note}: {line.text}")
    return "\n\n".join(out) + "\n"


def for_judge(lines: list[Line]) -> str:
    out = []
    for line in lines:
        who = "I" if line.speaker == "interviewer" else "C"
        note = f" ({line.note})" if line.note else ""
        out.append(f"[{clock(line.start_ms)}] {who}{note}: {line.text}")
    return "\n".join(out)
