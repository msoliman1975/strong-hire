"""RM-4: story ideas from a resume, and the worker job that adds their likely skills.

A story idea is one achievement in the parsed resume that no story uses. The list itself needs no
model call (the API builds it from the resume); `story_idea_skills` runs once per resume after it
is read or changed and stores the likely skills as open `story_idea` suggestions, one per
achievement. Until it finishes, or if it fails, the ideas list without skills.

CS-2: the same job then matches the resume's lines with the user's earlier ideas (on other
resumes) and stories. A line with the same normalized text needs no call (the API pools those by
rule). For the others, one extractor call says which earlier idea or story describes the same
work: the line's suggestion gets `payload.same_as` (an idea) or `story_id` (a story). The match
is optional: when the call fails, the lines stay separate ideas.
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
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    IdeaMatches,
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
MATCH_PROMPT = "story_idea_match"
MAX_EARLIER = 60
"""CS-2: at most this many earlier ideas and stories go to one match call."""


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
        mine: list[tuple[Achievement, SuggestionRow]] = []
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
                # Keep its status: a dismissed idea stays dismissed. Keep its match too (CS-2).
                payload["same_as"] = old.payload.get("same_as")
                old.payload = payload
                old.prompt_ref = ",".join(done.prompt_refs)
                mine.append((item, old))
            else:
                new = SuggestionRow(
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
                db.add(new)
                mine.append((item, new))
            stored += 1
        await db.flush()
        matched = await match_ideas(db, gateway, row, mine)
        await db.commit()
        return {"outcome": "done", "ideas": stored, "matched": matched}


def _company(role: str | None) -> str:
    """The company of a "Title, Company" role, for comparing lines across resumes."""
    return (role or "").rsplit(",", 1)[-1].strip().lower()


def _story_line(story: StoryRow) -> str:
    said = story.result or story.action or story.context or ""
    return f"{story.title}: {' '.join(said.split())[:300]}".rstrip(": ")


def build_match_messages(
    lines: list[Achievement], earlier: list[tuple[str, str | None, str]]
) -> list[Message]:
    """`earlier` is (kind, role, text): kind is "resume line" or "story"."""
    new = [{"line": i, "role": a.role, "text": a.text} for i, a in enumerate(lines)]
    old = [
        {"item": j, "kind": kind, "role": role, "text": text}
        for j, (kind, role, text) in enumerate(earlier)
    ]
    return [
        load_prompt(Role.EXTRACTOR, MATCH_PROMPT).message("system"),
        load_prompt(Role.EXTRACTOR, f"{MATCH_PROMPT}_input").message(
            "user",
            lines=json.dumps(new, ensure_ascii=False, indent=1),
            earlier=json.dumps(old, ensure_ascii=False, indent=1),
        ),
    ]


async def match_ideas(
    db: Any,
    gateway: ModelGateway,
    row: ResumeRow,
    mine: list[tuple[Achievement, SuggestionRow]],
) -> int:
    """CS-2: link this resume's ideas to the same work on earlier resumes or in stories. Returns
    how many lines it matched. Never raises: a failed call leaves the lines unmatched."""
    others = list(
        await db.scalars(
            select(SuggestionRow)
            .where(
                SuggestionRow.org_id == row.org_id,
                SuggestionRow.user_id == row.user_id,
                SuggestionRow.kind == SuggestionKind.STORY_IDEA,
                SuggestionRow.source_resume_id != row.id,
            )
            .order_by(SuggestionRow.created_at, SuggestionRow.id)
        )
    )
    # The first suggestion of each idea stands for it; lines with the same text need no call.
    roots = sorted(
        (s for s in others if not s.payload.get("same_as")),
        key=lambda s: (s.created_at, str(s.payload.get("resume_line_ref") or "")),
    )
    root_texts = {normalize(str(s.payload.get("achievement", ""))) for s in others}
    todo = [
        (item, s)
        for item, s in mine
        if not s.payload.get("same_as")
        and s.story_id is None
        and normalize(item.text) not in root_texts
    ]
    if not todo:
        return 0
    companies = {_company(item.role) for item, _ in todo}
    ideas = [s for s in roots if _company(s.payload.get("role")) in companies]
    stories = list(
        await db.scalars(
            select(StoryRow)
            .where(StoryRow.org_id == row.org_id, StoryRow.user_id == row.user_id, StoryRow.live())
            .order_by(StoryRow.updated_at.desc(), StoryRow.id)
        )
    )
    targets: list[SuggestionRow | StoryRow] = [*ideas, *stories][:MAX_EARLIER]
    if not targets:
        return 0
    earlier: list[tuple[str, str | None, str]] = [
        ("resume line", t.payload.get("role"), str(t.payload.get("achievement", "")))
        if isinstance(t, SuggestionRow)
        else ("story", None, _story_line(t))
        for t in targets
    ]
    lines = [item for item, _ in todo]
    try:
        done = await gateway.complete(
            Role.EXTRACTOR, build_match_messages(lines, earlier), output_type=IdeaMatches
        )
    except Exception as exc:  # the lines stay separate ideas
        log.warning("story idea match failed for resume %s: %s", row.id, exc)
        return 0
    matched = 0
    for match in done.output.items:
        if match.same_as is None or not 0 <= match.line < len(todo):
            continue
        if match.same_as >= len(targets):
            continue
        item, suggestion = todo[match.line]
        target = targets[match.same_as]
        if isinstance(target, SuggestionRow):
            if _company(target.payload.get("role")) != _company(item.role):
                continue  # a different employer is never the same work
            suggestion.payload = {**suggestion.payload, "same_as": str(target.id)}
        else:
            suggestion.story_id = target.id
        matched += 1
    return matched


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
