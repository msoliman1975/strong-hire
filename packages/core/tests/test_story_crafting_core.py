"""Deep story crafting core (SC01): story style (SC-1), the outline and its slots (SC-2), and the
contracts later tasks fill: craft reply, flow check, improve, organize and style rewrite."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from strong_core.db.models import Base
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
from strong_core.schemas import (
    CONTEXT_SLOTS,
    CORE_SLOTS,
    EXPORTED_SCHEMAS,
    SECTION_SLOT_KEYS,
    STYLE_SECTIONS,
    CraftReply,
    FlowCheck,
    FlowFlagType,
    OrganizeResult,
    OutlineSlot,
    SectionImprove,
    SlotRef,
    SlotStatus,
    Story,
    StoryOutline,
    StorySection,
    StorySource,
    StoryStyle,
    StyleRewrite,
)

COACH_FIXTURES = DEFAULT_FIXTURES_DIR / "coach"
MIGRATION = next(
    (Path(__file__).parents[1] / "migrations" / "versions").glob("*_0030_deep_story_crafting.py")
)
NOW = datetime(2026, 11, 2, tzinfo=UTC)


def _fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((COACH_FIXTURES / f"{name}.json").read_text("utf-8"))
    return data


def _star() -> dict[str, Any]:
    outline: dict[str, Any] = _fixture("OrganizeResult")["outline"]
    return outline


def _carl() -> dict[str, Any]:
    outline: dict[str, Any] = _fixture("StyleRewrite")["outline"]
    return outline


def _story(**extra: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "title": "Checkout migration",
        "source": StorySource.COACH.value,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        **extra,
    }


# --- SC-1: style


def test_sc1_story_styles_are_star_and_carl() -> None:
    """SC-1, D-1: STAR is Situation, Task, Action, Result, Learning; CARL is Challenge, Action,
    Result, Learning."""
    assert {s.value for s in StoryStyle} == {"star", "carl"}
    assert [s.value for s in STYLE_SECTIONS[StoryStyle.STAR]] == [
        "situation",
        "task",
        "action",
        "result",
        "learning",
    ]
    assert [s.value for s in STYLE_SECTIONS[StoryStyle.CARL]] == [
        "challenge",
        "action",
        "result",
        "learning",
    ]


def test_sc1_stories_store_a_nullable_style_and_outline() -> None:
    """SC-1, SC-2, D-11: stories.style, outline_json, flow_json and hints_json are nullable, so
    classic stories keep null; coach_sessions.section records the section in progress."""
    stories = Base.metadata.tables["stories"]
    style = stories.columns["style"]
    assert style.nullable
    assert set(style.type.enums) == {"star", "carl"}
    for column in ("outline_json", "flow_json", "hints_json"):
        assert stories.columns[column].nullable, column
    section = Base.metadata.tables["coach_sessions"].columns["section"]
    assert section.nullable
    assert set(section.type.enums) == {s.value for s in StorySection}


def test_sc1_migration_has_no_backfill_and_a_downgrade() -> None:
    """SC-1, D-11: the migration adds nullable columns only; nothing converts classic stories."""
    text = MIGRATION.read_text("utf-8")
    assert "def downgrade" in text
    assert "UPDATE" not in text.upper().replace("UPGRADE", "")
    assert "sa.CheckConstraint" not in text
    for table, column in [
        ("stories", "style"),
        ("stories", "outline_json"),
        ("stories", "flow_json"),
        ("stories", "hints_json"),
        ("coach_sessions", "section"),
    ]:
        assert f"op.add_column('{table}', sa.Column('{column}'" in text, column
        assert f"op.drop_column('{table}', '{column}')" in text, column


def test_sc1_classic_story_has_no_style_or_outline() -> None:
    """SC-1: a classic story has style and outline null; a styled one has both, matching."""
    classic = Story.model_validate(_story(context="We were late."))
    assert classic.style is None and classic.outline is None
    styled = Story.model_validate(_story(style="star", outline=_star()))
    assert styled.outline is not None and styled.outline.style == StoryStyle.STAR
    with pytest.raises(ValidationError, match="styled story has an outline"):
        Story.model_validate(_story(style="star"))
    with pytest.raises(ValidationError, match="style must match"):
        Story.model_validate(_story(style="carl", outline=_star()))


# --- SC-2: outline and slots


def test_sc2_star_and_carl_outlines_validate() -> None:
    """SC-2: a STAR outline and a CARL outline validate, and CARL's Challenge holds the Task
    slots so a style switch loses no fact."""
    star = StoryOutline.model_validate(_star())
    carl = StoryOutline.model_validate(_carl())
    assert star.style == StoryStyle.STAR and carl.style == StoryStyle.CARL
    challenge = SECTION_SLOT_KEYS[StoryStyle.CARL][StorySection.CHALLENGE]
    assert {"goal", "success", "assigned_by"} <= set(challenge)
    assert carl.section(StorySection.CHALLENGE).slot("org").status == SlotStatus.SKIPPED


def test_sc2_empty_outline_for_each_style_validates() -> None:
    """SC-2: a new styled story starts with every slot empty and one empty action step."""
    for style in StoryStyle:
        outline = StoryOutline.empty(style)
        assert tuple(s.section for s in outline.sections) == STYLE_SECTIONS[style]
        assert all(slot.status == SlotStatus.EMPTY for *_, slot in outline.iter_slots())
        assert len(outline.section(StorySection.ACTION).steps or []) == 1
        StoryOutline.model_validate(outline.model_dump(mode="json"))


def test_sc2_unknown_slot_is_rejected() -> None:
    """SC-2: slot keys follow the spec table per style; Task slots are not Situation slots."""
    bad = _star()
    bad["sections"][0]["slots"]["goal"] = {"text": "x", "by_user": True, "status": "filled"}
    with pytest.raises(ValidationError, match="unknown slot"):
        StoryOutline.model_validate(bad)
    bad = _carl()
    bad["sections"][0]["slots"]["favourite_colour"] = {"status": "empty"}
    with pytest.raises(ValidationError, match="unknown slot"):
        StoryOutline.model_validate(bad)


def test_sc2_six_steps_are_rejected() -> None:
    """SC-2: the Action section holds 1 to 5 steps."""
    bad = _star()
    action = bad["sections"][2]
    action["steps"] = [copy.deepcopy(action["steps"][0]) for _ in range(6)]
    with pytest.raises(ValidationError, match="1 to 5 steps"):
        StoryOutline.model_validate(bad)
    action["steps"] = []
    with pytest.raises(ValidationError, match="1 to 5 steps"):
        StoryOutline.model_validate(bad)
    action["steps"] = [{} for _ in range(5)]
    StoryOutline.model_validate(bad)


def test_sc2_strova_slot_without_quotes_is_rejected() -> None:
    """SC-2, CO-9, D-6: a filled slot Strova wrote needs verbatim quotes; one the candidate typed
    is by_user and needs none."""
    with pytest.raises(ValidationError, match="needs quotes"):
        OutlineSlot.model_validate({"text": "I led checkout.", "status": "filled"})
    typed = OutlineSlot.model_validate(
        {"text": "I led checkout.", "by_user": True, "status": "filled"}
    )
    assert typed.by_user and not typed.quotes
    bad = _star()
    del bad["sections"][0]["slots"]["role"]["quotes"]
    with pytest.raises(ValidationError, match="needs quotes"):
        StoryOutline.model_validate(bad)


def test_sc2_slot_status_rules() -> None:
    """SC-2: filled, empty or skipped. Only a filled slot has text; a filled one must have it."""
    assert {s.value for s in SlotStatus} == {"filled", "empty", "skipped"}
    with pytest.raises(ValidationError, match="filled slot needs text"):
        OutlineSlot.model_validate({"by_user": True, "status": "filled"})
    with pytest.raises(ValidationError, match="only a filled slot"):
        OutlineSlot.model_validate({"text": "x", "status": "skipped"})
    with pytest.raises(ValidationError, match="carries no quotes"):
        OutlineSlot.model_validate(
            {"text": "x", "quotes": ["x"], "by_user": True, "status": "filled"}
        )


def test_sc2_sections_must_follow_the_style() -> None:
    """SC-2, D-1: an outline has exactly its style's sections, in order; steps and metric sit only
    in Action and Result."""
    bad = _star()
    bad["sections"].reverse()
    with pytest.raises(ValidationError, match="in order"):
        StoryOutline.model_validate(bad)
    bad = _carl()
    bad["style"] = "star"
    with pytest.raises(ValidationError, match="in order"):
        StoryOutline.model_validate(bad)
    bad = _star()
    bad["sections"][0]["steps"] = [{}]
    with pytest.raises(ValidationError, match="only the action section"):
        StoryOutline.model_validate(bad)
    bad = _star()
    del bad["sections"][3]["metric"]
    with pytest.raises(ValidationError, match="has a metric"):
        StoryOutline.model_validate(bad)


def test_sc2_core_and_context_slots_match_the_spec() -> None:
    """SC-2, D-4, D-5: the core slots Ready needs and the context slots Strova presses for."""
    assert {"role", "problem", "did", "why", "metric", "lesson"} == CORE_SLOTS
    assert {"org", "role", "scale", "timeframe", "problem", "stakeholders"} == CONTEXT_SLOTS
    star_situation = SECTION_SLOT_KEYS[StoryStyle.STAR][StorySection.SITUATION]
    assert set(star_situation) >= CONTEXT_SLOTS


# --- Contracts the later tasks fill


def test_sc6_craft_reply_updates_carry_quotes() -> None:
    """SC-6, D-6: each slot update carries verbatim quotes; a slot is not both updated and
    skipped; action slots name their step."""
    reply = CraftReply.model_validate(_fixture("CraftReply"))
    assert reply.slot_updates and all(u.quotes for u in reply.slot_updates)
    bad = _fixture("CraftReply")
    bad["slot_updates"][0]["quotes"] = []
    with pytest.raises(ValidationError):
        CraftReply.model_validate(bad)
    bad = _fixture("CraftReply")
    bad["skips"] = [{"section": "situation", "slot": "role"}]
    with pytest.raises(ValidationError, match="both updated and skipped"):
        CraftReply.model_validate(bad)
    with pytest.raises(ValidationError, match="step is set exactly"):
        SlotRef.model_validate({"section": "action", "slot": "did"})
    with pytest.raises(ValidationError, match="step is set exactly"):
        SlotRef.model_validate({"section": "situation", "slot": "role", "step": 0})
    with pytest.raises(ValidationError, match="unknown slot"):
        SlotRef.model_validate({"section": "result", "slot": "role"})
    assert SlotRef.model_validate({"section": "action", "slot": "why", "step": 4}).step == 4


def test_sc8_craft_reply_has_at_most_three_hints() -> None:
    """SC-8: at most three skill hints, one per skill."""
    reply = _fixture("CraftReply")
    hint = {"skill": "collaboration", "reason": "You split the rollout with the team."}
    reply["hints"] = [hint, {**hint, "skill": "ownership"}, {**hint, "skill": "judgment"}]
    CraftReply.model_validate(reply)
    reply["hints"].append({**hint, "skill": "communication"})
    with pytest.raises(ValidationError):
        CraftReply.model_validate(reply)
    reply["hints"] = [hint, hint]
    with pytest.raises(ValidationError, match="repeat a skill"):
        CraftReply.model_validate(reply)


def test_sc9_flow_check_flag_types() -> None:
    """SC-9: the five flag types; each flag cites slots; keys are unique."""
    assert {t.value for t in FlowFlagType} == {
        "action_vs_problem",
        "result_vs_problem",
        "number_conflict",
        "timeline_conflict",
        "loose_end",
    }
    check = FlowCheck.model_validate(_fixture("FlowCheck"))
    assert check.flags[0].slots
    twice = _fixture("FlowCheck")
    twice["flags"].append(twice["flags"][0])
    with pytest.raises(ValidationError, match="keys must not repeat"):
        FlowCheck.model_validate(twice)
    no_slots = _fixture("FlowCheck")
    no_slots["flags"][0]["slots"] = []
    with pytest.raises(ValidationError):
        FlowCheck.model_validate(no_slots)


def test_sc11_section_improve_returns_edits_or_questions() -> None:
    """SC-11: Improve returns before-and-after edits with quotes, or questions; never neither."""
    improve = SectionImprove.model_validate(_fixture("SectionImprove"))
    assert improve.edits[0].quotes
    assert SectionImprove.model_validate({"questions": ["By how much?"]}).questions
    with pytest.raises(ValidationError, match="edits or questions"):
        SectionImprove.model_validate({"edits": [], "questions": []})


def test_sc13_organize_builds_a_star_outline_from_quotes() -> None:
    """SC-13, D-11: Organize with Strova returns a STAR outline; Strova quoted every slot."""
    OrganizeResult.model_validate(_fixture("OrganizeResult"))
    with pytest.raises(ValidationError, match="builds a STAR outline"):
        OrganizeResult.model_validate({"outline": _carl()})
    typed = _fixture("OrganizeResult")
    typed["outline"]["sections"][0]["slots"]["role"] = {
        "text": "I led checkout.",
        "by_user": True,
        "status": "filled",
    }
    with pytest.raises(ValidationError, match="quotes every filled slot"):
        OrganizeResult.model_validate(typed)


def test_sc12_style_rewrite_quotes_every_slot() -> None:
    """SC-12, D-2: a wording rewrite into the other style quotes every filled slot."""
    assert StyleRewrite.model_validate(_fixture("StyleRewrite")).outline.style == StoryStyle.CARL


def test_sc2_new_contracts_are_exported() -> None:
    """SC-2: the outline and crafting contracts have JSON Schemas in schemas/."""
    for name in (
        "story_outline",
        "craft_reply",
        "flow_check",
        "section_improve",
        "organize_result",
        "style_rewrite",
    ):
        assert name in EXPORTED_SCHEMAS, name
