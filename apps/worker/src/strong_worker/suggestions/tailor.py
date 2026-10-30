"""SG-5: tailor for a role. After story fit computes a new table for a role (ST-5), each skill's
lead story gets one note: the detail to bring forward for this company. Accepting adds it to the
story as a "For {company}" note. Never fails the story fit job."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import JobTarget
from strong_core.gateway import ModelGateway
from strong_core.schemas import JobPosting, Story, StoryFit, StoryFitStrength, SuggestionKind
from strong_worker.suggestions import generate
from strong_worker.suggestions.after_take import skill_label
from strong_worker.suggestions.store import add_suggestion, payload_has

log = logging.getLogger(__name__)

MAX_TAILOR = 3  # lead stories per role, strong ones first


def company_of(target: JobTarget) -> str | None:
    if target.parsed_json:
        try:
            return JobPosting.model_validate(target.parsed_json).company_name
        except ValidationError:
            return None
    return None


async def suggest_tailoring(
    db: AsyncSession,
    gateway: ModelGateway,
    target: JobTarget,
    stories: Sequence[Story],
    fit: StoryFit,
    job: str,
) -> dict[str, Any]:
    company = company_of(target)
    by_id = {s.id: s for s in stories}
    leads = sorted(
        (i for i in fit.items if i.story_id in by_id),
        key=lambda i: i.strength != StoryFitStrength.STRONG,
    )[:MAX_TAILOR]
    added = calls = errors = 0
    if company is None:
        return {"tailor_added": 0, "tailor_calls": 0, "tailor_errors": 0}
    for item in leads:
        assert item.story_id is not None
        story = by_id[item.story_id]
        try:
            written = await generate.tailor_role(gateway, story, job, company, item.competency)
        except Exception as exc:
            log.warning("tailoring for %s failed: %s", target.id, exc)
            errors += 1
            continue
        calls += written.calls
        if written.output is None:
            continue
        added += await add_suggestion(
            db,
            org_id=target.org_id,
            user_id=target.user_id,
            kind=SuggestionKind.TAILOR_ROLE,
            payload=written.output,
            reason=f"{story.title} leads for {skill_label(item.competency).lower()} at {company}.",
            prompt_ref=written.prompt_ref,
            same=payload_has("competency", item.competency.value),
            job_target_id=target.id,
            story_id=story.id,
        )
    await db.commit()
    return {"tailor_added": added, "tailor_calls": calls, "tailor_errors": errors}
