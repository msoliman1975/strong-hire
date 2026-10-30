"""Story fit for the interview plan page (ST-5).

For each skill the interview will test, the best story from the user's library and whether it
is strong, thin or missing (schemas.StoryFit).

- `compute_story_fit` is the engine: one planner-role call (prompt planner/story_fit) for all
  skills, or, for a small-tier model (PL-5), one call per skill. Code then checks the reply:
  only the asked skills, only the user's own story ids, one item per skill. A skill the reply
  leaves out, or gives an unknown story, becomes "missing". With no stories there is no call.
- `run_story_fit` is the Arq job the plan API enqueues when the plan page asks. It reads the
  stories and the job, and skips the model when the cached result has the same input hash
  (same stories, skills, job, prompt and model). The result is cached in Redis under
  `story_fit_key` as a `StoryFitRecord`, with PL-6 provenance.

How the plan API uses it (S23, in strong_api/plan/):
    await queue.enqueue_job(
        "run_story_fit", org_id=..., job_target_id=..., competencies=[...],
        _job_id=story_fit_job_id(org_id, job_target_id),
    )
    then read story_fit_key(org_id, job_target_id) from Redis: StoryFitRecord JSON, or nothing
    yet. The record's input_hash changes when the stories or the job change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from strong_core.db.models import JobTarget
from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.registry import CapabilityTier
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    Competency,
    JobPosting,
    Story,
    StoryFit,
    StoryFitItem,
    StoryFitStrength,
)
from strong_core.sim import gateway_for_org
from strong_worker.gap.jobs import _gap
from strong_worker.quoting import quote_untrusted
from strong_worker.scoring.stories import load_user_stories, render_story, story_from_row
from strong_worker.suggestions.tailor import suggest_tailoring

log = logging.getLogger(__name__)

ROLE = Role.PLANNER
CACHE_TTL_S = 30 * 24 * 3600
MAX_STORIES = 30
NO_STORIES_REASON = "You have no stories yet. Add one that shows this skill."
NOT_COVERED_REASON = "None of your stories shows this skill yet."


def story_fit_key(org_id: uuid.UUID | str, job_target_id: uuid.UUID | str) -> str:
    """Redis key of the cached StoryFitRecord. The plan API reads the same key."""
    return f"story_fit:{org_id}:{job_target_id}"


def story_fit_job_id(org_id: uuid.UUID | str, job_target_id: uuid.UUID | str) -> str:
    """Arq job id, so two page loads at once run the job once."""
    return f"story-fit:{org_id}:{job_target_id}"


class StoryFitRecord(BaseModel):
    """The cached story fit with its provenance (PL-6)."""

    model_config = ConfigDict(extra="forbid")

    fit: StoryFit
    input_hash: str
    model_profile: str
    model_id: str | None = Field(description="Gateway alias; null when no call was needed.")
    prompt_version: str
    computed_at: datetime


@dataclass
class StoryFitResult:
    fit: StoryFit
    model_id: str | None
    prompt_version: str
    model_calls: int


def _prompt_ref(gateway: ModelGateway) -> str:
    return load_prompt(ROLE, "story_fit", tier=gateway.capabilities(ROLE).tier).ref


def story_fit_input_hash(
    stories: Sequence[Story],
    competencies: Sequence[Competency],
    job: str,
    prompt_version: str,
    model_id: str,
) -> str:
    """Changes when a story, the tested skills, the job, the prompt or the model changes."""
    payload = {
        "stories": sorted(
            (s.model_dump(mode="json", exclude={"notes", "status", "updated_at"}) for s in stories),
            key=lambda d: d["id"],
        ),
        "competencies": [c.value for c in competencies],
        "job": job,
        "prompt": prompt_version,
        "model": model_id,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _missing(competency: Competency, reason: str) -> StoryFitItem:
    return StoryFitItem(
        competency=competency, story_id=None, strength=StoryFitStrength.MISSING, reason=reason
    )


def clean_fit(
    reply: StoryFit, competencies: Sequence[Competency], story_ids: set[uuid.UUID]
) -> StoryFit:
    """One item per asked skill, in the asked order, with only the user's story ids."""
    got: dict[Competency, StoryFitItem] = {}
    for item in reply.items:
        if item.competency not in competencies or item.competency in got:
            continue
        if item.story_id is not None and item.story_id not in story_ids:
            continue  # an id the model invented
        got[item.competency] = item
    return StoryFit(items=[got.get(c) or _missing(c, NOT_COVERED_REASON) for c in competencies])


