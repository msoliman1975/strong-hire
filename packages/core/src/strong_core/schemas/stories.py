"""Story library (ST-1), story fit (ST-5) and the deep story crafting outline (SC-1 to SC-13)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import (
    Competency,
    FlowFlagType,
    SlotStatus,
    StoryFitStrength,
    StoryPart,
    StorySection,
    StorySource,
    StoryStatus,
    StoryStyle,
)

STORY_TITLE_MAX_CHARS = 200

# --- Deep story crafting (RMAP-8): the outline, docs/story-crafting-spec.md "Sections and slots".

ACTION_STEPS_MAX = 5
"""SC-2: an Action section holds 1 to 5 steps."""

SKILL_HINTS_MAX = 3
"""SC-8, D-8: Strova offers at most three skill hints."""

STYLE_SECTIONS: dict[StoryStyle, tuple[StorySection, ...]] = {
    StoryStyle.STAR: (
        StorySection.SITUATION,
        StorySection.TASK,
        StorySection.ACTION,
        StorySection.RESULT,
        StorySection.LEARNING,
    ),
    StoryStyle.CARL: (
        StorySection.CHALLENGE,
        StorySection.ACTION,
        StorySection.RESULT,
        StorySection.LEARNING,
    ),
}
"""D-1: the sections of each style, in order."""

_CONTEXT_KEYS = ("org", "role", "scale", "timeframe", "problem", "constraints", "stakeholders")
_TASK_KEYS = ("goal", "success", "assigned_by")
_RESULT_KEYS = ("impact", "evidence", "recognition")
_LEARNING_KEYS = ("lesson", "differently", "since")

SECTION_SLOT_KEYS: dict[StoryStyle, dict[StorySection, tuple[str, ...]]] = {
    StoryStyle.STAR: {
        StorySection.SITUATION: _CONTEXT_KEYS,
        StorySection.TASK: _TASK_KEYS,
        StorySection.ACTION: (),
        StorySection.RESULT: _RESULT_KEYS,
        StorySection.LEARNING: _LEARNING_KEYS,
    },
    StoryStyle.CARL: {
        # In CARL the Task slots join Challenge, so switching styles moves and loses no fact.
        StorySection.CHALLENGE: (*_CONTEXT_KEYS, *_TASK_KEYS),
        StorySection.ACTION: (),
        StorySection.RESULT: _RESULT_KEYS,
        StorySection.LEARNING: _LEARNING_KEYS,
    },
}
"""SC-2: the named slots of each section, in display order. Action holds `steps` and Result also
holds `metric`; those two are fields of their own, not keys of `slots`."""

METRIC_SLOT = "metric"
"""The Result section's metric (ResultMetric), addressed by this key in updates and edits."""

STEP_FIELDS = ("did", "why", "alternatives", "people")
"""The slots of one action step (ActionStep), addressed with `step` set in updates and edits."""

CONTEXT_SLOTS = frozenset({"org", "role", "scale", "timeframe", "problem", "stakeholders"})
"""D-5: the context slots Strova presses for once each when they are empty."""

CORE_SLOTS = frozenset({"role", "problem", "did", "why", METRIC_SLOT, "lesson"})
"""D-4: the slots Ready needs. `did` and `why` count once at least one step has each."""


def section_slot_keys(section: StorySection) -> frozenset[str]:
    """Every slot key a section can address in any style, for refs that carry no style."""
    keys: set[str] = set()
    for by_section in SECTION_SLOT_KEYS.values():
        keys.update(by_section.get(section, ()))
    if section == StorySection.ACTION:
        keys.update(STEP_FIELDS)
    if section == StorySection.RESULT:
        keys.add(METRIC_SLOT)
    return frozenset(keys)


class OutlineSlot(Contract):
    """SC-2, D-6: one slot of the outline. A filled slot Strova wrote carries the candidate's
    verbatim `quotes`; a slot the candidate typed is `by_user` and needs none."""

    text: str | None = Field(default=None, description="Markdown. Set only when filled.")
    quotes: list[str] = Field(
        default_factory=list, description="The candidate's words this slot came from, verbatim."
    )
    by_user: bool = Field(default=False, description="True when the candidate typed the text.")
    status: SlotStatus = SlotStatus.EMPTY

    @model_validator(mode="after")
    def _check_slot(self) -> Self:
        if any(not q for q in self.quotes):
            raise ValueError("quotes must not be empty strings")
        if self.status == SlotStatus.FILLED:
            if not self.text:
                raise ValueError("a filled slot needs text")
            if not self.by_user and not self.quotes:
                raise ValueError("a slot Strova wrote needs quotes (CO-9, D-6)")
            if self.by_user and self.quotes:
                raise ValueError("a slot the candidate typed carries no quotes")
        elif self.text or self.quotes or self.by_user:
            raise ValueError("only a filled slot has text, quotes or by_user")
        return self


