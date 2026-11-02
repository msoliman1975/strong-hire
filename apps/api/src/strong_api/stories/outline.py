"""The outline of a styled story (SC-2), in code with no model: Ready (SC-3) and the legacy columns
rendered from it (SC-14, D-12).

A styled story keeps its outline in `stories.outline_json`; the outline is the source of truth.
Every outline write goes through `save_outline`, which renders `context`, `stakes`, `action`,
`result` and `reflection` as plain text with the Markdown stripped. So the interviewer, the scorer,
story fit, debrief notes, suggestions and versions keep reading the same five columns as today.
"""

from __future__ import annotations

from strong_api.markdown import SENTENCE_END
from strong_api.markdown import strip_markdown as strip_markdown  # re-exported for the routers
from strong_core.db.models import Story as StoryRow
from strong_core.schemas import (
    METRIC_SLOT,
    SECTION_SLOT_KEYS,
    STYLE_SECTIONS,
    OutlineSection,
    OutlineSlot,
    SlotStatus,
    StoryOutline,
    StoryPart,
    StorySection,
    StoryStyle,
)

# SC-14: which slots each legacy column is rendered from, in order. The first section that
# exists in the outline's style is used (Situation in STAR, Challenge in CARL; the Task slots sit
# in Task for STAR and in Challenge for CARL).
_OPENING = (StorySection.SITUATION, StorySection.CHALLENGE)
_TASK = (StorySection.TASK, StorySection.CHALLENGE)
LEGACY_MAP: dict[StoryPart, tuple[tuple[tuple[StorySection, ...], str], ...]] = {
    StoryPart.CONTEXT: tuple(
        (_OPENING, key)
        for key in ("org", "role", "scale", "timeframe", "constraints", "stakeholders")
    ),
    StoryPart.STAKES: ((_OPENING, "problem"), (_TASK, "goal"), (_TASK, "success")),
    # StoryPart.ACTION is the steps, each as "did, because why".
    StoryPart.RESULT: (
        ((StorySection.RESULT,), METRIC_SLOT),
        ((StorySection.RESULT,), "impact"),
        ((StorySection.RESULT,), "evidence"),
    ),
    StoryPart.REFLECTION: (
        ((StorySection.LEARNING,), "lesson"),
        ((StorySection.LEARNING,), "differently"),
        ((StorySection.LEARNING,), "since"),
    ),
}


def _sentence(text: str) -> str:
    text = strip_markdown(text)
    return text if not text or text.endswith(SENTENCE_END) else f"{text}."


def _section(outline: StoryOutline, keys: tuple[StorySection, ...]) -> OutlineSection | None:
    present = {s.section: s for s in outline.sections}
    return next((present[k] for k in keys if k in present), None)


def _text(outline: StoryOutline, keys: tuple[StorySection, ...], slot: str) -> str | None:
    section = _section(outline, keys)
    if section is None:
        return None
    value = section.slot(slot)
    if value.status != SlotStatus.FILLED or not value.text:
        return None
    return value.text


# Words that start a "why" sentence and read lower case after "because". A name ("Acme had
# no fallback") or "I" keeps its capital.
_LOWER_OPENERS = frozenset(
    [
        "a",
        "an",
        "the",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "there",
        "they",
        "their",
        "we",
        "our",
        "us",
        "my",
        "he",
        "she",
        "if",
        "when",
        "without",
        "with",
        "otherwise",
        "so",
        "to",
        "every",
        "each",
        "most",
        "no",
        "nothing",
        "one",
        "our",
    ]
)


def _lower_first(text: str) -> str:
    """'A small slice' -> 'a small slice'; 'I split', 'Acme had' and 'AWS was' stay."""
    first = text.split(" ", 1)[0]
    if first.lower() in _LOWER_OPENERS and first[:1].isupper():
        return text[0].lower() + text[1:]
    return text


def _step(did: str | None, why: str | None) -> str | None:
    if did and why:
        head = strip_markdown(did).rstrip(" .;,")
        return f"{head}, because {_lower_first(_sentence(why))}"
    if did or why:
        return _sentence(did or why or "")
    return None


