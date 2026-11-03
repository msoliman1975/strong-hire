"""The flow check (SC-9, D-9) and skill hints (SC-8, D-8) of a styled story. Both are advisory:
neither changes the status.

    POST /stories/{id}/flow-check                  run the flow check now (one model call)
    POST /stories/{id}/flow-flags/{key}/dismiss    hide a flag until a slot it cites changes
    POST /stories/{id}/hints/{skill}/deepen        tag the skill; the UI opens a short session
    POST /stories/{id}/hints/{skill}/dismiss       Not now

`stories.flow_json` holds the last check: {"flags": [FlowFlag], "seen": {key: {slot: text}},
"dismissed": {key: {slot: text}}}. A flag shows unless it was dismissed and none of the slots it
cites has changed since. `stories.hints_json` holds the hints: [{"skill", "reason", "state"}],
state open, deepened or dismissed. At most three open hints show, the gap skills of the user's
target roles first (their story fit is missing or thin, ST-5).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.coach import craft, engine
from strong_api.coach.facts import new_facts
from strong_api.inputs.deps import Db, Me, Queue
from strong_api.plan.story_fit import queue_story_fits_for_user
from strong_api.stories.outline import load_outline, ready, strip_markdown
from strong_api.stories.schemas import StoryOut
from strong_core.db.models import CoachSession, CoachTurn, RoleStoryFit
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Role, get_gateway, usage_context
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    SKILL_HINTS_MAX,
    CoachSpeaker,
    Competency,
    FlowCheck,
    FlowFlag,
    SkillHint,
    SlotRef,
    SlotStatus,
    StoryFit,
    StoryFitStrength,
    StoryOutline,
)
from strong_core.sim import gateway_for_org

log = logging.getLogger(__name__)

router = APIRouter(tags=["stories"])

HINT_OPEN = "open"
HINT_DEEPENED = "deepened"
HINT_DISMISSED = "dismissed"


# --- the slots a flag cites -------------------------------------------------------------------


def slot_id(ref: SlotRef) -> str:
    return f"{ref.section.value}.{ref.slot}" + ("" if ref.step is None else f"[{ref.step}]")


def slot_text(outline: StoryOutline, ref: SlotRef) -> str | None:
    """The text of a cited slot now; None when the slot is not in this outline or is not filled."""
    target = craft.target_section(outline, ref.section)
    if target is None or not craft.allowed(outline, target, ref.slot):
        return None
    sec = outline.section(target)
    if ref.step is not None and ref.step >= len(sec.steps or []):
        return None
    slot = craft.get(sec, ref.slot, ref.step)
    return slot.text if slot.status == SlotStatus.FILLED else None


def _texts(outline: StoryOutline, flag: FlowFlag) -> dict[str, str | None]:
    return {slot_id(r): slot_text(outline, r) for r in flag.slots}


def visible_flags(row: StoryRow) -> list[FlowFlag]:
    """SC-9: the last check's flags, less the dismissed ones whose cited slots did not change."""
    outline = load_outline(row)
    data: dict[str, Any] = row.flow_json or {}
    if outline is None or not data:
        return []
    dismissed: dict[str, dict[str, str | None]] = data.get("dismissed", {})
    out = []
    for raw in data.get("flags", []):
        flag = FlowFlag.model_validate(raw)
        if flag.key in dismissed and dismissed[flag.key] == _texts(outline, flag):
            continue
        out.append(flag)
    return out


# --- SC-9: the flow check ---------------------------------------------------------------------


async def _said(db: AsyncSession, row: StoryRow, outline: StoryOutline) -> str:
    texts = await db.scalars(
        select(CoachTurn.text)
        .join(CoachSession, CoachTurn.coach_session_id == CoachSession.id)
        .where(
            CoachTurn.org_id == row.org_id,
            CoachTurn.speaker == CoachSpeaker.CANDIDATE,
            CoachSession.story_id == row.id,
        )
    )
    words = [*texts, row.title]
    for *_, slot in outline.iter_slots():
        if slot.status == SlotStatus.FILLED and slot.text:
            words.append(strip_markdown(slot.text))
            words.extend(slot.quotes)
    return "\n".join(engine.normal(w) for w in words)


