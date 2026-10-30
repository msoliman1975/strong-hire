"""Suggestions from Strova (ux-spec section 8, SG-2 to SG-8).

    GET  /suggestions?place=...         open suggestions for one place, newest first:
                                        debrief&session_id, story&story_id,
                                        role&job_target_id, stories, resume&resume_id
    POST /suggestions/{id}/accept       apply it (optionally with an edited `after`)
    POST /suggestions/{id}/dismiss      dismiss it; it never comes back (SG-8)
    POST /suggestions/{id}/undo         restore what accepting changed (SG-2)

The worker writes suggestions (strong_worker.suggestions); this router only lists and applies
them. Accepting:
- tune_story: sets the story part; Undo restores it.
- new_story: saves a draft story from the debrief answer.
- missing_skill and story_idea: change nothing; the reply says what crafting opens with.
- tailor_role: adds a "For {company}" note to the story; Undo removes it.
- improve_resume_line: sets the resume line; the resume check runs again on its next read, and
  the story ideas follow the new line. Undo restores the line.
- review: applies the chosen parts' edits; Undo restores those parts.
A story whose result changes queues the improve resume line job (SG-6).

Suggestions belong to one user: every query filters by `org_id` and `user_id`, and another
user's suggestion answers 404. Error details for 409 are {"code", "message"}.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import Select, select

from strong_api.inputs.deps import Db, Me, Queue
from strong_api.inputs.queue import STORY_IDEA_SKILLS, SUGGEST_RESUME_LINE
from strong_api.suggestions.schemas import AcceptIn, AcceptOut, Crafting, Place
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.schemas import (
    ImproveResumeLinePayload,
    MissingSkillPayload,
    NewStoryPayload,
    Resume,
    ReviewPayload,
    StoryIdeaPayload,
    StoryNote,
    StoryPart,
    StorySource,
    StoryStatus,
    Suggestion,
    SuggestionKind,
    SuggestionStatus,
    TailorRolePayload,
    TuneStoryPayload,
)

router = APIRouter(tags=["suggestions"])

NOT_OPEN = "not_open"
CANNOT_UNDO = "cannot_undo"
CHANGED = "changed_since"

# What each place shows (ux-spec section 8, "Shown on").
PLACE_KINDS: dict[Place, tuple[SuggestionKind, ...]] = {
    Place.DEBRIEF: (
        SuggestionKind.TUNE_STORY,
        SuggestionKind.NEW_STORY,
        SuggestionKind.MISSING_SKILL,
    ),
    Place.STORY: (SuggestionKind.TUNE_STORY, SuggestionKind.TAILOR_ROLE, SuggestionKind.REVIEW),
    Place.ROLE: (SuggestionKind.MISSING_SKILL, SuggestionKind.TAILOR_ROLE),
    Place.STORIES: (
        SuggestionKind.TUNE_STORY,
        SuggestionKind.MISSING_SKILL,
        SuggestionKind.TAILOR_ROLE,
        SuggestionKind.STORY_IDEA,
    ),
    Place.RESUME: (SuggestionKind.IMPROVE_RESUME_LINE, SuggestionKind.STORY_IDEA),
}
_PLACE_ID = {
    Place.DEBRIEF: "session_id",
    Place.STORY: "story_id",
    Place.ROLE: "job_target_id",
    Place.RESUME: "resume_id",
}
_REF = re.compile(r"^roles\[(\d+)\]\.achievements\[(\d+)\]$")


def suggestion_out(row: SuggestionRow) -> Suggestion:
    return Suggestion.model_validate(
        {
            "id": row.id,
            "kind": row.kind,
            "status": row.status,
            "payload": row.payload,
            "reason": row.reason,
            "source_session_id": row.source_session_id,
            "source_question_ref": row.source_question_ref,
            "source_resume_id": row.source_resume_id,
            "job_target_id": row.job_target_id,
            "story_id": row.story_id,
            "resume_id": row.resume_id,
            "prompt_ref": row.prompt_ref,
            "created_at": row.created_at,
            "resolved_at": row.resolved_at,
        }
    )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"code": code, "message": message})


def _open_query(org_id: uuid.UUID, user_id: uuid.UUID) -> Select[SuggestionRow]:
    return (
        select(SuggestionRow)
        .where(
            SuggestionRow.org_id == org_id,
            SuggestionRow.user_id == user_id,
            SuggestionRow.status == SuggestionStatus.OPEN,
        )
        .order_by(SuggestionRow.created_at.desc(), SuggestionRow.id)
    )


async def debrief_suggestions(
    db: Db, org_id: uuid.UUID, user_id: uuid.UUID, session_id: uuid.UUID
) -> list[Suggestion]:
    """DB-4: the open suggestions from one take's debrief."""
    rows = await db.scalars(
        _open_query(org_id, user_id).where(
            SuggestionRow.source_session_id == session_id,
            SuggestionRow.kind.in_(PLACE_KINDS[Place.DEBRIEF]),
        )
    )
    return [suggestion_out(r) for r in rows]


