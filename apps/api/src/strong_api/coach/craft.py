"""Crafting a styled story, section by section (SC-3 to SC-6, D-2 to D-7), without HTTP, so the
text API and the voice agent's internal endpoint run the same code.

The engine, in code, decides what Strova asks about; the model only words the question and turns
the candidate's words into slot text:

1. The section in progress is `coach_sessions.section`. Sections run forward in the style's order
   (Situation or Challenge, then Task in STAR only, Action, Result, Learning). A section is
   skipped when it has nothing left to fill. When the last section is done, `section` is NULL and
   Strova asks whether to sharpen a section or finish.
2. Each section opens with one open question that can fill several slots (a fixed line). Strova
   then follows up once on each required or context slot that is still empty (D-5, D-7). The
   prompt gets only those slots, so it never asks out of order (SC-4); pressing once is in the
   prompt, which sees the conversation, as for IV-3 today.
3. "skip" or "I can't share that" marks the slot skipped, and a skipped slot is never asked about
   again. "move on" ends the section (SC-5). The model reports both; a short turn that is only
   "skip" or "move on" is also caught in code.
4. The model returns a CraftReply. A slot update is kept only when every quote is the candidate's
   own words and every number in its text is in its quotes (SC-6, CO-9), as for CO-3 today. A slot
   the candidate typed (`by_user`) is never overwritten by a turn.
5. Every outline write renders the five legacy columns (SC-14, `strong_api.stories.outline`).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.coach import engine
from strong_api.stories.outline import ready, save_outline, strip_markdown
from strong_core.db.models import CoachSession, CoachTurn
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Message, ModelGateway, Role, usage_context
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    ACTION_STEPS_MAX,
    CONTEXT_SLOTS,
    CORE_SLOTS,
    METRIC_SLOT,
    SECTION_SLOT_KEYS,
    STEP_FIELDS,
    STORY_SKILLS,
    STYLE_SECTIONS,
    ActionStep,
    AnswerConduct,
    CoachSessionStatus,
    CoachSpeaker,
    Competency,
    CraftReply,
    OutlineSection,
    OutlineSlot,
    ResultMetric,
    SlotRef,
    SlotStatus,
    SlotUpdate,
    StoryOutline,
    StorySection,
    StoryStyle,
)
from strong_interview.conduct import MAX_CONDUCT_WARNINGS

log = logging.getLogger(__name__)

# --- D-2: the style Strova suggests (code, no model) -----------------------------------------

CARL_SKILLS = frozenset(
    {
        Competency.CONFLICT_HANDLING,
        Competency.LEARNING_FROM_FAILURE,
        Competency.OWNERSHIP,
        Competency.JUDGMENT,
        Competency.PROBLEM_FRAMING,
    }
)
_CHALLENGE_QUESTION = re.compile(r"\bchallenge", re.IGNORECASE)


def suggest_style(target_skill: Competency | None, question: str | None = None) -> StoryStyle:
    """D-2: CARL for conflict, failure, ownership, judgment and problem framing, or when crafting
    starts from a "tell me about a challenge" question. STAR otherwise."""
    if target_skill in CARL_SKILLS:
        return StoryStyle.CARL
    if question and _CHALLENGE_QUESTION.search(question):
        return StoryStyle.CARL
    return StoryStyle.STAR


# --- labels and fixed lines ------------------------------------------------------------------

STYLE_NAMES = {
    StoryStyle.STAR: "STAR (Situation, Task, Action, Result, Learning)",
    StoryStyle.CARL: "CARL (Challenge, Action, Result, Learning)",
}
SECTION_LABELS = {
    StorySection.SITUATION: "Situation",
    StorySection.CHALLENGE: "Challenge",
    StorySection.TASK: "Task",
    StorySection.ACTION: "Action",
    StorySection.RESULT: "Result",
    StorySection.LEARNING: "Learning",
}
SLOT_LABELS = {
    "org": "Company and team",
    "role": "Your role at the time",
    "scale": "Scale (users, money, systems, team size)",
    "timeframe": "When, and how long",
    "problem": "The problem, and why it was hard",
    "constraints": "Constraints (deadline, budget, people, tech)",
    "stakeholders": "Stakeholders, and what each wanted",
    "goal": "Your goal or responsibility",
    "success": "What success looked like",
    "assigned_by": "Who gave it to you",
    "did": "What you did",
    "why": "Why you did it (the decision)",
    "alternatives": "The alternatives you weighed",
    "people": "How you brought people along",
    METRIC_SLOT: "A metric, before and after",
    "impact": "Business or customer impact",
    "evidence": "How you knew it worked",
    "recognition": "Recognition",
    "lesson": "The lesson",
    "differently": "What you'd do differently",
    "since": "Where you've used it since",
}

# D-7: each section opens with one open question that can fill several slots (fixed text).
SECTION_OPENERS = {
    StorySection.SITUATION: (
        "Tell me about one specific time at work: where you were, your role, and the problem "
        "you faced."
    ),
    StorySection.CHALLENGE: (
        "Tell me about one specific challenge at work: where you were, your role, and what made "
        "it hard."
    ),
    StorySection.TASK: "What were you responsible for, and what would success have looked like?",
    StorySection.ACTION: "Walk me through what you did, step by step, and why.",
    StorySection.RESULT: "What changed in the end? A number helps, if you have one.",
    StorySection.LEARNING: "Looking back, what did you learn?",
}
WRAP_LINE = "We've been through every section. Do you want to sharpen anything, or are you done?"

# The follow-up for one empty slot, used when the model call fails.
SLOT_QUESTIONS = {
    "org": "Which company and team was this?",
    "role": "What was your role at the time?",
    "scale": "How big was it, in users, money, systems or team size?",
    "timeframe": "When was this, and how long did it take?",
    "problem": "What was the problem, and why was it hard?",
    "stakeholders": "Who else had a stake in it, and what did each of them want?",
    "did": "What did you do yourself?",
    "why": "Why did you choose to do it that way?",
    METRIC_SLOT: "What changed in the end? A number helps, if you have one.",
    "lesson": "What did you learn from it?",
}

_OPEN_NEW = "Let's build one story together, from your own work, as {style}."
_OPEN_SKILL = "Let's build one story that shows {skill}, as {style}."
_OPEN_EXISTING = 'Let\'s work on "{title}".'
_OPEN_IDEA = 'Let\'s turn this resume line into a story, as {style}: "{line}".'

# SC-5: a short turn that only asks to skip the slot, or to move on.
_SKIP = re.compile(
    r"^(skip( it| this| that)?|pass|next question|i can'?t share( that| it)?|"
    r"i'?d rather not say|i'?d rather not share( that| it)?)[.!]?$",
    re.IGNORECASE,
)
_MOVE_ON = re.compile(
    r"^((let'?s |can we |please )?move on|next( section)?|skip( this| the)? section)[.!]?$",
    re.IGNORECASE,
)

# --- the section and the slots to ask about (SC-4, D-5, D-7) ---------------------------------


def _key(section: StorySection, slot: str, step: int | None) -> str:
    return f"{section.value}.{slot}" if step is None else f"{section.value}.{slot}[{step}]"


def _filled(slot: OutlineSlot | None) -> bool:
    return slot is not None and slot.status == SlotStatus.FILLED


def asks(outline: StoryOutline, section: StorySection) -> list[SlotRef]:
    """D-5, D-7: the required and context slots of `section` that are still empty (not filled,
    not skipped), in the spec table's order. Optional slots are filled only from the section's
    open question; they are never asked about one by one."""
    sec = outline.section(section)
    if section == StorySection.ACTION:
        steps = sec.steps or [ActionStep()]
        if not any(_filled(s.did) for s in steps):
            first = next((i for i, s in enumerate(steps) if not _is_skipped(s.did)), None)
            return [] if first is None else [SlotRef(section=section, slot="did", step=first)]
        if not any(_filled(s.why) for s in steps):
            first = next(
                (i for i, s in enumerate(steps) if _filled(s.did) and not _is_skipped(s.why)),
                None,
            )
            return [] if first is None else [SlotRef(section=section, slot="why", step=first)]
        return []
    out = []
    keys = (*SECTION_SLOT_KEYS[outline.style][section], METRIC_SLOT)
    for key in keys:
        if key == METRIC_SLOT and section != StorySection.RESULT:
            continue
        if key not in CORE_SLOTS and key not in CONTEXT_SLOTS:
            continue
        if sec.slot(key).status == SlotStatus.EMPTY:
            out.append(SlotRef(section=section, slot=key))
    return out


def _is_skipped(slot: OutlineSlot | None) -> bool:
    return slot is not None and slot.status == SlotStatus.SKIPPED


def has_room(outline: StoryOutline, section: StorySection) -> bool:
    """A section is worth opening when it has a slot to ask about, or (outside Action) any
    optional slot still empty for its open question to fill."""
    if asks(outline, section):
        return True
    if section == StorySection.ACTION:
        return False
    sec = outline.section(section)
    keys = SECTION_SLOT_KEYS[outline.style][section]
    if any(sec.slot(k).status == SlotStatus.EMPTY for k in keys):
        return True
    return section == StorySection.RESULT and sec.slot(METRIC_SLOT).status == SlotStatus.EMPTY


def next_section(outline: StoryOutline, after: StorySection | None) -> StorySection | None:
    """SC-4: the first section after `after` (or the first one) with room, in the style's order.
    Sections only move forward within a session; None means every section is done."""
    order = STYLE_SECTIONS[outline.style]
    start = 0 if after is None else order.index(after) + 1
    return next((s for s in order[start:] if has_room(outline, s)), None)


@dataclass(frozen=True)
class Ask:
    """What the engine has Strova ask about next."""

    section: StorySection | None  # None: every section is done; sharpen or finish
    slots: list[SlotRef]


def next_ask(outline: StoryOutline, section: StorySection | None) -> Ask:
    """SC-4: the section in progress and its empty slots, in the D-7 order."""
    if section is None:
        return Ask(section=None, slots=[])
    return Ask(section=section, slots=asks(outline, section))


def opener(
    story: StoryRow,
    outline: StoryOutline,
    section: StorySection | None,
    *,
    is_new: bool,
    target_skill: Competency | None,
    idea: str | None = None,
) -> str:
    """Strova's first line in a styled session: fixed text, no model call."""
    style = outline.style.value.upper()
    if idea is not None:
        lead = _OPEN_IDEA.format(style=style, line=idea)
    elif not is_new and target_skill is not None:
        # SC-8: Deepen opens a short session to show one more skill in this story.
        lead = f'Let\'s show {engine.skill_label(target_skill)} in "{story.title}".'
    elif not is_new:
        lead = _OPEN_EXISTING.format(title=story.title)
    elif target_skill is not None:
        lead = _OPEN_SKILL.format(skill=engine.skill_label(target_skill), style=style)
    else:
        lead = _OPEN_NEW.format(style=style)
    if section is None:
        return f"{lead} {WRAP_LINE}"
    started = any(
        slot.status != SlotStatus.EMPTY
        for sec, _key, _step, slot in outline.iter_slots()
        if sec == section
    )
    first = asks(outline, section)
    if started and first:  # an existing story: go straight to what the section still lacks
        return f"{lead} {SLOT_QUESTIONS[first[0].slot]}"
    return f"{lead} {SECTION_OPENERS[section]}"


