"""Deep story crafting evals (SC-15, SC-4, SC-5, SC-9).

Three parts, all through the product's own code:

- **No new facts (SC-15, CO-9, SG-7).** Each case in `fixtures/crafting/cases.yaml` is a reply
  Strova could give, a crafting turn, an Improve, an Organize or a style rewrite, with the
  user's words. The product's check (`strong_api.coach.craft.apply`,
  `strong_api.stories.outline_api.checked_edits` / `checked_outline`) keeps or drops it. The
  check is on facts, not wording; the cases include tempting ones (a point inside a range, a
  hedge dropped, a tool or name the user never gave). Metric `crafting_invented_facts`: kept
  texts with a fact not in the user's words, plus cases with an unexpected result. Must be 0.
- **Depth (SC-4, SC-5, D-5, D-7).** Scripted sessions through the engine: every context slot of
  the opening section is asked about, a skipped slot is never asked again, and "move on" ends a
  section. Metric `crafting_depth_violations`. Must be 0.
- **Flow (SC-9).** Seeded stories: an incoherent one per flag type, and a coherent one. On the
  fake profile the model's flags are the case's, so the suite checks the product's flag filter
  keeps them; on a real profile the coach role runs `flow_check`. Metric
  `crafting_flow_recall`: flag types found over flag types seeded, with no flag on the coherent
  story. Must be 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from strong_api.coach import craft, engine
from strong_api.coach.facts import new_facts
from strong_api.stories.flow import checked_flags
from strong_api.stories.outline_api import checked_edits, checked_outline
from strong_core.gateway import ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    Contract,
    CraftReply,
    FlowCheck,
    FlowFlagType,
    OutlineSlot,
    SlotEdit,
    SlotRef,
    SlotStatus,
    StoryOutline,
    StorySection,
    StoryStyle,
)
from strong_evals import EVALS_DIR

CASES_FILE = EVALS_DIR / "fixtures" / "crafting" / "cases.yaml"
Kind = Literal["craft_turn", "improve", "organize", "rewrite", "flow"]


class CraftingCase(Contract):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Kind
    said: list[str] = Field(default_factory=list, description="The user's words.")
    section: StorySection | None = None
    style: StoryStyle = StoryStyle.STAR
    story: dict[str, str] = Field(default_factory=dict, description="Flow: slot -> text.")
    reply: dict[str, Any] = Field(default_factory=dict)
    expect: Literal["kept", "rejected"] | None = None
    expect_flags: list[FlowFlagType] = Field(default_factory=list)


def load_cases(path: Path = CASES_FILE) -> list[CraftingCase]:
    return [CraftingCase.model_validate(i) for i in yaml.safe_load(path.read_text("utf-8"))]


@dataclass
class CraftingResult:
    case: CraftingCase
    outcome: Literal["kept", "rejected"] | None = None
    texts: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    flags: list[FlowFlagType] = field(default_factory=list)
    error: str | None = None

    @property
    def as_expected(self) -> bool:
        if self.case.kind == "flow":
            return set(self.flags) == set(self.case.expect_flags)
        return self.outcome == self.case.expect


def _said(case: CraftingCase) -> str:
    return "\n".join(engine.normal(t) for t in case.said)


def _story(case: CraftingCase) -> StoryOutline:
    """A filled outline from `story`: keys `section.slot` (or `action.did.0`), user-typed."""
    data = StoryOutline.empty(case.style)
    for key, text in case.story.items():
        section, slot, *step = key.split(".")
        sec = data.section(StorySection(section))
        value = OutlineSlot(text=text, by_user=True, status=SlotStatus.FILLED)
        craft.put(sec, slot, int(step[0]) if step else None, value)
    return StoryOutline.model_validate(data.model_dump())


async def _flow(case: CraftingCase, gateway: ModelGateway) -> list[FlowFlagType]:
    outline = _story(case)
    if gateway.profile == "fake":
        check = FlowCheck.model_validate(case.reply)
    else:
        messages = [
            load_prompt(Role.COACH, "flow_check").message("system"),
            load_prompt(Role.COACH, "flow_check_input").message(
                "user",
                story_style=craft.STYLE_NAMES[outline.style],
                outline=craft.render_outline(outline),
            ),
        ]
        check = (await gateway.complete(Role.COACH, messages, output_type=FlowCheck)).output
    said = "\n".join(engine.normal(t) for t in case.story.values())
    return sorted({f.type for f in checked_flags(outline, check, said)})


def run_case_sync(case: CraftingCase) -> CraftingResult:
    """One no-new-facts case through the product's check."""
    result = CraftingResult(case)
    said = _said(case)
    if case.kind == "craft_turn":
        applied = craft.apply(
            StoryOutline.empty(case.style), CraftReply.model_validate(case.reply), said
        )
        result.texts = [u.text for u in applied.kept]
    elif case.kind == "improve":
        section = case.section or StorySection.SITUATION
        edits = [SlotEdit.model_validate(e) for e in case.reply.get("edits", [])]
        kept, _ = checked_edits(StoryOutline.empty(case.style), section, edits, said)
        result.texts = [e.after for e in kept]
    else:  # organize, rewrite
        outline = StoryOutline.model_validate(case.reply["outline"])
        fallback = StoryOutline.empty(outline.style) if case.kind == "rewrite" else None
        checked, _ = checked_outline(outline, said, fallback)
        result.texts = [
            s.text for *_, s in checked.iter_slots() if s.status == SlotStatus.FILLED and s.text
        ]
    result.outcome = "kept" if result.texts else "rejected"
    for text in result.texts:
        result.invented += new_facts(text, said)
    return result


