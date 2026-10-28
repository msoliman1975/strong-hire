"""The transcript of a finished session (TR-1): what the candidate and the interviewer said.

    GET /sessions/{id}/transcript   turns in order, grouped by question

Only the owner reads it: another user's session answers 404, like the debrief. Admins keep using
the admin session page and replay. A session that has not ended answers 409 `not_ended`.

Turns hold text only; audio is never kept (spec: "Data handling"). The AC-1 export carries the
`turns` table and account delete removes it (TR-2).

Grouping: turns follow in session order. A turn with a question_ref joins the group of that
question. A turn without one stays in the current group while the phase is the same, and starts a
new group when the phase changes. When the first turn with a question_ref meets an unlabeled
group of the same phase (the interviewer's question, saved before the answer was matched), that
group takes the question.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from strong_api.inputs.deps import Db, Me
from strong_api.scoring.router import _brief, _owned_session
from strong_core.db.models import Turn
from strong_core.db.turns import TURN_ORDER
from strong_core.schemas import Phase, Speaker

router = APIRouter(tags=["reports"])


class TranscriptTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    speaker: Speaker
    phase: Phase
    text: str
    start_ms: int = Field(description="Time offset from the session start, in milliseconds.")
    end_ms: int


class TranscriptGroup(BaseModel):
    """Consecutive turns about one question, or about one phase when there is no question."""

    model_config = ConfigDict(extra="forbid")

    question_ref: str | None = Field(description="The brief question id, None outside questions.")
    question_text: str | None = Field(description="The question as planned, when known.")
    phase: Phase = Field(description="The phase of the group's first turn.")
    turns: list[TranscriptTurn]


class Transcript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    started_at: datetime | None
    ended_at: datetime
    groups: list[TranscriptGroup]


def group_turns(
    turns: list[tuple[TranscriptTurn, str | None]], questions: dict[str, str] | None = None
) -> list[TranscriptGroup]:
    """Group (turn, question_ref) pairs, in session order, by question (module docstring)."""
    questions = questions or {}
    groups: list[TranscriptGroup] = []
    for turn, ref in turns:
        current = groups[-1] if groups else None
        if (
            current is not None
            and ref is not None
            and current.question_ref is None
            and current.phase == turn.phase
        ):
            current.question_ref, current.question_text = ref, questions.get(ref)
        if current is not None and (
            (ref is not None and ref == current.question_ref)
            or (ref is None and turn.phase == current.phase)
        ):
            current.turns.append(turn)
            continue
        groups.append(
            TranscriptGroup(
                question_ref=ref,
                question_text=questions.get(ref) if ref else None,
                phase=turn.phase,
                turns=[turn],
            )
        )
    return groups


def _turn(row: Turn) -> TranscriptTurn:
    return TranscriptTurn(
        id=row.id,
        speaker=row.speaker,
        phase=row.phase,
        text=row.text,
        start_ms=row.start_ms,
        end_ms=row.end_ms,
    )


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: uuid.UUID, db: Db, me: Me) -> Transcript:
    """TR-1: the transcript of the signed-in user's finished session. 404 for anyone else."""
    session = await _owned_session(db, me, session_id)
    if session.ended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_ended")
    rows = await db.scalars(
        select(Turn)
        .where(Turn.session_id == session.id, Turn.org_id == me.org_id)
        .order_by(*TURN_ORDER)
    )
    brief = _brief(session)
    questions = {q.id: q.text for q in brief.questions} if brief is not None else {}
    return Transcript(
        session_id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        groups=group_turns([(_turn(r), r.question_ref) for r in rows], questions),
    )