def fixed_line(ask: Ask) -> str:
    """The question to ask without the model: the first empty slot, else the section's opener."""
    if ask.section is None:
        return WRAP_LINE
    if ask.slots:
        return SLOT_QUESTIONS[ask.slots[0].slot]
    return SECTION_OPENERS[ask.section]


# --- SC-6: merging a reply -------------------------------------------------------------------


def target_section(outline: StoryOutline, section: StorySection) -> StorySection | None:
    """The outline's section for a section the model named: Situation and Challenge are the same
    place, and in CARL the Task slots live in Challenge."""
    present = {s.section for s in outline.sections}
    if section in present:
        return section
    if section in (StorySection.SITUATION, StorySection.CHALLENGE, StorySection.TASK):
        return next(
            (s for s in (StorySection.SITUATION, StorySection.CHALLENGE) if s in present), None
        )
    return None


def allowed(outline: StoryOutline, section: StorySection, slot: str) -> bool:
    if section == StorySection.ACTION:
        return slot in STEP_FIELDS
    if section == StorySection.RESULT and slot == METRIC_SLOT:
        return True
    return slot in SECTION_SLOT_KEYS[outline.style][section]


@dataclass
class Applied:
    outline: StoryOutline
    kept: list[SlotUpdate] = field(default_factory=list)
    skipped: list[SlotRef] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # why updates were dropped