def render_legacy(outline: StoryOutline) -> dict[StoryPart, str | None]:
    """SC-14, D-12: the five legacy columns from the outline, plain text, None when empty."""
    out: dict[StoryPart, str | None] = {}
    for part in StoryPart:
        if part == StoryPart.ACTION:
            action = outline.section(StorySection.ACTION)
            pieces = [_step(_filled(step.did), _filled(step.why)) for step in action.steps or []]
        else:
            pieces = [
                _sentence(text)
                for keys, slot in LEGACY_MAP[part]
                if (text := _text(outline, keys, slot))
            ]
        joined = " ".join(p for p in pieces if p)
        out[part] = joined or None
    return out


def _filled(slot: OutlineSlot | None) -> str | None:
    if slot is None or slot.status != SlotStatus.FILLED:
        return None
    return slot.text or None


def ready(outline: StoryOutline) -> bool:
    """SC-3, D-4: Ready when every core slot is filled: your role, the problem, at least one
    action step with what you did and at least one with why, the metric, and the lesson. The
    optional slots never block it."""
    opening = _section(outline, _OPENING)
    if opening is None:
        return False
    steps = outline.section(StorySection.ACTION).steps or []
    return (
        all(opening.slot(k).status == SlotStatus.FILLED for k in ("role", "problem"))
        and any(_filled(s.did) for s in steps)
        and any(_filled(s.why) for s in steps)
        and outline.section(StorySection.RESULT).slot(METRIC_SLOT).status == SlotStatus.FILLED
        and outline.section(StorySection.LEARNING).slot("lesson").status == SlotStatus.FILLED
    )


def has_content(outline: StoryOutline) -> bool:
    """True when any slot is filled."""
    return any(slot.status == SlotStatus.FILLED for *_, slot in outline.iter_slots())


def load_outline(row: StoryRow) -> StoryOutline | None:
    """The outline of a styled story; None for a classic one."""
    if row.style is None or row.outline_json is None:
        return None
    return StoryOutline.model_validate(row.outline_json)


def save_outline(row: StoryRow, outline: StoryOutline) -> None:
    """Every outline write: store the outline and render the legacy columns from it (SC-14)."""
    row.style = outline.style
    row.outline_json = outline.model_dump(mode="json", exclude_none=True)
    for part, text in render_legacy(outline).items():
        setattr(row, part.value, text)


# --- SC-12: switching style in code ------------------------------------------------------------

_TASK_KEYS = SECTION_SLOT_KEYS[StoryStyle.STAR][StorySection.TASK]


def convert_style(outline: StoryOutline, style: StoryStyle) -> StoryOutline:
    """SC-12, D-2: the same slots in the other style, with no model call. Sections are renamed
    and the Task slots move into Challenge (CARL) or out of it (STAR); every slot keeps its text,
    quotes and status, so STAR to CARL to STAR gives back the same outline."""
    if outline.style == style:
        return outline.model_copy(deep=True)
    by_section = {s.section: s for s in outline.model_copy(deep=True).sections}
    if style == StoryStyle.CARL:
        situation, task = by_section[StorySection.SITUATION], by_section[StorySection.TASK]
        challenge = OutlineSection(
            section=StorySection.CHALLENGE, slots={**situation.slots, **task.slots}
        )
        by_section[StorySection.CHALLENGE] = challenge
    else:
        challenge = by_section[StorySection.CHALLENGE]
        by_section[StorySection.SITUATION] = OutlineSection(
            section=StorySection.SITUATION,
            slots={k: v for k, v in challenge.slots.items() if k not in _TASK_KEYS},
        )
        by_section[StorySection.TASK] = OutlineSection(
            section=StorySection.TASK,
            slots={k: v for k, v in challenge.slots.items() if k in _TASK_KEYS},
        )
    return StoryOutline(style=style, sections=[by_section[s] for s in STYLE_SECTIONS[style]])