class ResultMetric(OutlineSlot):
    """SC-2: the Result section's metric. `text` says it in words; `before`, `after` and `unit`
    hold the numbers when the candidate gave them."""

    before: str | None = None
    after: str | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _check_numbers(self) -> Self:
        if self.status != SlotStatus.FILLED and (self.before or self.after or self.unit):
            raise ValueError("only a filled metric has before, after or unit")
        return self


class ActionStep(Contract):
    """SC-2: one action step. `did` and `why` are core (D-4); the other two are optional."""

    did: OutlineSlot | None = None
    why: OutlineSlot | None = None
    alternatives: OutlineSlot | None = None
    people: OutlineSlot | None = Field(default=None, description="How you brought people along.")

    def slot(self, name: str) -> OutlineSlot:
        """One of STEP_FIELDS by name; an empty slot when it has not been written yet."""
        if name not in STEP_FIELDS:
            raise ValueError(f"unknown step slot {name!r}")
        value: OutlineSlot | None = getattr(self, name)
        return value or OutlineSlot()


class OutlineSection(Contract):
    """SC-2: one section of the outline with its named slots. Missing keys are empty slots."""

    section: StorySection
    slots: dict[str, OutlineSlot] = Field(default_factory=dict)
    steps: list[ActionStep] | None = Field(
        default=None, description="Action only: 1 to 5 steps, in order."
    )
    metric: ResultMetric | None = Field(default=None, description="Result only.")

    def slot(self, key: str) -> OutlineSlot:
        """A named slot, or an empty one when the key has not been written yet."""
        if key == METRIC_SLOT and self.metric is not None:
            return self.metric
        return self.slots.get(key) or OutlineSlot()


class StoryOutline(Contract):
    """SC-2, D-3: the source of truth of a styled story. The five legacy columns are rendered
    from it in code (D-12, SC-14)."""

    style: StoryStyle
    sections: list[OutlineSection]

    @model_validator(mode="after")
    def _check_outline(self) -> Self:
        expected = STYLE_SECTIONS[self.style]
        got = tuple(s.section for s in self.sections)
        if got != expected:
            names = ", ".join(s.value for s in expected)
            raise ValueError(f"a {self.style.value} outline has the sections {names}, in order")
        allowed = SECTION_SLOT_KEYS[self.style]
        for sec in self.sections:
            unknown = set(sec.slots) - set(allowed[sec.section])
            if unknown:
                raise ValueError(
                    f"unknown slot {sorted(unknown)} in {sec.section.value} for {self.style.value}"
                )
            if sec.section == StorySection.ACTION:
                if sec.steps is None or not 1 <= len(sec.steps) <= ACTION_STEPS_MAX:
                    raise ValueError(f"the action section holds 1 to {ACTION_STEPS_MAX} steps")
            elif sec.steps is not None:
                raise ValueError("only the action section has steps")
            if sec.section == StorySection.RESULT:
                if sec.metric is None:
                    raise ValueError("the result section has a metric")
            elif sec.metric is not None:
                raise ValueError("only the result section has a metric")
        return self

    @classmethod
    def empty(cls, style: StoryStyle) -> StoryOutline:
        """A blank outline for a new styled story: every slot empty, one empty action step."""
        sections = [
            OutlineSection(
                section=section,
                steps=[ActionStep()] if section == StorySection.ACTION else None,
                metric=ResultMetric() if section == StorySection.RESULT else None,
            )
            for section in STYLE_SECTIONS[style]
        ]
        return cls(style=style, sections=sections)

    def section(self, key: StorySection) -> OutlineSection:
        for sec in self.sections:
            if sec.section == key:
                return sec
        raise KeyError(key.value)

    def iter_slots(self) -> Iterator[tuple[StorySection, str, int | None, OutlineSlot]]:
        """Every slot in display order as (section, key, step index or None, slot). Slots that
        have not been written come back as empty OutlineSlots."""
        for sec in self.sections:
            for key in SECTION_SLOT_KEYS[self.style][sec.section]:
                yield sec.section, key, None, sec.slot(key)
            if sec.metric is not None:
                yield sec.section, METRIC_SLOT, None, sec.metric
            for i, step in enumerate(sec.steps or ()):
                for name in STEP_FIELDS:
                    yield sec.section, name, i, step.slot(name)


