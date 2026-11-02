"""Story fit of a target role (ST-5): "Your stories for this role".

    GET /roles/{job_target_id}/story-fit                StoryFitView for the role
    GET /plan/{job_target_id}/{resume_id}/story-fit     the same, for the v1 plan page

The worker computes the table (strong_worker.gap.story_fit, Arq job `run_story_fit`) and stores
it on the role in Postgres (`role_story_fits`). It runs when the role's interviews are created
and when a story changes (`queue_story_fit`, `queue_story_fits_for_user`), so the page reads a
stored table and never waits for the model. Each read also enqueues the job, which does nothing
when the inputs are unchanged, to catch roles made another way. A table from before Postgres
storage is read from Redis. `computing` means there is no table yet; the page polls until there
is. The key and job id functions must match the worker's (a test checks this).

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
from strong_core.db.models import JobTarget, RoleStoryFit
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


async def role_skills(db: Db, target: JobTarget) -> list[Competency]:
    """The skills the role's story rounds test (see story_skills)."""
    profile = await resolve_profile(db, target.company_id)
    return story_skills(service.tested(profile, target))


async def queue_story_fit(db: Db, queue: Queue, target: JobTarget) -> None:
    """Compute the role's story fit in the background. Never fails the caller: a job already
    queued or a Redis outage only means the next read or change runs it."""
    if target.parsed_json is None or target.deleted_at is not None:
        return
    try:
        skills = await role_skills(db, target)
        await queue.enqueue(
            RUN_STORY_FIT,
            story_fit_job_id(target.org_id, target.id),
            org_id=str(target.org_id),
            job_target_id=str(target.id),
            competencies=[c.value for c in skills],
        )
    except Exception as exc:
        log.info("story fit not enqueued for job %s: %s", target.id, exc)


async def queue_story_fits_for_user(
    db: Db, queue: Queue, org_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """A story changed: refresh the story fit of each of the user's live roles."""
    targets = await db.scalars(
        select(JobTarget).where(
            JobTarget.org_id == org_id,
            JobTarget.user_id == user_id,
            JobTarget.deleted_at.is_(None),
            JobTarget.archived_at.is_(None),
        )
    )
    for target in list(targets):
        await queue_story_fit(db, queue, target)


async def _stored(db: Db, request: Request, target: JobTarget) -> CachedStoryFit | None:
    row = await db.scalar(select(RoleStoryFit).where(RoleStoryFit.job_target_id == target.id))
    if row is not None:
        try:
            return CachedStoryFit(
                fit=StoryFit.model_validate(row.fit_json), computed_at=row.computed_at
            )
        except ValidationError:
            log.warning("stored story fit for job %s does not validate", target.id)
    # A table stored before role_story_fits existed (the worker moves it on its next run).
    try:
        raw = await story_fit_cache(request).get(story_fit_key(target.org_id, target.id))
    except Exception as exc:
        log.info("story fit cache not read for job %s: %s", target.id, exc)
        return None
    return _parse(raw)


async def _view(db: Db, me: Me, queue: Queue, request: Request, target: JobTarget) -> StoryFitView:
    skills = await role_skills(db, target)
    await queue_story_fit(db, queue, target)
    cached = await _stored(db, request, target)
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


@router.get(
    "/roles/{job_target_id}/story-fit",
    responses={404: {"description": "The role does not exist."}},
)
async def get_role_story_fit(
    job_target_id: uuid.UUID, db: Db, me: Me, queue: Queue, request: Request
) -> StoryFitView:
    """ST-5: for each skill the role's interviews test, the best story and whether it is
    strong, thin or missing. Read from the role's stored table; never waits for the model."""
    target = await _owned_job_target(db, me, job_target_id)
    return await _view(db, me, queue, request, target)


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
    """ST-5: the role's story fit, for the v1 plan page (the resume only checks ownership)."""
    target = await _owned_job_target(db, me, job_target_id)
    await _owned_resume(db, me, resume_id)
    return await _view(db, me, queue, request, target)
