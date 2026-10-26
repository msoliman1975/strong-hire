"""The post-session rating (L05): "felt like a real interview", 1 to 5, one per session.

    GET /sessions/{id}/feedback   the rating, or null when the candidate has not rated it
    PUT /sessions/{id}/feedback   rate it, or change the rating (only after the session ended)

The debrief asks once; skipping is the candidate's choice and stores nothing. The admin overview
averages the ratings as "perceived realism" (docs/spec.md "Metrics and analytics").
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from strong_api.inputs.deps import Db, Me
from strong_api.scoring.router import _owned_session
from strong_core.db.models import SessionFeedback

router = APIRouter(tags=["sessions"])


class SessionFeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    realism: int = Field(ge=1, le=5, description='"Felt like a real interview", 1 to 5')
    comment: str | None = Field(default=None, max_length=2000)


class SessionFeedbackOut(BaseModel):
    realism: int
    comment: str | None
    created_at: datetime


def _out(row: SessionFeedback) -> SessionFeedbackOut:
    return SessionFeedbackOut(realism=row.realism, comment=row.comment, created_at=row.created_at)


@router.get("/sessions/{session_id}/feedback")
async def get_feedback(session_id: uuid.UUID, db: Db, me: Me) -> SessionFeedbackOut | None:
    session = await _owned_session(db, me, session_id)
    row = await db.scalar(select(SessionFeedback).where(SessionFeedback.session_id == session.id))
    return _out(row) if row is not None else None


@router.put("/sessions/{session_id}/feedback")
async def put_feedback(
    session_id: uuid.UUID, body: SessionFeedbackIn, db: Db, me: Me
) -> SessionFeedbackOut:
    session = await _owned_session(db, me, session_id)
    if session.ended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_ended")
    row = await db.scalar(select(SessionFeedback).where(SessionFeedback.session_id == session.id))
    if row is None:
        row = SessionFeedback(org_id=session.org_id, session_id=session.id)
        db.add(row)
    row.realism = body.realism
    row.comment = body.comment or None
    await db.commit()
    await db.refresh(row)
    return _out(row)