@router.get("/suggestions")
async def list_suggestions(
    place: Place,
    db: Db,
    me: Me,
    session_id: uuid.UUID | None = None,
    story_id: uuid.UUID | None = None,
    job_target_id: uuid.UUID | None = None,
    resume_id: uuid.UUID | None = None,
) -> list[Suggestion]:
    """SG-8: the open suggestions for one place, newest first."""
    ids = {
        "session_id": session_id,
        "story_id": story_id,
        "job_target_id": job_target_id,
        "resume_id": resume_id,
    }
    query = _open_query(me.org_id, me.user_id).where(SuggestionRow.kind.in_(PLACE_KINDS[place]))
    name = _PLACE_ID.get(place)
    if name is not None:
        value = ids[name]
        if value is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                [
                    {
                        "loc": ["query", name],
                        "msg": f"place={place.value} needs {name}",
                        "type": "missing",
                    }
                ],
            )
        column = "source_session_id" if name == "session_id" else name
        query = query.where(getattr(SuggestionRow, column) == value)
    return [suggestion_out(r) for r in await db.scalars(query)]


async def _owned(db: Db, me: Me, suggestion_id: uuid.UUID) -> SuggestionRow:
    row = await db.scalar(
        select(SuggestionRow).where(
            SuggestionRow.id == suggestion_id,
            SuggestionRow.org_id == me.org_id,
            SuggestionRow.user_id == me.user_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found")
    return row


async def _story(db: Db, me: Me, story_id: uuid.UUID | None) -> StoryRow:
    row = None
    if story_id is not None:
        row = await db.scalar(
            select(StoryRow).where(
                StoryRow.id == story_id,
                StoryRow.org_id == me.org_id,
                StoryRow.user_id == me.user_id,
            )
        )
    if row is None:
        raise _conflict(CHANGED, "The story this suggestion changes is gone.")
    return row


async def _resume(db: Db, me: Me, resume_id: uuid.UUID | None) -> tuple[ResumeRow, Resume]:
    row = None
    if resume_id is not None:
        row = await db.scalar(
            select(ResumeRow).where(
                ResumeRow.id == resume_id,
                ResumeRow.org_id == me.org_id,
                ResumeRow.user_id == me.user_id,
                ResumeRow.deleted_at.is_(None),
            )
        )
    if row is None or row.parsed_json is None:
        raise _conflict(CHANGED, "The resume this suggestion changes is gone.")
    return row, Resume.model_validate(row.parsed_json)


def _line(resume: Resume, ref: str) -> tuple[int, int]:
    found = _REF.match(ref)
    if found is None:
        raise _conflict(CHANGED, "That resume line is gone.")
    i, j = int(found[1]), int(found[2])
    if i >= len(resume.roles) or j >= len(resume.roles[i].achievements):
        raise _conflict(CHANGED, "That resume line is gone.")
    return i, j


def _set_line(row: ResumeRow, resume: Resume, i: int, j: int, text: str) -> None:
    roles = list(resume.roles)
    lines = list(roles[i].achievements)
    lines[j] = text
    roles[i] = roles[i].model_copy(update={"achievements": lines})
    row.parsed_json = resume.model_copy(update={"roles": roles}).model_dump(mode="json")


async def _queue_resume_line(queue: Queue, me: Me, story: StoryRow) -> None:
    """SG-6: a story whose result changed may improve a resume line."""
    await queue.enqueue(
        SUGGEST_RESUME_LINE,
        f"suggest_resume_line:{story.id}:{uuid.uuid4().hex[:8]}",
        org_id=str(me.org_id),
        story_id=str(story.id),
    )


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: uuid.UUID, body: AcceptIn, db: Db, me: Me, queue: Queue
) -> AcceptOut:
    """SG-8: apply the suggestion. 409 `not_open` when it was already accepted or dismissed."""
    row = await _owned(db, me, suggestion_id)
    if row.status != SuggestionStatus.OPEN:
        raise _conflict(NOT_OPEN, "This suggestion was already accepted or dismissed.")
    now = datetime.now(UTC)
    out: dict[str, Any] = {}
    undo: dict[str, Any] | None = None
    result_changed: StoryRow | None = None
    match row.kind:
        case SuggestionKind.TUNE_STORY:
            edit = TuneStoryPayload.model_validate(row.payload).edit
            story = await _story(db, me, row.story_id)
            after = (body.after or edit.after).strip()
            before = getattr(story, edit.part.value)
            setattr(story, edit.part.value, after)
            story.updated_at = now
            undo = {"story_id": str(story.id), "parts": {edit.part.value: [before, after]}}
            out["story_id"] = story.id
            if edit.part == StoryPart.RESULT:
                result_changed = story
        case SuggestionKind.NEW_STORY:
            payload = NewStoryPayload.model_validate(row.payload)
            story = StoryRow(
                org_id=me.org_id,
                user_id=me.user_id,
                title=payload.title,
                context=payload.context,
                stakes=payload.stakes,
                action=payload.action,
                result=payload.result,
                reflection=payload.reflection,
                skills=[s.value for s in payload.skills],
                status=StoryStatus.DRAFT,
                source=StorySource.DEBRIEF_ANSWER,
                source_session_id=row.source_session_id,
                source_question_ref=row.source_question_ref,
                notes_json=[],
            )
            db.add(story)
            await db.flush()
            row.story_id = story.id
            out["story_id"] = story.id
            if payload.result:
                result_changed = story
        case SuggestionKind.MISSING_SKILL:
            skill = MissingSkillPayload.model_validate(row.payload)
            out["crafting"] = Crafting(competency=skill.competency, job_target_id=row.job_target_id)
        case SuggestionKind.STORY_IDEA:
            idea = StoryIdeaPayload.model_validate(row.payload)
            out["crafting"] = Crafting(achievement=idea.achievement, skills=idea.skills)
        case SuggestionKind.TAILOR_ROLE:
            tailor = TailorRolePayload.model_validate(row.payload)
            story = await _story(db, me, row.story_id)
            note = StoryNote(
                text=f"For {tailor.company}: {(body.after or tailor.note).strip()}", at=now
            )
            story.notes_json = [*(story.notes_json or []), note.model_dump(mode="json")]
            story.updated_at = now
            undo = {"story_id": str(story.id), "note": note.model_dump(mode="json")}
            out["story_id"] = story.id
        case SuggestionKind.IMPROVE_RESUME_LINE:
            line = ImproveResumeLinePayload.model_validate(row.payload)
            resume_row, resume = await _resume(db, me, row.resume_id)
            i, j = _line(resume, line.resume_line_ref)
            before = resume.roles[i].achievements[j]
            after = (body.after or line.after).strip()
            _set_line(resume_row, resume, i, j, after)
            undo = {
                "resume_id": str(resume_row.id),
                "ref": line.resume_line_ref,
                "line": [before, after],
            }
            out["resume_id"] = resume_row.id
        case SuggestionKind.REVIEW:
            review = ReviewPayload.model_validate(row.payload).review
            story = await _story(db, me, row.story_id)
            chosen = set(body.parts) if body.parts is not None else None
            parts: dict[str, list[str | None]] = {}
            for n in review.notes:
                if n.edit is None or (chosen is not None and n.part not in chosen):
                    continue
                before = getattr(story, n.part.value)
                setattr(story, n.part.value, n.edit.after)
                parts[n.part.value] = [before, n.edit.after]
            if parts:
                story.updated_at = now
                undo = {"story_id": str(story.id), "parts": parts}
                if StoryPart.RESULT.value in parts:
                    result_changed = story
            out["story_id"] = story.id
    row.status = SuggestionStatus.ACCEPTED
    row.resolved_at = now
    row.undo = undo
    await db.commit()
    await db.refresh(row)
    if row.kind == SuggestionKind.IMPROVE_RESUME_LINE and row.resume_id is not None:
        # RM-4: the story ideas follow the changed line.
        await queue.enqueue(
            STORY_IDEA_SKILLS,
            f"story_idea_skills:{row.resume_id}:{uuid.uuid4().hex[:8]}",
            resume_id=str(row.resume_id),
            org_id=str(me.org_id),
        )
    if result_changed is not None:
        await _queue_resume_line(queue, me, result_changed)
    return AcceptOut(suggestion=suggestion_out(row), can_undo=undo is not None, **out)


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(suggestion_id: uuid.UUID, db: Db, me: Me) -> Suggestion:
    """SG-8: dismissed suggestions never come back. 409 `not_open` when already resolved."""
    row = await _owned(db, me, suggestion_id)
    if row.status != SuggestionStatus.OPEN:
        raise _conflict(NOT_OPEN, "This suggestion was already accepted or dismissed.")
    row.status = SuggestionStatus.DISMISSED
    row.resolved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return suggestion_out(row)


@router.post("/suggestions/{suggestion_id}/undo")
async def undo_suggestion(suggestion_id: uuid.UUID, db: Db, me: Me) -> Suggestion:
    """SG-2: restore what accepting changed; the suggestion is open again. 409 `cannot_undo`
    when nothing was applied, `changed_since` when the text was edited after accepting."""
    row = await _owned(db, me, suggestion_id)
    undo = row.undo
    if row.status != SuggestionStatus.ACCEPTED or not undo:
        raise _conflict(CANNOT_UNDO, "There is nothing to undo.")
    now = datetime.now(UTC)
    if "parts" in undo:
        story = await _story(db, me, uuid.UUID(undo["story_id"]))
        parts: dict[str, list[str | None]] = undo["parts"]
        if any(getattr(story, part) != applied for part, (_b, applied) in parts.items()):
            raise _conflict(CHANGED, "The story changed after you accepted. Edit it instead.")
        for part, (before, _a) in parts.items():
            setattr(story, part, before)
        story.updated_at = now
    elif "note" in undo:
        story = await _story(db, me, uuid.UUID(undo["story_id"]))
        notes = list(story.notes_json or [])
        if undo["note"] in notes:
            notes.remove(undo["note"])
        story.notes_json = notes
        story.updated_at = now
    elif "line" in undo:
        resume_row, resume = await _resume(db, me, uuid.UUID(undo["resume_id"]))
        i, j = _line(resume, undo["ref"])
        before, applied = undo["line"]
        if resume.roles[i].achievements[j] != applied:
            raise _conflict(CHANGED, "The resume line changed after you accepted.")
        _set_line(resume_row, resume, i, j, before)
    row.status = SuggestionStatus.OPEN
    row.resolved_at = None
    row.undo = None
    await db.commit()
    await db.refresh(row)
    return suggestion_out(row)