def _backed(update: SlotUpdate, said: str) -> str | None:
    for quote in update.quotes:
        if not engine.quote_found(quote, said):
            return f"quote not found: {quote[:80]!r}"
    quoted = " ".join(engine.normal(q) for q in update.quotes)
    numbers = " ".join(filter(None, (update.text, update.before, update.after)))
    for number in engine.NUMBER.findall(numbers):
        if number not in quoted:
            return f"number not in the quotes: {number}"
    return None


def get(sec: OutlineSection, slot: str, step: int | None) -> OutlineSlot:
    if step is not None:
        steps = sec.steps or []
        return steps[step].slot(slot) if step < len(steps) else OutlineSlot()
    return sec.slot(slot)


def put(sec: OutlineSection, slot: str, step: int | None, value: OutlineSlot) -> None:
    if step is not None:
        steps = sec.steps if sec.steps is not None else []
        while len(steps) <= step:
            steps.append(ActionStep())
        setattr(steps[step], slot, value)
        sec.steps = steps
    elif slot == METRIC_SLOT:
        sec.metric = ResultMetric.model_validate(value.model_dump())
    else:
        sec.slots[slot] = value


def apply(outline: StoryOutline, reply: CraftReply, said: str) -> Applied:
    """SC-5, SC-6: merge the reply's slot updates and skips into a copy of the outline. Keeps an
    update only when its quotes are the candidate's words (`said`, normalized) and its numbers
    are quoted; never overwrites a slot the candidate typed; skips only empty slots."""
    out = outline.model_copy(deep=True)
    applied = Applied(outline=out)
    for update in reply.slot_updates:
        where = _key(update.section, update.slot, update.step)
        target = target_section(out, update.section)
        if target is None or not allowed(out, target, update.slot):
            applied.dropped.append(f"{where}: not a slot of this {out.style.value} story")
            continue
        sec = out.section(target)
        if update.step is not None and update.step > len(sec.steps or []):
            applied.dropped.append(f"{where}: steps are added in order")
            continue
        if update.step is not None and update.step >= ACTION_STEPS_MAX:
            applied.dropped.append(f"{where}: at most {ACTION_STEPS_MAX} steps")
            continue
        if get(sec, update.slot, update.step).by_user:
            applied.dropped.append(f"{where}: the candidate typed this slot")
            continue
        why = _backed(update, said)
        if why is not None:
            applied.dropped.append(f"{where}: {why}")
            continue
        value = strova_slot(
            update.slot,
            update.text,
            update.quotes,
            before=update.before,
            after=update.after,
            unit=update.unit,
        )
        put(sec, update.slot, update.step, value)
        applied.kept.append(update)
    for ref in reply.skips:
        skip(applied, ref)
    applied.outline = StoryOutline.model_validate(out.model_dump())
    return applied


