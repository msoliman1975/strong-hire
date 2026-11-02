"""The story page's outline actions (SC-10 to SC-13, D-2, D-10, D-11).

    PATCH /stories/{id}/outline                         SC-10: the user's inline slot edits
    POST  /stories/{id}/sections/{section}/improve       SC-11: Improve with Strova (a preview)
    POST  /stories/{id}/sections/{section}/improve/accept  SC-11: apply the accepted edits
    POST  /stories/{id}/organize                        SC-13: a classic story as a STAR preview
    POST  /stories/{id}/organize/accept                 SC-13: apply the preview
    POST  /stories/{id}/style                           SC-12: switch STAR and CARL
    POST  /stories/{id}/style/accept                    SC-12: apply a wording rewrite

Every write goes through `save_outline`, which renders the five legacy columns (SC-14), and
refreshes the story fit of the user's roles (ST-5) as a story edit does.

Strova's text is held to D-6 in code: a slot she writes is kept only when every quote is the
user's words and every number in its text is in its quotes. The user's words are what they said
in coach sessions on this story, the text of the story itself (the parts of a classic story, the
slots they typed, the quotes already in the outline) and, for an improve, their note. A preview
writes nothing; the accept endpoints check the same rules again, so an accepted edit can never
carry a fact the user did not give.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.coach import craft, engine
from strong_api.coach.facts import new_facts
from strong_api.inputs.deps import Db, Me, Queue
from strong_api.plan.story_fit import queue_story_fits_for_user
from strong_api.stories.outline import convert_style, load_outline, save_outline, strip_markdown
from strong_api.stories.router import _owned, story_out
from strong_api.stories.schemas import (
    ImproveAccept,
    ImproveIn,
    OutlinePatch,
    SlotEditIn,
    StoryOut,
    StyleIn,
    StyleSwitchOut,
)
from strong_core.db.models import CoachSession, CoachTurn
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Completion, Message, Role, get_gateway, usage_context
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    METRIC_SLOT,
    CoachSpeaker,
    OrganizeResult,
    OutlineSlot,
    ResultMetric,
    SectionImprove,
    SlotEdit,
    SlotStatus,
    StoryOutline,
    StoryPart,
    StorySection,
    StyleRewrite,
)
from strong_core.sim import gateway_for_org

log = logging.getLogger(__name__)

router = APIRouter(tags=["stories"])

STYLED = "styled_story"
CLASSIC = "classic_story"
NO_QUESTION = "What would you like this section to say that it does not say yet?"


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"code": code, "message": message})


def _styled(row: StoryRow) -> StoryOutline:
    outline = load_outline(row)
    if outline is None:
        raise _conflict(CLASSIC, "Organize this story into sections first.")
    return outline


def _invalid(error: ValidationError | ValueError) -> HTTPException:
    detail = error.errors() if isinstance(error, ValidationError) else str(error)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


async def _saved(db: Db, me: Me, queue: Queue, row: StoryRow, outline: StoryOutline) -> StoryOut:
    save_outline(row, outline)
    await db.commit()
    await db.refresh(row)
    await queue_story_fits_for_user(db, queue, me.org_id, me.user_id)  # ST-5
    return story_out(row)


# --- the user's words (D-6) --------------------------------------------------------------------


async def _session_words(db: AsyncSession, row: StoryRow) -> list[str]:
    texts = await db.scalars(
        select(CoachTurn.text)
        .join(CoachSession, CoachTurn.coach_session_id == CoachSession.id)
        .where(
            CoachTurn.org_id == row.org_id,
            CoachTurn.speaker == CoachSpeaker.CANDIDATE,
            CoachSession.story_id == row.id,
        )
    )
    return list(texts)


def _story_words(row: StoryRow, outline: StoryOutline | None) -> list[str]:
    words = [row.title]
    if outline is None:
        words.extend(t for p in StoryPart if (t := getattr(row, p.value)))
        return words
    for *_, slot in outline.iter_slots():
        if slot.status != SlotStatus.FILLED:
            continue
        if slot.by_user and slot.text:
            words.append(strip_markdown(slot.text))
        words.extend(slot.quotes)
    return words


async def _words(
    db: AsyncSession, row: StoryRow, outline: StoryOutline | None, *extra: str | None
) -> list[str]:
    return [
        *_story_words(row, outline),
        *(await _session_words(db, row)),
        *(e for e in extra if e and e.strip()),
    ]


def _said(words: Sequence[str]) -> str:
    return "\n".join(engine.normal(w) for w in words)


def _unbacked(text: str, quotes: Sequence[str], said: str, *numbers_in: str | None) -> str | None:
    """Why Strova's text is not the user's words, or None when every quote is found and every
    number is quoted (the CO-3 rules, SC-6)."""
    if not quotes:
        return "no quotes"
    for quote in quotes:
        if not engine.quote_found(quote, said):
            return f"quote not found: {quote[:80]!r}"
    quoted = " ".join(engine.normal(q) for q in quotes)
    claimed = " ".join(filter(None, (text, *numbers_in)))
    for number in engine.NUMBER.findall(claimed):
        if number not in quoted:
            return f"number not in the quotes: {number}"
    invented = new_facts(claimed, said)  # SC-15: facts, not wording
    if invented:
        return f"new fact: {invented[0]}"
    return None


def _render_said(words: Sequence[str]) -> str:
    seen: list[str] = []
    for w in words:
        flat = " ".join(w.split())
        if flat and flat not in seen:
            seen.append(flat[:2000])
    return "\n\n".join(seen) or "(nothing yet)"


async def _call[T: BaseModel](
    db: AsyncSession, row: StoryRow, messages: list[Message], output_type: type[T]
) -> T:
    """One coach-role call (the gateway validates the contract and retries once)."""
    gateway = await gateway_for_org(db, row.org_id, get_gateway())
    with usage_context(row.org_id):  # OB-2: role coach
        try:
            done: Completion[T] = await gateway.complete(
                Role.COACH, messages, output_type=output_type
            )
        except Exception:
            log.warning(
                "strova %s failed for story %s", output_type.__name__, row.id, exc_info=True
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Strova could not answer just now. Try again in a moment.",
            ) from None
    return done.output


# --- SC-10: inline edits ------------------------------------------------------------------------


def _user_slot(edit: SlotEditIn) -> OutlineSlot:
    text = (edit.text or "").strip()
    if edit.skipped:
        return OutlineSlot(status=SlotStatus.SKIPPED)
    if not text:
        return OutlineSlot()
    if edit.slot == METRIC_SLOT:
        return ResultMetric(
            text=text,
            by_user=True,
            status=SlotStatus.FILLED,
            before=(edit.before or "").strip() or None,
            after=(edit.after or "").strip() or None,
            unit=(edit.unit or "").strip() or None,
        )
    return OutlineSlot(text=text, by_user=True, status=SlotStatus.FILLED)


def apply_user_edits(outline: StoryOutline, patch: OutlinePatch) -> StoryOutline:
    """SC-10, D-10: the user's text goes in as typed (`by_user`, no quotes); a blank text empties
    the slot. Then the steps are reordered. Raises ValueError or ValidationError when the result
    is not a valid outline."""
    out = outline.model_copy(deep=True)
    for edit in patch.slots:
        target = craft.target_section(out, edit.section)
        if target is None or not craft.allowed(out, target, edit.slot):
            raise ValueError(f"{edit.section.value}.{edit.slot} is not a slot of this story")
        sec = out.section(target)
        if edit.step is not None and edit.step > len(sec.steps or []):
            raise ValueError("steps are added one at a time, at the end")
        craft.put(sec, edit.slot, edit.step, _user_slot(edit))
    if patch.steps is not None:
        action = out.section(StorySection.ACTION)
        current = action.steps or []
        if len(set(patch.steps)) != len(patch.steps) or not all(
            0 <= i < len(current) for i in patch.steps
        ):
            raise ValueError("steps must list existing step numbers, each once")
        action.steps = [current[i] for i in patch.steps]
    return StoryOutline.model_validate(out.model_dump())


@router.patch("/stories/{story_id}/outline")
async def edit_outline(
    story_id: uuid.UUID, body: OutlinePatch, db: Db, me: Me, queue: Queue
) -> StoryOut:
    """SC-10: set, clear, skip or reorder slots and steps, as the user typed them."""
    row = await _owned(db, me, story_id)
    try:
        outline = apply_user_edits(_styled(row), body)
    except (ValidationError, ValueError) as error:
        raise _invalid(error) from None
    return await _saved(db, me, queue, row, outline)


# --- SC-11: Improve with Strova -----------------------------------------------------------------


def checked_edits(
    outline: StoryOutline, section: StorySection, edits: Sequence[SlotEdit], said: str
) -> tuple[list[SlotEdit], list[str]]:
    """The edits of `section` that are the user's words, with `before` set from the story; and
    why the others were dropped."""
    kept: list[SlotEdit] = []
    dropped: list[str] = []
    for edit in edits:
        where = f"{edit.section.value}.{edit.slot}"
        target = craft.target_section(outline, edit.section)
        wanted = craft.target_section(outline, section)
        if target is None or target != wanted or not craft.allowed(outline, target, edit.slot):
            dropped.append(f"{where}: not a slot of this section")
            continue
        sec = outline.section(target)
        if edit.step is not None and edit.step > len(sec.steps or []):
            dropped.append(f"{where}: steps are added in order")
            continue
        current = craft.get(sec, edit.slot, edit.step)
        why = _unbacked(edit.after, edit.quotes, said)
        if why is not None:
            dropped.append(f"{where}: {why}")
            continue
        before = current.text if current.status == SlotStatus.FILLED else None
        kept.append(edit.model_copy(update={"section": target, "before": before}))
    return kept, dropped


def _improve_messages(
    outline: StoryOutline, section: StorySection, note: str | None, words: Sequence[str]
) -> list[Message]:
    return [
        load_prompt(Role.COACH, "improve_section").message("system"),
        load_prompt(Role.COACH, "improve_section_input").message(
            "user",
            story_style=craft.STYLE_NAMES[outline.style],
            section=f'"{section.value}" ({craft.SECTION_LABELS[section]})',
            outline=craft.render_outline(outline),
            note=(note or "").strip() or "(none)",
            said=_render_said(words),
        ),
    ]


@router.post("/stories/{story_id}/sections/{section}/improve")
async def improve_section(
    story_id: uuid.UUID, section: StorySection, body: ImproveIn, db: Db, me: Me
) -> SectionImprove:
    """SC-11: Strova's before-and-after edits for one section, from the user's words, or the
    questions to ask when facts are missing. Nothing is written until the user accepts."""
    row = await _owned(db, me, story_id)
    outline = _styled(row)
    if craft.target_section(outline, section) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This story has no such section")
    words = await _words(db, row, outline, body.note)
    raw = await _call(
        db, row, _improve_messages(outline, section, body.note, words), SectionImprove
    )
    kept, dropped = checked_edits(outline, section, raw.edits, _said(words))
    if dropped:
        log.warning("improve %s dropped edits: %s", row.id, "; ".join(dropped))
    questions = [q for q in raw.questions if q.strip()][:3]
    if not kept and not questions:
        questions = [NO_QUESTION]
    return SectionImprove(edits=kept, questions=questions)


@router.post("/stories/{story_id}/sections/{section}/improve/accept")
async def accept_improve(
    story_id: uuid.UUID, section: StorySection, body: ImproveAccept, db: Db, me: Me, queue: Queue
) -> StoryOut:
    """SC-11: apply the edits the user accepted. Each is checked again against the user's words;
    one that is not is refused (422), so nothing is half applied."""
    row = await _owned(db, me, story_id)
    outline = _styled(row)
    words = await _words(db, row, outline, body.note)
    kept, dropped = checked_edits(outline, section, body.edits, _said(words))
    if dropped:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, dropped)
    out = outline.model_copy(deep=True)
    for edit in kept:
        craft.put(
            out.section(edit.section),
            edit.slot,
            edit.step,
            craft.strova_slot(edit.slot, edit.after, edit.quotes),
        )
    try:
        out = StoryOutline.model_validate(out.model_dump())
    except ValidationError as error:
        raise _invalid(error) from None
    return await _saved(db, me, queue, row, out)


# --- SC-13: Organize with Strova ----------------------------------------------------------------


def checked_outline(
    outline: StoryOutline, said: str, fallback: StoryOutline | None = None
) -> tuple[StoryOutline, list[str]]:
    """Strova's outline with every filled slot backed by the user's words. A slot that is not is
    emptied, or taken from `fallback` (the same slot moved in code) when there is one."""
    out = outline.model_copy(deep=True)
    dropped: list[str] = []
    for section, key, step, slot in list(out.iter_slots()):
        if slot.status != SlotStatus.FILLED or slot.by_user:
            continue  # a slot the user typed is their own words
        extra = (slot.before, slot.after) if isinstance(slot, ResultMetric) else ()
        why = _unbacked(slot.text or "", slot.quotes, said, *extra)
        if why is None:
            continue
        dropped.append(f"{section.value}.{key}: {why}")
        replacement = OutlineSlot()
        if fallback is not None:
            replacement = craft.get(fallback.section(section), key, step)
        craft.put(out.section(section), key, step, replacement)
    return StoryOutline.model_validate(out.model_dump()), dropped


def _render_classic(row: StoryRow) -> str:
    lines = [f"Title: {row.title}"]
    for part in StoryPart:
        lines.append(f"{part.value}: {getattr(row, part.value) or '(empty)'}")
    return "\n".join(lines)


@router.post("/stories/{story_id}/organize")
async def organize_story(story_id: uuid.UUID, db: Db, me: Me) -> OrganizeResult:
    """SC-13, D-11: one model call sorts a classic story's words into STAR slots. A preview:
    nothing is written until the user accepts."""
    row = await _owned(db, me, story_id)
    if load_outline(row) is not None:
        raise _conflict(STYLED, "This story is already organized in sections.")
    words = await _words(db, row, None)
    messages = [
        load_prompt(Role.COACH, "organize").message("system"),
        load_prompt(Role.COACH, "organize_input").message(
            "user", story=_render_classic(row), said=_render_said(words)
        ),
    ]
    raw = await _call(db, row, messages, OrganizeResult)
    outline, dropped = checked_outline(raw.outline, _said(words))
    if dropped:
        log.warning("organize %s dropped slots: %s", row.id, "; ".join(dropped))
    return OrganizeResult(outline=outline)


@router.post("/stories/{story_id}/organize/accept")
async def accept_organize(
    story_id: uuid.UUID, body: OrganizeResult, db: Db, me: Me, queue: Queue
) -> StoryOut:
    """SC-13: apply the previewed outline. Its slots are checked again against the user's words;
    the story becomes STAR and its five parts are rendered from the outline (SC-14)."""
    row = await _owned(db, me, story_id)
    if load_outline(row) is not None:
        raise _conflict(STYLED, "This story is already organized in sections.")
    words = await _words(db, row, None)
    outline, dropped = checked_outline(body.outline, _said(words))
    if dropped:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, dropped)
    return await _saved(db, me, queue, row, outline)


# --- SC-12: Switch to STAR or CARL --------------------------------------------------------------


@router.post("/stories/{story_id}/style")
async def switch_style(
    story_id: uuid.UUID, body: StyleIn, db: Db, me: Me, queue: Queue
) -> StyleSwitchOut:
    """SC-12, D-2: without `rewrite`, rename and move the slots in code and save (no model call,
    no fact lost). With it, one model call rewrites the wording; that is a preview to accept."""
    row = await _owned(db, me, story_id)
    outline = _styled(row)
    moved = convert_style(outline, body.style)
    if not body.rewrite:
        if outline.style == body.style:
            return StyleSwitchOut(story=story_out(row))
        return StyleSwitchOut(story=await _saved(db, me, queue, row, moved))
    words = await _words(db, row, outline)
    messages = [
        load_prompt(Role.COACH, "rewrite_style").message("system"),
        load_prompt(Role.COACH, "rewrite_style_input").message(
            "user",
            story_style=craft.STYLE_NAMES[body.style],
            outline=json.dumps(moved.model_dump(mode="json", exclude_none=True), indent=1),
            said=_render_said(words),
        ),
    ]
    raw = await _call(db, row, messages, StyleRewrite)
    if raw.outline.style != body.style:
        return StyleSwitchOut(preview=moved)
    rewritten, dropped = checked_outline(raw.outline, _said(words), fallback=moved)
    if dropped:
        log.warning("rewrite %s kept the moved slots for: %s", row.id, "; ".join(dropped))
    return StyleSwitchOut(preview=_keep_typed(rewritten, moved))


def _keep_typed(rewritten: StoryOutline, moved: StoryOutline) -> StoryOutline:
    """A rewrite only rewords Strova's filled slots. A slot the user typed stays word for word,
    a skipped or empty slot stays as it was, and a filled slot the model emptied or skipped
    keeps its moved text."""
    out = rewritten.model_copy(deep=True)
    for section, key, step, slot in list(moved.iter_slots()):
        current = craft.get(out.section(section), key, step)
        reworded = (
            slot.status == SlotStatus.FILLED
            and not slot.by_user
            and current.status == SlotStatus.FILLED
        )
        if not reworded and current != slot:
            craft.put(out.section(section), key, step, slot)
    return StoryOutline.model_validate(out.model_dump())


@router.post("/stories/{story_id}/style/accept")
async def accept_style(
    story_id: uuid.UUID, body: StoryOutline, db: Db, me: Me, queue: Queue
) -> StoryOut:
    """SC-12: apply a previewed rewrite. Its slots are checked again against the user's words;
    a slot that is not keeps its moved text."""
    row = await _owned(db, me, story_id)
    outline = _styled(row)
    if body.style == outline.style:
        raise _conflict(STYLED, "The story is already in this style.")
    words = await _words(db, row, outline)
    moved = convert_style(outline, body.style)
    rewritten, dropped = checked_outline(body, _said(words), fallback=moved)
    if dropped:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, dropped)
    return await _saved(db, me, queue, row, _keep_typed(rewritten, moved))