class SlotRef(Contract):
    """Points at one slot: a named slot of a section, or a field of one action step."""

    section: StorySection
    slot: str = Field(min_length=1, description="A slot key, `metric`, or a step field.")
    step: int | None = Field(
        default=None, ge=0, lt=ACTION_STEPS_MAX, description="Action only: the step index."
    )

    @model_validator(mode="after")
    def _check_ref(self) -> Self:
        if self.slot not in section_slot_keys(self.section):
            raise ValueError(f"unknown slot {self.slot!r} in {self.section.value}")
        if (self.section == StorySection.ACTION) != (self.step is not None):
            raise ValueError("step is set exactly for action slots")
        return self


class SlotUpdate(SlotRef):
    """SC-6, D-6: new text for one slot from a crafting turn, backed by verbatim quotes."""

    text: str = Field(min_length=1, description="The slot, reworded from the candidate's words.")
    quotes: list[str] = Field(
        min_length=1, description="The candidate's words this slot came from, verbatim."
    )
    before: str | None = Field(default=None, description="Metric only.")
    after: str | None = Field(default=None, description="Metric only.")
    unit: str | None = Field(default=None, description="Metric only.")

    @model_validator(mode="after")
    def _check_metric_fields(self) -> Self:
        if self.slot != METRIC_SLOT and (self.before or self.after or self.unit):
            raise ValueError("before, after and unit belong to the metric only")
        if any(not q for q in self.quotes):
            raise ValueError("quotes must not be empty strings")
        return self


class SkillHint(Contract):
    """SC-8, D-8: "This story could also show {skill}", offered once the core slots are filled."""

    skill: Competency
    reason: str = Field(min_length=1, description="One sentence, from the story's own facts.")


class CraftReply(Contract):
    """SC-4 to SC-6: one Strova turn while crafting a styled story. It replaces CoachReply for
    styled stories. The engine names the section and slots; the reply fills only those."""

    message: str = Field(min_length=1, description="What Strova says: one question at a time.")
    slot_updates: list[SlotUpdate] = Field(default_factory=list)
    skips: list[SlotRef] = Field(
        default_factory=list, description="SC-5: slots the candidate asked to skip."
    )
    section_done: bool = Field(
        default=False, description="SC-5: the candidate said move on, or the section is complete."
    )
    skills: list[Competency] = Field(
        default_factory=list, description="Skills the story shows so far."
    )
    hints: list[SkillHint] = Field(default_factory=list, max_length=SKILL_HINTS_MAX)

    @model_validator(mode="after")
    def _check_reply(self) -> Self:
        updated = [_ref_key(u) for u in self.slot_updates]
        if len(updated) != len(set(updated)):
            raise ValueError("slot_updates must not repeat a slot")
        skipped = [_ref_key(s) for s in self.skips]
        if len(skipped) != len(set(skipped)):
            raise ValueError("skips must not repeat a slot")
        if set(updated) & set(skipped):
            raise ValueError("a slot cannot be both updated and skipped")
        if len(self.skills) != len(set(self.skills)):
            raise ValueError("skills must not repeat")
        hinted = [h.skill for h in self.hints]
        if len(hinted) != len(set(hinted)):
            raise ValueError("hints must not repeat a skill")
        return self


class FlowFlag(Contract):
    """SC-9, D-9: one advisory flow flag. `key` is stable for the same issue, so a dismissed
    flag stays dismissed until the slots it cites change."""

    key: str = Field(min_length=1, max_length=100)
    type: FlowFlagType
    slots: list[SlotRef] = Field(min_length=1, description="The slots the flag is about.")
    question: str = Field(min_length=1, description="What Strova would ask about it.")