def strova_slot(
    slot: str,
    text: str,
    quotes: Sequence[str],
    *,
    before: str | None = None,
    after: str | None = None,
    unit: str | None = None,
) -> OutlineSlot:
    """A filled slot Strova wrote, with the user's verbatim quotes (D-6)."""
    if slot == METRIC_SLOT:
        return ResultMetric(
            text=text,
            quotes=list(quotes),
            status=SlotStatus.FILLED,
            before=before,
            after=after,
            unit=unit,
        )
    return OutlineSlot(text=text, quotes=list(quotes), status=SlotStatus.FILLED)


def skip(applied: Applied, ref: SlotRef) -> None:
    """SC-5: mark an empty slot skipped. A filled slot is left as it is."""
    target = target_section(applied.outline, ref.section)
    if target is None or not allowed(applied.outline, target, ref.slot):
        return
    sec = applied.outline.section(target)
    if ref.step is not None and ref.step >= len(sec.steps or []):
        return
    if get(sec, ref.slot, ref.step).status != SlotStatus.EMPTY:
        return
    put(sec, ref.slot, ref.step, OutlineSlot(status=SlotStatus.SKIPPED))
    applied.skipped.append(ref)


# --- the turn --------------------------------------------------------------------------------


def render_outline(outline: StoryOutline) -> str:
    lines = [f"Style: {STYLE_NAMES[outline.style]}"]
    for sec in outline.sections:
        lines.append(f'{SECTION_LABELS[sec.section]} (section "{sec.section.value}"):')
        for section, key, step, slot in outline.iter_slots():
            if section != sec.section:
                continue
            label = SLOT_LABELS[key] if step is None else f"Step {step + 1}, {SLOT_LABELS[key]}"
            ref = f'slot "{key}"' if step is None else f'slot "{key}", step {step}'
            if slot.status == SlotStatus.FILLED and slot.text:
                value = strip_markdown(slot.text)
            else:
                value = f"({slot.status.value})"
            lines.append(f"  {label} [{ref}]: {value}")
    return "\n".join(lines)