async def run_case(case: CraftingCase, gateway: ModelGateway) -> CraftingResult:
    try:
        if case.kind == "flow":
            result = CraftingResult(case, flags=await _flow(case, gateway))
            result.outcome = "kept" if result.flags else "rejected"
            return result
        return run_case_sync(case)
    except Exception as exc:  # one case never stops the suite
        return CraftingResult(case, error=f"{type(exc).__name__}: {exc}")


def invented_facts(results: list[CraftingResult]) -> int:
    """SC-15: kept texts with a fact the user never gave, and cases with an unexpected result."""
    facts = [r for r in results if r.case.kind != "flow"]
    return sum(bool(r.invented) for r in facts) + sum(
        not r.as_expected for r in facts if r.error is None
    )


def flow_recall(results: list[CraftingResult]) -> float:
    """SC-9: seeded flag types found; a coherent story (no expected flags) must get none."""
    flows = [r for r in results if r.case.kind == "flow" and r.error is None]
    seeded = sum(len(r.case.expect_flags) for r in flows) or 1
    found = sum(len(set(r.flags) & set(r.case.expect_flags)) for r in flows)
    false_alarms = sum(1 for r in flows if not r.case.expect_flags and r.flags)
    return 0.0 if false_alarms else found / seeded


# --- depth (SC-4, SC-5): scripted sessions through the engine --------------------------------


def _fill(outline: StoryOutline, ref: SlotRef) -> StoryOutline:
    reply = CraftReply(
        message="Next?",
        slot_updates=[
            {
                "section": ref.section,
                "slot": ref.slot,
                "step": ref.step,
                "text": "my own words here",
                "quotes": ["my own words here"],
            }
        ],
    )
    return craft.apply(outline, reply, engine.normal("my own words here")).outline


def depth_violations() -> list[str]:
    """Scripted sessions: each context slot is asked, a skipped slot never returns, move on ends
    the section. Returns what went wrong; empty when the engine behaves."""
    problems: list[str] = []
    for style in StoryStyle:
        outline = StoryOutline.empty(style)
        opening = craft.start_section(outline)
        assert opening is not None
        asked: list[str] = []
        skipped = "scale"
        while True:
            ask = craft.next_ask(outline, opening)
            if not ask.slots:
                break
            ref = ask.slots[0]
            if ref.slot in asked:
                problems.append(f"{style.value}: {ref.slot} asked twice")
                break
            asked.append(ref.slot)
            if ref.slot == skipped:
                applied = craft.Applied(outline=outline.model_copy(deep=True))
                craft.skip(applied, ref)
                outline = applied.outline
            else:
                outline = _fill(outline, ref)
        for slot in ("org", "role", "scale", "timeframe", "problem", "stakeholders"):
            if slot not in asked:
                problems.append(f"{style.value}: context slot {slot} never asked")
        if skipped in [r.slot for r in craft.next_ask(outline, opening).slots]:
            problems.append(f"{style.value}: skipped slot asked again")
        # move on: the next section opens and the opening one is never returned to
        nxt = craft.next_section(outline, opening)
        seen = set()
        section = nxt
        while section is not None:
            if section == opening or section in seen:
                problems.append(f"{style.value}: went back to {section.value}")
                break
            seen.add(section)
            section = craft.next_section(outline, section)
    return problems
