"""Takes and story versions (CO-7, CO-8).

    POST /stories/{id}/takes            store one telling of the story and queue its scoring
    GET  /stories/{id}/takes            the story's takes, newest first, with their scores
    GET  /stories/{id}/takes/{take_id}  one take; poll it until it is scored
    POST /stories/{id}/versions         the coach's 60-second and full versions (CO-8)

A take is scored by the worker job `score_take` (strong_worker.scoring.takes) with the session
scorer, one answer on the story's skill tags. A take never changes the story's Draft or Proven
status (only ST-7 does) and never counts toward readiness: nothing here writes the story's status
or a progress snapshot.

Versions are written by the coach role and checked in code (strong_api.takes.versions); they are
returned, not stored.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.inputs.deps import Db, Me, Queue
from strong_api.inputs.queue import JobQueue
from strong_api.takes import versions as story_versions
from strong_api.takes.schemas import TakeOut, TakeRequest, TakeStatus
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Take
from strong_core.gateway import get_gateway
from strong_core.schemas import CompetencyScore, StoryVersions
from strong_core.sim import gateway_for_org

log = logging.getLogger(__name__)

# Name of the Arq function in strong_worker.scoring.takes. A test checks they stay in sync.
SCORE_TAKE = "score_take"

router = APIRouter(tags=["takes"])


def take_job_id(take_id: uuid.UUID) -> str:
    return f"take:{take_id}"


async def _owned_story(db: AsyncSession, me: Me, story_id: uuid.UUID) -> StoryRow:
    story = await db.scalar(
        select(StoryRow).where(
            StoryRow.id == story_id, StoryRow.org_id == me.org_id, StoryRow.user_id == me.user_id
        )
    )
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return story


async def take_out(queue: JobQueue, row: Take) -> TakeOut:
    scores: list[CompetencyScore] = []
    reason = None
    if row.skill_scores_json is not None:
        state = TakeStatus.SCORED
        scores = [CompetencyScore.model_validate(s) for s in row.skill_scores_json]
    else:
        info = await queue.info(take_job_id(row.id))
        failed = info.status == "failed" or (
            info.status == "complete" and (info.result or {}).get("outcome") == "failed"
        )
        state = TakeStatus.FAILED if failed else TakeStatus.SCORING
        if failed:
            reason = str((info.result or {}).get("reason") or "Scoring failed.")
    return TakeOut(
        id=row.id,
        story_id=row.story_id,
        channel=row.channel,
        text=row.text,
        duration_s=row.duration_s,
        status=state,
        scores=scores,
        reason=reason,
        created_at=row.created_at,
    )


async def _takes(db: AsyncSession, story: StoryRow) -> list[Take]:
    rows = await db.scalars(
        select(Take)
        .where(Take.story_id == story.id, Take.org_id == story.org_id)
        .order_by(Take.created_at.desc(), Take.id.desc())
    )
    return list(rows)


@router.post(
    "/stories/{story_id}/takes", status_code=status.HTTP_201_CREATED, response_model=TakeOut
)
async def create_take(
    story_id: uuid.UUID, body: TakeRequest, db: Db, me: Me, queue: Queue
) -> TakeOut:
    """CO-7: store a take and queue its scoring on the story's skills."""
    story = await _owned_story(db, me, story_id)
    if not story.skills:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Tag the story with at least one skill before practicing it.",
        )
    take = Take(
        id=uuid.uuid4(),
        org_id=me.org_id,
        user_id=me.user_id,
        story_id=story.id,
        channel=body.channel,
        text=body.text.strip(),
        duration_s=body.duration_s,
    )
    db.add(take)
    await db.commit()
    await queue.enqueue(
        SCORE_TAKE, take_job_id(take.id), take_id=str(take.id), org_id=str(me.org_id)
    )
    await db.refresh(take)
    return await take_out(queue, take)


@router.get("/stories/{story_id}/takes", response_model=list[TakeOut])
async def list_takes(story_id: uuid.UUID, db: Db, me: Me, queue: Queue) -> list[TakeOut]:
    story = await _owned_story(db, me, story_id)
    return [await take_out(queue, r) for r in await _takes(db, story)]


@router.get("/stories/{story_id}/takes/{take_id}", response_model=TakeOut)
async def get_take(
    story_id: uuid.UUID, take_id: uuid.UUID, db: Db, me: Me, queue: Queue
) -> TakeOut:
    story = await _owned_story(db, me, story_id)
    row = await db.scalar(
        select(Take).where(Take.id == take_id, Take.story_id == story.id, Take.org_id == me.org_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Take not found")
    return await take_out(queue, row)


@router.post("/stories/{story_id}/versions", response_model=StoryVersions)
async def create_versions(story_id: uuid.UUID, db: Db, me: Me) -> StoryVersions:
    """CO-8: a 60-second and a full version, every sentence from the story's parts or takes."""
    story = await _owned_story(db, me, story_id)
    takes = [t.text for t in reversed(await _takes(db, story))]  # oldest first
    if not story_versions.sources(story, takes):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The story has no parts or takes yet, so there is nothing to write from.",
        )
    gateway = await gateway_for_org(db, me.org_id, get_gateway())
    result = await story_versions.write_versions(gateway, story, takes)
    if result.versions is None:
        log.warning("story %s: versions rejected: %s", story.id, "; ".join(result.problems))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The coach could not write versions from your own words. Try again.",
        )
    return result.versions