def _render_slots(slots: Sequence[SlotRef]) -> str:
    if not slots:
        return "(none: the open question covers this section)"
    return "\n".join(f"- {_slot_name(r)}: {SLOT_LABELS[r.slot]}" for r in slots)


def _slot_name(ref: SlotRef) -> str:
    return (
        f'section "{ref.section.value}", slot "{ref.slot}"'
        if ref.step is None
        else f'section "{ref.section.value}", slot "{ref.slot}", step {ref.step}'
    )


def _skipped(outline: StoryOutline) -> str:
    names = [
        SLOT_LABELS[key] if step is None else f"Step {step + 1}, {SLOT_LABELS[key]}"
        for _section, key, step, slot in outline.iter_slots()
        if slot.status == SlotStatus.SKIPPED
    ]
    return ", ".join(names) or "none"


def craft_messages(
    session: CoachSession,
    story: StoryRow,
    outline: StoryOutline,
    turns: Sequence[CoachTurn],
    answer: str,
    ask: Ask,
) -> list[Message]:
    """System and user messages for one crafting turn. The candidate's text is data only."""
    coach_style = load_prompt(Role.COACH, f"style_{session.style.value}").render()
    target = ", ".join(engine.skill_label(Competency(s)) for s in story.skills) or "none chosen"
    if ask.section is None:
        section = "none: every section is done"
        then = "nothing; ask whether they want to sharpen a section, or finish"
    else:
        section = f'"{ask.section.value}" ({SECTION_LABELS[ask.section]})'
        following = next_section(outline, ask.section)
        then = (
            f'the "{following.value}" section ({SECTION_LABELS[following]}); open it with '
            f"this question, in your own words: {SECTION_OPENERS[following]}"
            if following is not None
            else "nothing; every section is done, so ask whether they want to sharpen a "
            "section, or finish"
        )
    return [
        load_prompt(Role.COACH, "craft_turn").message(
            "system",
            style=coach_style,
            skills=", ".join(c.value for c in STORY_SKILLS),
        ),
        load_prompt(Role.COACH, "craft_turn_input").message(
            "user",
            story_style=STYLE_NAMES[outline.style],
            outline=render_outline(outline),
            target_skill=target,
            transcript=engine.render_transcript(turns),
            section=section,
            slots=_render_slots(ask.slots),
            skipped=_skipped(outline),
            then=then,
            hints=_hints_line(story, outline),
            answer=answer,
        ),
    ]


def _hints_line(story: StoryRow, outline: StoryOutline) -> str:
    """SC-8, D-8: hints are offered only once the core slots are filled."""
    if not ready(outline):
        return "not yet: the core slots are not all filled, so return no hints"
    shows = ", ".join(engine.skill_label(Competency(s)) for s in story.skills) or "none tagged"
    return (
        "the core slots are filled: you may list up to three other skills this story could also "
        f"show, from its own facts (it is already tagged with: {shows})"
    )


@dataclass
class CraftTurnResult:
    reply: CraftReply  # the kept updates and skips, the message as said
    ask: Ask  # what Strova asks about next
    outline: StoryOutline
    conduct: AnswerConduct = AnswerConduct.OK
    ended: bool = False
    dropped: list[str] = field(default_factory=list)
    turns: list[CoachTurn] = field(default_factory=list)


def _short(text: str) -> str:
    return " ".join(text.strip().split())