def _invents(text: str, said: str) -> bool:
    """D-9, SC-15: a question or hint never suggests a fact: a number, name or tool the user
    never gave."""
    return bool(new_facts(text, said))


def checked_flags(outline: StoryOutline, check: FlowCheck, said: str) -> list[FlowFlag]:
    """Flags that cite filled slots of this story and whose question adds no number."""
    out = []
    for flag in check.flags:
        if any(slot_text(outline, r) is None for r in flag.slots):
            log.info("flow flag %s cites an empty or unknown slot; dropped", flag.key)
            continue
        if _invents(flag.question, said):
            log.info("flow flag %s suggests a number; dropped", flag.key)
            continue
        out.append(flag)
    return out


async def run_flow_check(db: AsyncSession, row: StoryRow) -> list[FlowFlag]:
    """One model call; stores the flags with the slot texts they saw and keeps the dismissed
    keys. Never raises: on a model failure the last check stays."""
    outline = load_outline(row)
    if outline is None:
        return []
    messages = [
        load_prompt(Role.COACH, "flow_check").message("system"),
        load_prompt(Role.COACH, "flow_check_input").message(
            "user",
            story_style=craft.STYLE_NAMES[outline.style],
            outline=craft.render_outline(outline),
        ),
    ]
    try:
        gateway = await gateway_for_org(db, row.org_id, get_gateway())
        with usage_context(row.org_id):  # OB-2: role coach
            done = await gateway.complete(Role.COACH, messages, output_type=FlowCheck)
    except Exception:
        log.warning("flow check failed for story %s", row.id, exc_info=True)
        return visible_flags(row)
    flags = checked_flags(outline, done.output, await _said(db, row, outline))
    old: dict[str, Any] = row.flow_json or {}
    row.flow_json = {
        "flags": [f.model_dump(mode="json") for f in flags],
        "seen": {f.key: _texts(outline, f) for f in flags},
        "dismissed": old.get("dismissed", {}),
        "prompt_ref": ",".join(sorted(done.prompt_refs)),
    }
    return visible_flags(row)


async def flow_check_if_ready(db: AsyncSession, row: StoryRow) -> None:
    """SC-9: the check runs once the core slots are filled (a craft turn, the end of a styled
    session, a review)."""
    outline = load_outline(row)
    if outline is not None and ready(outline):
        await run_flow_check(db, row)


# --- SC-8: skill hints ------------------------------------------------------------------------


