"""Story fit table on the interview plan page (ST-5).

    GET /plan/{job_target_id}/{resume_id}/story-fit     StoryFitView for the job

The worker computes the table (strong_worker.gap.story_fit, Arq job `run_story_fit`) and caches
it in Redis as a StoryFitRecord. Each read enqueues the job, which skips the model when nothing
changed, and answers with the cached table, or `computing` while there is none yet. The page
polls until it is ready. The key and job id functions must match the worker's (a test checks
this).

The tested skills are the competencies of the story rounds (behavioral and hiring manager) that
are in the company's loop, or both of them when the loop has neither (generic mode). Technical
and case rounds are not answered with stories.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal, Protocol

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select

from strong_api.inputs.deps import Db, Me, Queue
from strong_api.inputs.router import _owned_job_target, _owned_resume
from strong_api.plan import service
from strong_api.plan.schemas import TypeWeights
from strong_core.config import get_settings
from strong_core.db.models import Story as StoryRow
from strong_core.profiles import resolve_profile
from strong_core.schemas import (
    Competency,
    InterviewType,
    StoryFit,
    StoryFitStrength,
    StoryStatus,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["interview plan"])

# Name of the Arq function in strong_worker.gap.story_fit. A test checks they stay in sync.
RUN_STORY_FIT = "run_story_fit"
STORY_ROUNDS = (InterviewType.BEHAVIORAL, InterviewType.HIRING_MANAGER)
DELETED_REASON = "The story that fit this skill was deleted."


def story_fit_key(org_id: uuid.UUID | str, job_target_id: uuid.UUID | str) -> str:
    """Redis key of the cached StoryFitRecord (same as the worker's)."""
    return f"story_fit:{org_id}:{job_target_id}"


def story_fit_job_id(org_id: uuid.UUID | str, job_target_id: uuid.UUID | str) -> str:
    """Arq job id, so two page loads at once run the job once (same as the worker's)."""
    return f"story-fit:{org_id}:{job_target_id}"


class CachedStoryFit(BaseModel):
    """The fields of the worker's StoryFitRecord that the page needs."""

    model_config = ConfigDict(extra="ignore")

    fit: StoryFit
    computed_at: datetime


class StoryFitCache(Protocol):
    async def get(self, key: str) -> bytes | str | None: ...


class RedisStoryFitCache:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def get(self, key: str) -> bytes | None:
        client: Redis = Redis.from_url(self._redis_url)
        try:
            value: bytes | None = await client.get(key)
            return value
        finally:
            await client.aclose()


def story_fit_cache(request: Request) -> StoryFitCache:
    """The app's cache reader. Tests set `app.state.story_fit_cache` to an in-memory one."""
    cache: StoryFitCache | None = getattr(request.app.state, "story_fit_cache", None)
    if cache is None:
        cache = RedisStoryFitCache(get_settings().redis_url)
        request.app.state.story_fit_cache = cache
    return cache


class StoryRef(BaseModel):
    id: uuid.UUID
    title: str
    status: StoryStatus


class StoryFitRow(BaseModel):
    """ST-5: one tested skill, its best story (none when missing) and how well it fits."""

    competency: Competency
    strength: StoryFitStrength
    story: StoryRef | None
    reason: str


class StoryFitView(BaseModel):
    status: Literal["ready", "computing"] = Field(
        description="computing until the worker has a table for every tested skill."
    )
    rows: list[StoryFitRow] = Field(description="One per tested skill, in display order.")
    computed_at: datetime | None


def story_skills(tested: list[TypeWeights]) -> list[Competency]:
    """The tested skills a story can show, highest weight first within each round: the story
    rounds in the loop, else both story rounds."""
    rounds = [t for t in tested if t.interview_type in STORY_ROUNDS]
    in_loop = [t for t in rounds if t.in_loop]
    skills: list[Competency] = []
    for t in in_loop or rounds:
        skills += [c.competency for c in t.competencies if c.competency not in skills]
    return skills


def _parse(raw: bytes | str | None) -> CachedStoryFit | None:
    if raw is None:
        return None
    try:
        return CachedStoryFit.model_validate_json(raw)
    except ValidationError:
        return None


@router.get(
    "/plan/{job_target_id}/{resume_id}/story-fit",
    responses={404: {"description": "The job target or the resume does not exist."}},
)
async def get_story_fit(
    job_target_id: uuid.UUID,
    resume_id: uuid.UUID,
    db: Db,
    me: Me,
    queue: Queue,
    request: Request,
) -> StoryFitView:
    """ST-5: for each skill the interview will test, the best story and whether it is strong,
    thin or missing."""
    target = await _owned_job_target(db, me, job_target_id)
    await _owned_resume(db, me, resume_id)
    profile = await resolve_profile(db, target.company_id)
    skills = story_skills(service.tested(profile, target))

    try:
        await queue.enqueue(
            RUN_STORY_FIT,
            story_fit_job_id(me.org_id, target.id),
            org_id=str(me.org_id),
            job_target_id=str(target.id),
            competencies=[c.value for c in skills],
        )
    except Exception as exc:  # already queued, or Redis is down: the cached table still shows
        log.info("story fit not enqueued for job %s: %s", target.id, exc)

    cached = _parse(await story_fit_cache(request).get(story_fit_key(me.org_id, target.id)))
    if cached is None:
        return StoryFitView(status="computing", rows=[], computed_at=None)

    stories = {
        r.id: r
        for r in await db.scalars(
            select(StoryRow).where(StoryRow.org_id == me.org_id, StoryRow.user_id == me.user_id)
        )
    }
    items = {i.competency: i for i in cached.fit.items}
    rows: list[StoryFitRow] = []
    for skill in skills:
        item = items.get(skill)
        if item is None:
            continue
        row = stories.get(item.story_id) if item.story_id else None
        if item.story_id is not None and row is None:
            rows.append(
                StoryFitRow(
                    competency=skill,
                    strength=StoryFitStrength.MISSING,
                    story=None,
                    reason=DELETED_REASON,
                )
            )
            continue
        rows.append(
            StoryFitRow(
                competency=skill,
                strength=item.strength,
                story=StoryRef(id=row.id, title=row.title, status=row.status) if row else None,
                reason=item.reason,
            )
        )
    done = len(rows) == len(skills)
    return StoryFitView(
        status="ready" if done else "computing", rows=rows, computed_at=cached.computed_at
    )