class FlowCheck(Contract):
    """SC-9: the result of one flow check. No flags means the story hangs together."""

    flags: list[FlowFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        keys = [f.key for f in self.flags]
        if len(keys) != len(set(keys)):
            raise ValueError("flag keys must not repeat")
        return self


class SlotEdit(SlotRef):
    """SC-11, D-10: one before-and-after edit to a slot from Improve with Strova."""

    before: str | None = Field(default=None, description="The slot's text now; null if empty.")
    after: str = Field(min_length=1)
    quotes: list[str] = Field(
        min_length=1, description="The candidate's words the new text came from, verbatim."
    )


class SectionImprove(Contract):
    """SC-11: Improve with Strova for one section. Edits to accept or reject, or questions when
    the facts are missing; never neither."""

    edits: list[SlotEdit] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edits_or_questions(self) -> Self:
        if not self.edits and not self.questions:
            raise ValueError("an improve returns edits or questions")
        if any(not q for q in self.questions):
            raise ValueError("questions must not be empty strings")
        keys = [_ref_key(e) for e in self.edits]
        if len(keys) != len(set(keys)):
            raise ValueError("edits must not repeat a slot")
        return self


def _strova_wrote_every_slot(outline: StoryOutline) -> None:
    for section, key, _step, slot in outline.iter_slots():
        if slot.status == SlotStatus.FILLED and slot.by_user:
            raise ValueError(f"{section.value}.{key}: Strova's outline quotes every filled slot")


class OrganizeResult(Contract):
    """SC-13, D-11: a classic story sorted into STAR slots from the candidate's words only."""

    outline: StoryOutline

    @model_validator(mode="after")
    def _check_organize(self) -> Self:
        if self.outline.style != StoryStyle.STAR:
            raise ValueError("Organize with Strova builds a STAR outline")
        _strova_wrote_every_slot(self.outline)
        return self


class StyleRewrite(Contract):
    """SC-12, D-2: the outline in the other style with the wording rewritten, no new facts."""

    outline: StoryOutline

    @model_validator(mode="after")
    def _check_rewrite(self) -> Self:
        _strova_wrote_every_slot(self.outline)
        return self


def _ref_key(ref: SlotRef) -> tuple[StorySection, str, int | None]:
    return ref.section, ref.slot, ref.step


class StoryNote(Contract):
    """ST-6: a fix note sent to the story from a debrief answer that used it."""

    text: str = Field(min_length=1)
    session_id: UUID | None = Field(default=None, description="The debrief's session.")
    question_ref: str | None = Field(default=None, description="QuestionScore.question_ref.")
    at: datetime


class Story(Contract):
    """ST-1: one story in the user's library. The stories table holds org_id and user_id."""

    id: UUID
    title: str = Field(min_length=1, max_length=STORY_TITLE_MAX_CHARS)
    context: str | None = None
    stakes: str | None = None
    action: str | None = None
    result: str | None = None
    reflection: str | None = None
    skills: list[Competency] = Field(default_factory=list, description="Skill tags.")
    status: StoryStatus = StoryStatus.DRAFT
    source: StorySource
    source_session_id: UUID | None = Field(
        default=None, description="ST-2: the session of the debrief answer it came from."
    )
    source_question_ref: str | None = Field(
        default=None, description="ST-2: QuestionScore.question_ref of that answer."
    )
    notes: list[StoryNote] = Field(default_factory=list)
    style: StoryStyle | None = Field(
        default=None, description="SC-1: star or carl; null for a classic story (D-11)."
    )
    outline: StoryOutline | None = Field(
        default=None, description="SC-2: the outline of a styled story; null when classic."
    )
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _unique_skills(self) -> Story:
        if len(self.skills) != len(set(self.skills)):
            raise ValueError("skills must not repeat")
        if (self.style is None) != (self.outline is None):
            raise ValueError("a styled story has an outline and a classic story has none")
        if self.outline is not None and self.outline.style != self.style:
            raise ValueError("the outline's style must match the story's style")
        return self

    def part(self, name: StoryPart) -> str | None:
        """The text of one part, by StoryPart."""
        value: str | None = getattr(self, name.value)
        return value


class StoryFitItem(Contract):
    """ST-5: for one skill the interview will test, the best story and how well it fits."""

    competency: Competency
    story_id: UUID | None = Field(description="Null when no story fits (strength missing).")
    strength: StoryFitStrength
    reason: str = Field(min_length=1, description="One sentence the plan page shows.")

    @model_validator(mode="after")
    def _story_matches_strength(self) -> StoryFitItem:
        if (self.strength == StoryFitStrength.MISSING) != (self.story_id is None):
            raise ValueError("story_id is null exactly when strength is missing")
        return self


class StoryFit(Contract):
    """ST-5: the planner's story fit table, one item per tested skill."""

    items: list[StoryFitItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_item_per_skill(self) -> StoryFit:
        skills = [i.competency for i in self.items]
        if len(skills) != len(set(skills)):
            raise ValueError("items must have one entry per competency")
        return self
