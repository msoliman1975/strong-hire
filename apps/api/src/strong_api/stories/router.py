"""Story library endpoints (ST-1, ST-2, ST-6 notes).

    GET    /stories                   ST-1: the user's stories, newest first; `?status=` and
                                      `?skill=` filter
    POST   /stories                   ST-1: create a draft story
    POST   /stories/from-answer       ST-2: save a debrief answer as a draft story
    GET    /stories/{id}              ST-1: one story
    PATCH  /stories/{id}              ST-1: change the title, the skills or any part
    DELETE /stories/{id}              ST-1: delete a story
    GET    /stories/{id}/notes        ST-6: the story's fix notes, oldest first
    POST   /stories/{id}/notes        ST-6: append a fix note

Stories belong to one user: every query filters by both `org_id` and `user_id`, and another
user's story answers 404. Account export and delete (AC-1) cover stories and their notes through
USER_OWNED_TABLES (strong_api.account.deletion, strong_worker.account.bundle); notes live on the
story row (`notes_json`).

Error details are {"code", "message", ...}:
- 404 `scorecard_not_found` or `question_not_found` for from-answer;
- 409 `story_exists` (with `story_id`) when that answer is already saved as a story;
- 422 `answer_empty` when the candidate said nothing for that question.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import select

from strong_api.inputs.deps import Db, Me
from strong_api.stories.schemas import StoryFromAnswerIn, StoryIn, StoryNoteIn, StoryPatch
from strong_core.db.models import InterviewSession, Scorecard
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Turn as TurnRow
from strong_core.schemas import (
    Competency,
    QuestionScore,
    Speaker,
    Story,
    StoryNote,
    StoryPart,
    StorySource,
    StoryStatus,
)
from strong_core.schemas.stories import STORY_TITLE_MAX_CHARS

router = APIRouter(tags=["stories"])

SCORECARD_NOT_FOUND = "scorecard_not_found"
QUESTION_NOT_FOUND = "question_not_found"
STORY_EXISTS = "story_exists"
ANSWER_EMPTY = "answer_empty"

_FROM_ANSWER_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {
        "description": "The session is not the user's, or detail.code is "
        "'scorecard_not_found' or 'question_not_found'."
    },
    409: {"description": "detail.code is 'story_exists'; detail.story_id is that story."},
    422: {"description": "detail.code is 'answer_empty' when the answer has no text."},
}


def _clean(text: str | None) -> str | None:
    """Trimmed text, or None for a blank part."""
    if text is None:
        return None
    text = text.strip()
    return text or None


def story_out(row: StoryRow) -> Story:
    return Story(
        id=row.id,
        title=row.title,
        context=row.context,
        stakes=row.stakes,
        action=row.action,
        result=row.result,
        reflection=row.reflection,
        skills=[Competency(s) for s in row.skills],
        status=row.status,
        source=row.source,
        source_session_id=row.source_session_id,
        source_question_ref=row.source_question_ref,
        notes=_notes(row),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _notes(row: StoryRow) -> list[StoryNote]:
    return [StoryNote.model_validate(n) for n in row.notes_json or []]


async def _owned(db: Db, me: Me, story_id: uuid.UUID) -> StoryRow:
    row = await db.scalar(
        select(StoryRow).where(
            StoryRow.id == story_id,
            StoryRow.org_id == me.org_id,
            StoryRow.user_id == me.user_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return row


async def _save(db: Db, row: StoryRow) -> Story:
    await db.commit()
    await db.refresh(row)
    return story_out(row)


# --- ST-1 ------------------------------------------------------------------------------------


@router.get("/stories")
async def list_stories(
    db: Db,
    me: Me,
    story_status: Annotated[
        StoryStatus | None, Query(alias="status", description="Only drafts, or only proven.")
    ] = None,
    skill: Annotated[Competency | None, Query(description="Only stories with this tag.")] = None,
) -> list[Story]:
    """ST-1: the user's stories, newest first."""
    query = select(StoryRow).where(StoryRow.org_id == me.org_id, StoryRow.user_id == me.user_id)
    if story_status is not None:
        query = query.where(StoryRow.status == story_status)
    rows = await db.scalars(query.order_by(StoryRow.created_at.desc(), StoryRow.id.desc()))
    # Skills are a JSON list; a user's library is small, so the tag filter runs here.
    return [story_out(r) for r in rows if skill is None or skill.value in r.skills]


@router.post("/stories", status_code=status.HTTP_201_CREATED)
async def create_story(body: StoryIn, db: Db, me: Me) -> Story:
    """ST-1: create a draft story."""
    row = StoryRow(
        org_id=me.org_id,
        user_id=me.user_id,
        title=body.title.strip() or body.title,
        **{p.value: _clean(getattr(body, p.value)) for p in StoryPart},
        skills=[s.value for s in body.skills],
        status=StoryStatus.DRAFT,
        source=body.source,
        notes_json=[],
    )
    db.add(row)
    return await _save(db, row)


# --- ST-2 ------------------------------------------------------------------------------------


