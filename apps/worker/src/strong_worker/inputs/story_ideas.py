"""RM-4: story ideas from a resume, and the worker job that adds their likely skills.

A story idea is one achievement in the parsed resume that no story uses. The list itself needs no
model call (the API builds it from the resume); `story_idea_skills` runs once per resume after it
is read or changed and stores the likely skills as open `story_idea` suggestions, one per
achievement. Until it finishes, or if it fails, the ideas list without skills.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.gateway import Message, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    Resume,
    StoryIdeaPayload,
    StoryIdeas,
    StoryPart,
    SuggestionKind,
    SuggestionStatus,
)
from strong_core.sim import gateway_for_org
from strong_worker.ops.context import job_context

log = logging.getLogger(__name__)

PROMPT = "story_idea_skills"


@dataclass(frozen=True)
class Achievement:
    ref: str
    """Where the line is in schemas.Resume: roles[<i>].achievements[<j>]."""
    text: str
    role: str
    """"Title, Company"."""


def achievements(resume: Resume) -> list[Achievement]:
    """Every non-empty achievement line, in resume order."""
    found = []
    for i, role in enumerate(resume.roles):
        for j, text in enumerate(role.achievements):
            if text.strip():
                found.append(
                    Achievement(
                        f"roles[{i}].achievements[{j}]",
                        text.strip(),
                        f"{role.title}, {role.company}",
                    )
                )
    return found


def normalize(text: str) -> str:
    """Achievements match by their text, ignoring case, spacing and end punctuation."""
    return re.sub(r"\s+", " ", text).strip().strip(".;").lower()


# Irregular past tenses that open resume lines in the first person ("Led", "Built", "Ran").
_IRREGULAR_PAST = {
    "led", "built", "ran", "wrote", "drove", "grew", "cut", "made", "took", "won", "set",
    "began", "brought", "sold", "taught", "kept", "found", "held", "spoke", "chose", "rebuilt",
    "rewrote", "overhauled", "oversaw", "undertook", "shut", "split", "spun", "put", "met",
}  # fmt: skip


def missing_parts(text: str) -> list[StoryPart]:
    """What a story built on this line still needs. A resume line rarely says why it mattered or
    what the user learned, so stakes and reflection are always missing. Action is missing too
    when the line does not open with a verb in the first person past tense ("Led", "Cut"), or
    say "I"."""
    words = re.findall(r"[A-Za-z']+", text)
    first = words[0].lower() if words else ""
    has_action = (
        first.endswith("ed") or first in _IRREGULAR_PAST or re.search(r"\bI\b", text) is not None
    )
    parts = [StoryPart.STAKES, StoryPart.REFLECTION]
    if not has_action:
        parts.insert(0, StoryPart.ACTION)
    return parts


def idea_reason(item: Achievement) -> str:
    return f"An achievement on your resume ({item.role}) that no story tells yet."


def build_messages(items: list[Achievement]) -> list[Message]:
    lines = json.dumps([i.text for i in items], ensure_ascii=False, indent=1)
    return [
        load_prompt(Role.EXTRACTOR, PROMPT).message("system"),
        load_prompt(Role.EXTRACTOR, f"{PROMPT}_input").message("user", achievements=lines),
    ]


async def add_story_idea_skills(ctx: dict[str, Any], resume_id: str, org_id: str) -> dict[str, Any]:
    """RM-4: one extractor call for the resume's achievements; stores the likely skills."""
    from strong_worker.inputs.jobs import _inputs  # imported here to avoid an import cycle

    inputs = _inputs(ctx)
    async with inputs.sessionmaker() as db:
        row = await db.scalar(
            select(ResumeRow).where(
                ResumeRow.id == uuid.UUID(resume_id), ResumeRow.org_id == uuid.UUID(org_id)
            )
        )
        if row is None or row.deleted_at is not None or row.parsed_json is None:
            return {"outcome": "failed", "reason": "resume not found or not read yet"}
        items = achievements(Resume.model_validate(row.parsed_json))
        if not items:
            return {"outcome": "done", "ideas": 0}
        try:
            gateway = await gateway_for_org(db, row.org_id, inputs.gateway)  # P13
            done = await gateway.complete(
                Role.EXTRACTOR, build_messages(items), output_type=StoryIdeas
            )
        except Exception as exc:  # the ideas still list, without skills
            log.warning("story idea skills failed for resume %s: %s", resume_id, exc)
            return {"outcome": "failed", "reason": f"{type(exc).__name__}"}
        skills = {normalize(i.achievement): i.skills for i in done.output.items}
        existing = {
            normalize(str(s.payload.get("achievement", ""))): s
            for s in await db.scalars(
                select(SuggestionRow).where(
                    SuggestionRow.org_id == row.org_id,
                    SuggestionRow.source_resume_id == row.id,
                    SuggestionRow.kind == SuggestionKind.STORY_IDEA,
                )
            )
        }
        stored = 0
        for item in items:
            found = skills.get(normalize(item.text))
            if found is None:
                continue
            payload = StoryIdeaPayload(
                achievement=item.text,
                role=item.role,
                resume_line_ref=item.ref,
                skills=list(dict.fromkeys(found)),
                missing_parts=missing_parts(item.text),
            ).model_dump(mode="json")
            old = existing.get(normalize(item.text))
            if old is not None:
                # Keep its status: a dismissed idea stays dismissed.
                old.payload = payload
                old.prompt_ref = ",".join(done.prompt_refs)
            else:
                db.add(
                    SuggestionRow(
                        org_id=row.org_id,
                        user_id=row.user_id,
                        kind=SuggestionKind.STORY_IDEA,
                        status=SuggestionStatus.OPEN,
                        source_resume_id=row.id,
                        resume_id=row.id,
                        payload=payload,
                        reason=idea_reason(item),
                        prompt_ref=",".join(done.prompt_refs),
                    )
                )
            stored += 1
        await db.commit()
        return {"outcome": "done", "ideas": stored}


@job_context()
async def story_idea_skills(ctx: dict[str, Any], resume_id: str, org_id: str) -> dict[str, Any]:
    """RM-4: the likely skills of a resume's story ideas, after it is read or changed."""
    return await add_story_idea_skills(ctx, resume_id, org_id)


async def queue_story_idea_skills(ctx: dict[str, Any], resume_id: str, org_id: str) -> None:
    """Queue the skills job after extraction. Outside a worker (tests call the input jobs with no
    Redis) it runs here instead. Never fails the extraction."""
    redis = ctx.get("redis")
    try:
        if redis is None:
            await add_story_idea_skills(ctx, resume_id, org_id)
        else:
            await redis.enqueue_job(
                "story_idea_skills",
                resume_id=resume_id,
                org_id=org_id,
                _job_id=f"story_idea_skills:{resume_id}:{uuid.uuid4().hex[:8]}",
            )
    except Exception as exc:  # story ideas are optional; the resume is read
        log.warning("could not run the story idea skills for %s: %s", resume_id, exc)
