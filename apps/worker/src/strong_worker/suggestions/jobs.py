"""Arq jobs for suggestions that start outside scoring.

- `suggest_resume_line` (SG-6): after a story gains a result with a number (the API queues it
  when a tune or new story suggestion is accepted, and U10's story editor may queue it on save).
  The line is the main resume's achievement that shares the most words with the story and has
  no number; the coach rewrites it from the story's words.
- `review_story` (ST-11): on request. Stores one open review suggestion for the story, replacing
  an older open one.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import delete, select

from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import TURN_ORDER
from strong_core.schemas import (
    ImproveResumeLinePayload,
    Resume,
    ReviewPayload,
    SuggestionKind,
    SuggestionStatus,
)
from strong_core.sim import gateway_for_org
from strong_worker.inputs.story_ideas import Achievement, achievements
from strong_worker.ops.context import job_context
from strong_worker.scoring.jobs import _ctx
from strong_worker.scoring.stories import answers_by_question, story_from_row
from strong_worker.suggestions import generate
from strong_worker.suggestions.facts import content_words, has_number
from strong_worker.suggestions.store import add_suggestion, payload_has

log = logging.getLogger(__name__)

MIN_SHARED_WORDS = 2


def best_line(items: list[Achievement], story_text: str) -> Achievement | None:
    """The achievement without a number that shares the most content words with the story."""
    words = set(content_words(story_text))
    best: tuple[int, Achievement] | None = None
    for item in items:
        if has_number(item.text):
            continue
        shared = len(words & set(content_words(item.text)))
        if shared >= MIN_SHARED_WORDS and (best is None or shared > best[0]):
            best = (shared, item)
    return best[1] if best else None


async def _story(db: Any, org_id: str, story_id: str) -> StoryRow | None:
    row: StoryRow | None = await db.scalar(
        select(StoryRow).where(
            StoryRow.id == uuid.UUID(story_id), StoryRow.org_id == uuid.UUID(org_id)
        )
    )
    return row


@job_context()
async def suggest_resume_line(ctx: dict[str, Any], org_id: str, story_id: str) -> dict[str, Any]:
    """SG-6: one improve resume line suggestion for the story, when a line fits."""
    scoring = _ctx(ctx)
    async with scoring.sessionmaker() as db:
        row = await _story(db, org_id, story_id)
        if row is None:
            return {"outcome": "failed", "reason": "story not found"}
        story = story_from_row(row)
        if not has_number(story.result):
            return {"outcome": "skipped", "reason": "the result has no number"}
        resume = await db.scalar(
            select(ResumeRow)
            .where(
                ResumeRow.org_id == row.org_id,
                ResumeRow.user_id == row.user_id,
                ResumeRow.deleted_at.is_(None),
                ResumeRow.parsed_json.is_not(None),
            )
            .order_by(ResumeRow.is_main.desc(), ResumeRow.uploaded_at.desc())
            .limit(1)
        )
        if resume is None or resume.parsed_json is None:
            return {"outcome": "skipped", "reason": "no resume"}
        text = " ".join(t for t in generate.story_words(story) if t)
        line = best_line(achievements(Resume.model_validate(resume.parsed_json)), text)
        if line is None:
            return {"outcome": "skipped", "reason": "no line fits"}
        gateway = await gateway_for_org(db, row.org_id, scoring.gateway)
        written = await generate.improve_resume_line(gateway, story, line.ref, line.text)
        if written.output is None:
            return {"outcome": "rejected", "problems": written.problems}
        added = await add_suggestion(
            db,
            org_id=row.org_id,
            user_id=row.user_id,
            kind=SuggestionKind.IMPROVE_RESUME_LINE,
            payload=ImproveResumeLinePayload(**written.output.model_dump()),
            reason=f"Your story “{story.title}” has a result this line does not show.",
            prompt_ref=written.prompt_ref,
            same=payload_has("resume_line_ref", line.ref),
            resume_id=resume.id,
            story_id=row.id,
        )
        await db.commit()
    return {"outcome": "added" if added else "exists", "model_calls": written.calls}


@job_context()
async def review_story(ctx: dict[str, Any], org_id: str, story_id: str) -> dict[str, Any]:
    """ST-11: Strova's review of one story, stored as an open review suggestion."""
    scoring = _ctx(ctx)
    async with scoring.sessionmaker() as db:
        row = await _story(db, org_id, story_id)
        if row is None:
            return {"outcome": "failed", "reason": "story not found"}
        story = story_from_row(row)
        said: list[str] = []
        if row.source_session_id is not None and row.source_question_ref:
            turns = await db.scalars(
                select(TurnRow)
                .where(TurnRow.session_id == row.source_session_id)
                .order_by(*TURN_ORDER)
            )
            answer = answers_by_question(list(turns)).get(row.source_question_ref)
            if answer:
                said.append(answer)
        gateway = await gateway_for_org(db, row.org_id, scoring.gateway)
        written = await generate.review_story(gateway, story, said)
        if written.output is None:
            return {"outcome": "failed", "problems": written.problems}
        await db.execute(
            delete(SuggestionRow).where(
                SuggestionRow.org_id == row.org_id,
                SuggestionRow.story_id == row.id,
                SuggestionRow.kind == SuggestionKind.REVIEW,
                SuggestionRow.status == SuggestionStatus.OPEN,
            )
        )
        db.add(
            SuggestionRow(
                org_id=row.org_id,
                user_id=row.user_id,
                kind=SuggestionKind.REVIEW,
                status=SuggestionStatus.OPEN,
                payload=ReviewPayload(review=written.output).model_dump(mode="json"),
                reason=written.output.summary,
                prompt_ref=written.prompt_ref,
                story_id=row.id,
            )
        )
        await db.commit()
    return {"outcome": "reviewed", "model_calls": written.calls}


FUNCTIONS = [suggest_resume_line, review_story]