@router.post(
    "/stories/from-answer",
    status_code=status.HTTP_201_CREATED,
    responses=_FROM_ANSWER_RESPONSES,
)
async def story_from_answer(body: StoryFromAnswerIn, db: Db, me: Me) -> Story:
    """ST-2: "Save as a story" on a debrief answer. Creates a draft story with the candidate's
    answer to that question, tagged with the competencies it was scored on and linked to the
    session and question. The answer goes into `action` until a split into parts is known."""
    session = await db.scalar(
        select(InterviewSession).where(
            InterviewSession.id == body.session_id, InterviewSession.org_id == me.org_id
        )
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    question = await _scored_question(db, session.id, body.question_ref)

    existing = await db.scalar(
        select(StoryRow.id).where(
            StoryRow.org_id == me.org_id,
            StoryRow.user_id == me.user_id,
            StoryRow.source_session_id == session.id,
            StoryRow.source_question_ref == body.question_ref,
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": STORY_EXISTS,
                "message": "This answer is already in your stories.",
                "story_id": str(existing),
            },
        )

    answer = await answer_text(db, session.id, body.question_ref)
    if not answer:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": ANSWER_EMPTY, "message": "There is no answer to save for this question."},
        )
    skills = list(dict.fromkeys(s.competency for s in question.scores))
    row = StoryRow(
        org_id=me.org_id,
        user_id=me.user_id,
        title=body.title or _title(question.question_text),
        action=answer,
        skills=[s.value for s in skills],
        status=StoryStatus.DRAFT,
        source=StorySource.DEBRIEF_ANSWER,
        source_session_id=session.id,
        source_question_ref=body.question_ref,
        notes_json=[],
    )
    db.add(row)
    return await _save(db, row)


async def _scored_question(db: Db, session_id: uuid.UUID, question_ref: str) -> QuestionScore:
    card = await db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
    if card is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": SCORECARD_NOT_FOUND, "message": "This session has no debrief yet."},
        )
    for item in card.per_question_json or []:
        if item.get("question_ref") != question_ref:
            continue
        try:
            return QuestionScore.model_validate(item)
        except ValidationError:
            break
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        {"code": QUESTION_NOT_FOUND, "message": "This question is not in the debrief."},
    )


async def answer_text(db: Db, session_id: uuid.UUID, question_ref: str) -> str:
    """Everything the candidate said for one question (the answer and the follow-ups), in
    order, one paragraph per turn."""
    turns = await db.scalars(
        select(TurnRow.text)
        .where(
            TurnRow.session_id == session_id,
            TurnRow.question_ref == question_ref,
            TurnRow.speaker == Speaker.CANDIDATE,
        )
        .order_by(TurnRow.start_ms, TurnRow.seq)
    )
    return "\n\n".join(t.strip() for t in turns if t.strip())


def _title(question_text: str) -> str:
    text = " ".join(question_text.split())
    if len(text) <= STORY_TITLE_MAX_CHARS:
        return text
    return text[: STORY_TITLE_MAX_CHARS - 1].rstrip() + "…"


# --- ST-1 one story --------------------------------------------------------------------------


@router.get("/stories/{story_id}")
async def get_story(story_id: uuid.UUID, db: Db, me: Me) -> Story:
    """ST-1: one story with its notes."""
    return story_out(await _owned(db, me, story_id))


@router.patch("/stories/{story_id}")
async def edit_story(story_id: uuid.UUID, body: StoryPatch, db: Db, me: Me) -> Story:
    """ST-1: change the title, the skill tags or any of the five parts. Only the fields sent
    change; a part sent as null or blank is cleared."""
    row = await _owned(db, me, story_id)
    sent = body.model_fields_set
    if "title" in sent:
        title = _clean(body.title)
        if title is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                [{"loc": ["body", "title"], "msg": "A story needs a title", "type": "missing"}],
            )
        row.title = title
    for part in StoryPart:
        if part.value in sent:
            setattr(row, part.value, _clean(getattr(body, part.value)))
    if "skills" in sent:
        row.skills = [s.value for s in body.skills or []]
    return await _save(db, row)


@router.delete("/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(story_id: uuid.UUID, db: Db, me: Me) -> Response:
    """ST-1: delete a story and its notes. Debriefs that used it keep their scores."""
    row = await _owned(db, me, story_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- ST-6 notes ------------------------------------------------------------------------------


@router.get("/stories/{story_id}/notes")
async def list_story_notes(story_id: uuid.UUID, db: Db, me: Me) -> list[StoryNote]:
    """ST-6: the story's fix notes, oldest first."""
    return _notes(await _owned(db, me, story_id))


@router.post("/stories/{story_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_story_note(story_id: uuid.UUID, body: StoryNoteIn, db: Db, me: Me) -> StoryNote:
    """ST-6: append a fix note (S22 sends the debrief's story fix here)."""
    row = await _owned(db, me, story_id)
    note = StoryNote(
        text=body.text.strip() or body.text,
        session_id=body.session_id,
        question_ref=body.question_ref,
        at=datetime.now(UTC),
    )
    # A new list, so SQLAlchemy sees the JSON change.
    row.notes_json = [*(row.notes_json or []), note.model_dump(mode="json")]
    await db.commit()
    return note