async def gap_skills(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> list[Competency]:
    """ST-5: the skills of the user's target roles that no story covers well, missing first."""
    rows = await db.scalars(
        select(RoleStoryFit.fit_json).where(
            RoleStoryFit.org_id == org_id, RoleStoryFit.user_id == user_id
        )
    )
    missing: list[Competency] = []
    thin: list[Competency] = []
    for raw in rows:
        try:
            fit = StoryFit.model_validate(raw)
        except Exception:
            continue
        for item in fit.items:
            if item.strength == StoryFitStrength.MISSING and item.competency not in missing:
                missing.append(item.competency)
            elif item.strength == StoryFitStrength.THIN and item.competency not in thin:
                thin.append(item.competency)
    return [*missing, *(s for s in thin if s not in missing)]


def open_hints(row: StoryRow) -> list[SkillHint]:
    """SC-8: the open hints, in stored order (gaps first), at most three."""
    return [
        SkillHint(skill=h["skill"], reason=h["reason"])
        for h in (row.hints_json or [])
        if h.get("state") == HINT_OPEN
    ][:SKILL_HINTS_MAX]


def merge_hints(
    row: StoryRow, new: list[SkillHint], gaps: list[Competency], said: str
) -> list[SkillHint]:
    """SC-8, D-8: add the model's hints for skills the story is not tagged with and the user has
    not dismissed or deepened; a reason that adds a number is dropped. The open hints are ordered
    gap skills first (in gap order), then the rest, and capped at three."""
    known = {h["skill"]: h for h in (row.hints_json or [])}
    tagged = set(row.skills or [])
    for hint in new:
        skill = hint.skill.value
        if skill in known or skill in tagged or _invents(hint.reason, said):
            continue
        known[skill] = {"skill": skill, "reason": hint.reason, "state": HINT_OPEN}
    rank = {s.value: i for i, s in enumerate(gaps)}
    opened = [h for h in known.values() if h["state"] == HINT_OPEN]
    opened.sort(key=lambda h: rank.get(h["skill"], len(rank)))
    kept = opened[:SKILL_HINTS_MAX]
    closed = [h for h in known.values() if h["state"] != HINT_OPEN]
    row.hints_json = [*kept, *closed]
    return open_hints(row)


async def add_hints(db: AsyncSession, row: StoryRow, hints: list[SkillHint]) -> None:
    """Store the hints of a craft turn once the core slots are filled (SC-8)."""
    outline = load_outline(row)
    if outline is None or not ready(outline) or not hints:
        return
    gaps = await gap_skills(db, row.org_id, row.user_id)
    merge_hints(row, hints, gaps, await _said(db, row, outline))


def _set_hint(row: StoryRow, skill: Competency, state: str) -> None:
    hints = [dict(h) for h in (row.hints_json or [])]
    for h in hints:
        if h["skill"] == skill.value:
            h["state"] = state
            break
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such hint on this story")
    row.hints_json = hints


# --- endpoints --------------------------------------------------------------------------------


async def _story(db: Db, me: Me, story_id: uuid.UUID) -> StoryRow:
    from strong_api.stories.router import _owned

    row = await _owned(db, me, story_id)
    if load_outline(row) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "classic_story", "message": "Organize this story into sections first."},
        )
    return row


async def _out(db: Db, row: StoryRow) -> StoryOut:
    from strong_api.stories.router import story_out

    await db.commit()
    await db.refresh(row)
    return story_out(row)


@router.post("/stories/{story_id}/flow-check")
async def flow_check(story_id: uuid.UUID, db: Db, me: Me) -> StoryOut:
    """SC-9: check that the story hangs together. Advisory; the status never depends on it."""
    row = await _story(db, me, story_id)
    await run_flow_check(db, row)
    return await _out(db, row)


@router.post("/stories/{story_id}/flow-flags/{key}/dismiss")
async def dismiss_flag(story_id: uuid.UUID, key: str, db: Db, me: Me) -> StoryOut:
    """SC-9: hide a flag until one of the slots it cites changes."""
    row = await _story(db, me, story_id)
    outline = load_outline(row)
    assert outline is not None
    data: dict[str, Any] = dict(row.flow_json or {})
    flag = next((f for f in data.get("flags", []) if f.get("key") == key), None)
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such flag on this story")
    dismissed = dict(data.get("dismissed", {}))
    dismissed[key] = _texts(outline, FlowFlag.model_validate(flag))
    row.flow_json = {**data, "dismissed": dismissed}
    return await _out(db, row)


@router.post("/stories/{story_id}/hints/{skill}/deepen")
async def deepen_hint(
    story_id: uuid.UUID, skill: Competency, db: Db, me: Me, queue: Queue
) -> StoryOut:
    """SC-8, D-8: Deepen tags the story with the skill; the UI opens a short session with Strova
    on this story for it (POST /coach/sessions with story_id and target_skill)."""
    row = await _story(db, me, story_id)
    _set_hint(row, skill, HINT_DEEPENED)
    row.skills = engine.merge_skills(row.skills or [], [skill])
    out = await _out(db, row)
    await queue_story_fits_for_user(db, queue, me.org_id, me.user_id)  # ST-5
    return out


@router.post("/stories/{story_id}/hints/{skill}/dismiss")
async def dismiss_hint(story_id: uuid.UUID, skill: Competency, db: Db, me: Me) -> StoryOut:
    """SC-8: Not now. The hint does not come back."""
    row = await _story(db, me, story_id)
    _set_hint(row, skill, HINT_DISMISSED)
    return await _out(db, row)