async def run_craft_turn(
    db: AsyncSession,
    gateway: ModelGateway,
    session: CoachSession,
    story: StoryRow,
    outline: StoryOutline,
    turns: list[CoachTurn],
    text: str,
    prompt_refs: set[str],
) -> CraftTurnResult:
    """One candidate turn on a styled story and Strova's reply. Saves both turns, the outline and
    the legacy columns; the caller commits."""
    asked = next((t.text for t in reversed(turns) if t.speaker == CoachSpeaker.COACH), "")
    ask = next_ask(outline, session.section)
    messages = craft_messages(session, story, outline, turns, text, ask)
    candidate = engine.add_turn(db, session, turns, CoachSpeaker.CANDIDATE, text)
    await db.flush()

    async def reply() -> CraftReply | None:
        try:
            done = await gateway.complete(Role.COACH, messages, output_type=CraftReply)
        except Exception:
            log.warning(
                "craft reply failed for %s; asking the fixed line", session.id, exc_info=True
            )
            return None
        prompt_refs.update(done.prompt_refs)
        return done.output

    with usage_context(session.org_id):  # OB-2: role coach; usage_events.session_id is NULL
        conduct, raw = await asyncio.gather(engine.check_turn(gateway, asked, text), reply())
    prompt_refs.add(load_prompt(Role.COACH, f"style_{session.style.value}").ref)

    if conduct != AnswerConduct.OK:
        count = engine.strikes(turns) + 1
        ended = count > MAX_CONDUCT_WARNINGS
        line = (
            engine.CLOSE_LINES[conduct]
            if ended
            else engine.warning_line(
                conduct, last=count == MAX_CONDUCT_WARNINGS, back_to=fixed_line(ask)
            )
        )
        coach = engine.add_turn(db, session, turns, CoachSpeaker.COACH, line)
        if ended:
            session.status = CoachSessionStatus.ENDED
            session.ended_at = datetime.now(UTC)
        return CraftTurnResult(
            reply=CraftReply(message=line),
            ask=ask,
            outline=outline,
            conduct=conduct,
            ended=ended,
            turns=[candidate, coach],
        )

    said = await engine.candidate_words(db, session)
    applied = apply(outline, raw or CraftReply(message=fixed_line(ask)), said)
    if applied.dropped:
        log.warning("craft %s dropped slot updates: %s", session.id, "; ".join(applied.dropped))
    short = _short(text)
    if ask.section is not None and ask.slots and _SKIP.match(short) and not applied.skipped:
        skip(applied, ask.slots[0])  # SC-5: a bare "skip" is about the slot just asked about
    moved_on = bool(_MOVE_ON.match(short)) or (raw is not None and raw.section_done)
    new_outline = applied.outline
    save_outline(story, new_outline)
    if raw is not None:
        story.skills = engine.merge_skills(story.skills, raw.skills)

    section = session.section
    advanced = False
    if section is not None and (moved_on or not asks(new_outline, section)):
        session.section = next_section(new_outline, section)
        advanced = True
    following = next_ask(new_outline, session.section)

    if raw is None or (advanced and not (raw is not None and raw.section_done)):
        # No model reply, or the engine moved on where the model did not: the fixed line for
        # what comes next, so Strova never asks about a section that is done.
        message = _fixed_after(following, advanced)
    else:
        message = engine.styled(engine.one_question(raw.message), session.style)
        if not message:
            message = fixed_line(following)
    coach = engine.add_turn(db, session, turns, CoachSpeaker.COACH, message)
    out = CraftReply(
        message=message,
        slot_updates=applied.kept,
        skips=applied.skipped,
        section_done=advanced,
        skills=[Competency(s) for s in story.skills],
        # SC-8: the model's hints as given; the router checks, orders and stores them.
        hints=raw.hints if raw is not None else [],
    )
    return CraftTurnResult(
        reply=out,
        ask=following,
        outline=new_outline,
        dropped=applied.dropped,
        turns=[candidate, coach],
    )


def _fixed_after(ask: Ask, advanced: bool) -> str:
    if ask.section is None:
        return WRAP_LINE
    if advanced:
        return SECTION_OPENERS[ask.section]
    return fixed_line(ask)


def start_section(outline: StoryOutline) -> StorySection | None:
    """The section a new styled session opens on."""
    return next_section(outline, None)