async def compute_story_fit(
    gateway: ModelGateway,
    stories: Sequence[Story],
    competencies: Sequence[Competency],
    job: str,
) -> StoryFitResult:
    """ST-5: the story fit table for these skills. Raises on a model or gateway failure."""
    competencies = list(dict.fromkeys(competencies))
    tier = gateway.capabilities(ROLE).tier
    system = load_prompt(ROLE, "story_fit", tier=tier)
    if not stories or not competencies:
        fit = StoryFit(items=[_missing(c, NO_STORIES_REASON) for c in competencies])
        return StoryFitResult(fit, None, system.ref, 0)
    user = load_prompt(ROLE, "story_fit_input", tier=tier)
    shown = list(stories)[:MAX_STORIES]
    library = "\n".join(render_story(str(s.id), s) for s in shown)
    ids = {s.id for s in shown}
    batches = [[c] for c in competencies] if tier == CapabilityTier.SMALL else [competencies]
    items: list[StoryFitItem] = []
    model_id: str | None = None
    for batch in batches:
        messages = [
            system.message("system"),
            user.message(
                "user",
                job=quote_untrusted(job) if job else "(not given)",
                skills="\n".join(f"- {c.value}" for c in batch),
                stories=library,
            ),
        ]
        done = await gateway.complete(ROLE, messages, output_type=StoryFit)
        model_id = done.model
        items += clean_fit(done.output, batch, ids).items
    return StoryFitResult(StoryFit(items=items), model_id, system.ref, len(batches))


# --- the job ---------------------------------------------------------------------------------


class StoryFitCache(Protocol):
    async def get(self, key: str) -> bytes | str | None: ...

    async def set(self, key: str, value: str, ex: int | None = None) -> Any: ...


def _job_text(target: JobTarget) -> str:
    parts: list[str] = []
    if target.parsed_json:
        try:
            posting = JobPosting.model_validate(target.parsed_json)
            parts.append(f"{posting.title} at {posting.company_name}")
        except ValidationError:
            pass
    if not parts and target.name:
        parts.append(target.name)
    return " ".join(parts)


def _cached(raw: bytes | str | None) -> StoryFitRecord | None:
    if raw is None:
        return None
    try:
        return StoryFitRecord.model_validate_json(raw)
    except ValidationError:
        return None


async def run_story_fit(
    ctx: dict[str, Any], org_id: str, job_target_id: str, competencies: list[str]
) -> dict[str, Any]:
    """Arq job: compute (or reuse) the story fit for one job and cache it."""
    gap = _gap(ctx)
    cache: StoryFitCache = ctx["redis"]
    org = uuid.UUID(org_id)
    wanted = [Competency(c) for c in competencies]
    async with gap.sessionmaker() as db:
        target = await db.scalar(
            select(JobTarget).where(
                JobTarget.id == uuid.UUID(job_target_id), JobTarget.org_id == org
            )
        )
        if target is None:
            return {"outcome": "failed", "reason": "job not found"}
        stories = [story_from_row(r) for r in await load_user_stories(db, org, target.user_id)]
        gateway = await gateway_for_org(db, org, gap.gateway)
    job = _job_text(target)
    prompt_version = _prompt_ref(gateway)
    input_hash = story_fit_input_hash(
        stories, wanted, job, prompt_version, gateway.config.roles[ROLE]
    )
    key = story_fit_key(org_id, job_target_id)
    previous = _cached(await cache.get(key))
    if previous is not None and previous.input_hash == input_hash:
        return {"outcome": "cached", "input_hash": input_hash, "model_calls": 0}
    try:
        result = await compute_story_fit(gateway, stories, wanted, job)
    except Exception as exc:  # the plan page keeps the last good table, or shows none
        log.warning("story fit failed for job %s: %s", job_target_id, exc)
        return {"outcome": "failed", "reason": f"Story fit failed: {type(exc).__name__}"}
    record = StoryFitRecord(
        fit=result.fit,
        input_hash=input_hash,
        model_profile=gateway.profile,
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        computed_at=datetime.now(UTC),
    )
    await cache.set(key, record.model_dump_json(), ex=CACHE_TTL_S)
    # SG-5: a new table gives each lead story a "For {company}" suggestion. Never fails the job.
    try:
        async with gap.sessionmaker() as db:
            tailoring = await suggest_tailoring(db, gateway, target, stories, result.fit, job)
    except Exception as exc:
        log.warning("tailoring failed for job %s: %s", job_target_id, exc)
        tailoring = {"tailor_errors": 1}
    return {
        "outcome": "computed",
        "input_hash": input_hash,
        "model_calls": result.model_calls,
        **tailoring,
    }


FUNCTIONS = [run_story_fit]
