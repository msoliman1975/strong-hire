"""Deep story crafting, the engine and the craft turn (SC02): Ready (SC-3), section by section
(SC-4), skip and move on (SC-5), slot updates backed by quotes (SC-6), and the legacy columns
rendered from the outline (SC-14). All on the fake model."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.coach import craft
from strong_api.coach import router as coach_router
from strong_api.stories.outline import (
    load_outline,
    ready,
    render_legacy,
    save_outline,
    strip_markdown,
)
from strong_core.db.models import CoachSession
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import fake_models_config
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    Competency,
    CraftReply,
    SlotRef,
    SlotStatus,
    StoryOutline,
    StoryPart,
    StorySection,
    StorySource,
    StoryStatus,
    StoryStyle,
)
from strong_worker.scoring.stories import render_story, story_from_row

from .conftest import sign_in

S = StorySection
T1 = (
    "Last year at Acme I was the tech lead on checkout when we were moving checkout to the new "
    "payments provider, and the rollout was already two weeks late. Black Friday was a month "
    "out and checkout could not break."
)
T2 = (
    "I split the rollout by country instead of one big switch, because a full switch could not "
    "be rolled back fast."
)
T3 = "Checkout errors dropped from 2% to 0.3% and we shipped a week before Black Friday."
T4 = "I learned to cut big launches into small reversible steps."


def quoted(text: str, *quotes: str) -> dict[str, Any]:
    return {"text": text, "quotes": list(quotes), "status": "filled"}


def typed(text: str) -> dict[str, Any]:
    return {"text": text, "by_user": True, "status": "filled"}


def outline(style: StoryStyle = StoryStyle.STAR, **slots: Any) -> StoryOutline:
    """An outline with the given slots filled, keyed '<section>.<slot>' (steps: 'action')."""
    data = StoryOutline.empty(style).model_dump(mode="json", exclude_none=True)
    sections = {s["section"]: s for s in data["sections"]}
    for key, value in slots.items():
        section, _, slot = key.partition("__")
        if section == "action":
            sections["action"]["steps"] = value
        elif slot == "metric":
            sections[section]["metric"] = value
        else:
            sections[section]["slots"][slot] = value
    return StoryOutline.model_validate(data)


def core(style: StoryStyle = StoryStyle.STAR) -> dict[str, Any]:
    opening = "situation" if style == StoryStyle.STAR else "challenge"
    return {
        f"{opening}__role": typed("I was the tech lead on checkout."),
        f"{opening}__problem": typed("The payments migration was two weeks late."),
        "action": [{"did": typed("I split the rollout by country."), "why": typed("Rollback.")}],
        "result__metric": typed("Errors dropped from 2% to 0.3%."),
        "learning__lesson": typed("Small reversible steps."),
    }


def row(o: StoryOutline | None = None) -> StoryRow:
    story = StoryRow(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Checkout migration",
        skills=["ownership"],
        notes_json=[],
        status=StoryStatus.DRAFT,
        source=StorySource.COACH,
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
        updated_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    if o is not None:
        save_outline(story, o)
    return story


# --- SC-1, D-2: the style Strova suggests ----------------------------------------------------


def test_sc1_suggest_style_follows_the_d2_rule() -> None:
    """SC-1, D-2: CARL for conflict, failure, ownership, judgment and problem framing, or for a
    challenge question; STAR otherwise."""
    for skill in ("conflict_handling", "learning_from_failure", "ownership", "judgment"):
        assert craft.suggest_style(Competency(skill)) == StoryStyle.CARL
    assert craft.suggest_style(Competency.PROBLEM_FRAMING) == StoryStyle.CARL
    assert craft.suggest_style(Competency.COLLABORATION) == StoryStyle.STAR
    assert craft.suggest_style(None) == StoryStyle.STAR
    assert craft.suggest_style(None, "Tell me about a challenge you faced") == StoryStyle.CARL


# --- SC-3: Ready -------------------------------------------------------------------------------


@pytest.mark.parametrize("style", list(StoryStyle))
def test_sc3_ready_exactly_when_the_core_slots_are_filled(style: StoryStyle) -> None:
    """SC-3, D-4: Ready needs role, problem, one step with what you did and one with why, the
    metric and the lesson. The optional slots never block it."""
    full = core(style)
    assert ready(outline(style, **full))
    assert not ready(StoryOutline.empty(style))
    for key in full:
        partial = {k: v for k, v in full.items() if k != key}
        assert not ready(outline(style, **partial)), key
    no_why = {**full, "action": [{"did": typed("I split the rollout.")}]}
    assert not ready(outline(style, **no_why))
    split = {**full, "action": [{"did": typed("I split it.")}, {"why": typed("Rollback.")}]}
    assert ready(outline(style, **split))


def test_sc3_display_status_of_a_styled_story_follows_the_outline() -> None:
    """SC-3, ST-8: a styled story shows Ready from its core slots; Proven is unchanged (ST-7)."""
    from strong_api.stories.router import display_status

    assert display_status(row(outline(**core()))) == "ready"
    assert display_status(row(StoryOutline.empty(StoryStyle.STAR))) == "draft"
    proven = row(StoryOutline.empty(StoryStyle.STAR))
    proven.status = StoryStatus.PROVEN
    assert display_status(proven) == "proven"


# --- SC-4, SC-5: section by section ----------------------------------------------------------


def test_sc4_sections_run_in_the_style_order() -> None:
    """SC-4, D-7: STAR runs Situation, Task, Action, Result, Learning; CARL runs Challenge,
    Action, Result, Learning; sections only move forward."""
    for style, order in (
        (StoryStyle.STAR, [S.SITUATION, S.TASK, S.ACTION, S.RESULT, S.LEARNING]),
        (StoryStyle.CARL, [S.CHALLENGE, S.ACTION, S.RESULT, S.LEARNING]),
    ):
        o = StoryOutline.empty(style)
        seen, section = [], craft.start_section(o)
        while section is not None:
            seen.append(section)
            section = craft.next_section(o, section)
        assert seen == order


def test_sc4_the_engine_picks_the_empty_slots_in_order() -> None:
    """SC-4, D-5, D-7: the required and context slots still empty, in the table's order. The
    optional slots (constraints, the Task slots) are left to the section's open question."""
    o = StoryOutline.empty(StoryStyle.STAR)
    assert [r.slot for r in craft.asks(o, S.SITUATION)] == [
        "org",
        "role",
        "scale",
        "timeframe",
        "problem",
        "stakeholders",
    ]
    assert craft.asks(o, S.TASK) == []
    assert craft.has_room(o, S.TASK)
    assert craft.asks(o, S.ACTION) == [SlotRef(section=S.ACTION, slot="did", step=0)]
    assert [r.slot for r in craft.asks(o, S.RESULT)] == ["metric"]
    assert [r.slot for r in craft.asks(o, S.LEARNING)] == ["lesson"]
    did = outline(action=[{"did": typed("I split it.")}])
    assert craft.asks(did, S.ACTION) == [SlotRef(section=S.ACTION, slot="why", step=0)]
    carl = StoryOutline.empty(StoryStyle.CARL)
    assert "goal" not in [r.slot for r in craft.asks(carl, S.CHALLENGE)]


def test_sc4_a_filled_section_is_passed_over() -> None:
    """SC-4: a section with nothing left to fill is not opened."""
    task = {
        "task__goal": typed("Ship it."),
        "task__success": typed("No failed payments."),
        "task__assigned_by": typed("The CTO."),
    }
    o = outline(**task)
    assert craft.next_section(o, S.SITUATION) == S.ACTION


def test_sc5_skipped_slots_are_never_asked_again() -> None:
    """SC-5, D-5: a skipped slot drops out of the slots Strova is given."""
    o = outline(situation__org={"status": "skipped"})
    assert "org" not in [r.slot for r in craft.asks(o, S.SITUATION)]
    applied = craft.apply(
        StoryOutline.empty(StoryStyle.STAR),
        CraftReply(message="Thanks.", skips=[SlotRef(section=S.SITUATION, slot="scale")]),
        "",
    )
    assert applied.outline.section(S.SITUATION).slot("scale").status == SlotStatus.SKIPPED
    assert "scale" not in [r.slot for r in craft.asks(applied.outline, S.SITUATION)]


def test_sc5_a_filled_slot_is_not_skipped() -> None:
    """SC-5: skip marks only an empty slot."""
    o = outline(situation__role=typed("I led checkout."))
    applied = craft.apply(
        o, CraftReply(message="Ok.", skips=[SlotRef(section=S.SITUATION, slot="role")]), ""
    )
    assert applied.outline.section(S.SITUATION).slot("role").status == SlotStatus.FILLED
    assert applied.skipped == []


def test_sc4_the_prompt_gets_only_the_section_and_its_slots() -> None:
    """SC-4, SC-5: the craft prompt names the section in progress, its empty slots in order, and
    the skipped ones; the rules for pressing once, skip and move on are in the prompt."""
    system = load_prompt("coach", "craft_turn").render(style="", skills="")
    assert "Follow up once on each empty slot" in system
    assert '"skip"' in system and '"move on"' in system
    assert "never add" in system and "quotes" in system
    o = outline(situation__org={"status": "skipped"})
    ask = craft.next_ask(o, S.SITUATION)
    text = load_prompt("coach", "craft_turn_input").render(
        story_style="STAR",
        outline="",
        target_skill="",
        transcript="",
        section=S.SITUATION.value,
        slots=craft._render_slots(ask.slots),
        skipped=craft._skipped(o),
        then="",
        hints="",
        answer="",
    )
    assert 'slot "role"' in text and 'slot "org"' not in text
    assert "Skipped slots (never ask about these): Company and team" in text


# --- SC-6: slot updates backed by quotes ------------------------------------------------------


def _said(*texts: str) -> str:
    from strong_api.coach import engine

    return "\n".join(engine.normal(t) for t in texts)


def test_sc6_updates_need_the_candidates_quotes_and_numbers() -> None:
    """SC-6, CO-9: an update is kept only when its quotes are the candidate's words and its
    numbers are in its quotes; Strova may reword."""
    reply = CraftReply.model_validate(
        {
            "message": "What was your role?",
            "slot_updates": [
                {
                    "section": "situation",
                    "slot": "problem",
                    "text": "Our move to a new payments provider was two weeks late.",
                    "quotes": [
                        "we were moving checkout to the new payments provider",
                        "the rollout was already two weeks late",
                    ],
                },
                {
                    "section": "situation",
                    "slot": "scale",
                    "text": "Checkout handled 40,000 orders a day.",
                    "quotes": ["we were moving checkout to the new payments provider"],
                },
                {
                    "section": "situation",
                    "slot": "org",
                    "text": "I worked at Globex.",
                    "quotes": ["I worked at Globex"],
                },
            ],
        }
    )
    applied = craft.apply(StoryOutline.empty(StoryStyle.STAR), reply, _said(T1))
    situation = applied.outline.section(S.SITUATION)
    assert situation.slot("problem").status == SlotStatus.FILLED
    assert situation.slot("problem").quotes
    assert situation.slot("scale").status == SlotStatus.EMPTY
    assert situation.slot("org").status == SlotStatus.EMPTY
    assert any("number not in the quotes" in d for d in applied.dropped)
    assert any("quote not found" in d for d in applied.dropped)


def test_sc6_a_slot_the_candidate_typed_is_never_overwritten() -> None:
    """SC-6, D-10: a craft turn never replaces the candidate's own text."""
    o = outline(situation__role=typed("I was the tech lead on checkout."))
    reply = CraftReply.model_validate(
        {
            "message": "Ok.",
            "slot_updates": [
                {
                    "section": "situation",
                    "slot": "role",
                    "text": "I was the tech lead.",
                    "quotes": ["I was the tech lead on checkout"],
                }
            ],
        }
    )
    applied = craft.apply(o, reply, _said(T1))
    assert applied.outline.section(S.SITUATION).slot("role").by_user
    assert applied.kept == []


def test_sc6_steps_are_added_in_order_and_carl_maps_task_slots() -> None:
    """SC-6, SC-2: a new step is appended in order; a gap is dropped. In CARL, a Task slot lands
    in Challenge (D-1)."""
    step = {
        "section": "action",
        "slot": "did",
        "text": "I split the rollout by country.",
        "quotes": ["I split the rollout by country instead of one big switch"],
    }
    o = outline(action=[{"did": typed("I took over the cutover plan.")}])
    gap = craft.apply(
        o,
        CraftReply.model_validate({"message": "Ok.", "slot_updates": [{**step, "step": 2}]}),
        _said(T2),
    )
    assert gap.kept == [] and "in order" in gap.dropped[0]
    added = craft.apply(
        o,
        CraftReply.model_validate({"message": "Ok.", "slot_updates": [{**step, "step": 1}]}),
        _said(T2),
    )
    assert len(added.outline.section(S.ACTION).steps or []) == 2
    goal = {
        "section": "task",
        "slot": "goal",
        "text": "Checkout could not break before Black Friday.",
        "quotes": ["Black Friday was a month out and checkout could not break"],
    }
    carl = craft.apply(
        StoryOutline.empty(StoryStyle.CARL),
        CraftReply.model_validate({"message": "Ok.", "slot_updates": [goal]}),
        _said(T1),
    )
    assert carl.outline.section(S.CHALLENGE).slot("goal").status == SlotStatus.FILLED


def test_sc6_metric_keeps_before_and_after_only_when_quoted() -> None:
    """SC-6: the metric's before and after numbers must be in its quotes too."""
    metric = {
        "section": "result",
        "slot": "metric",
        "text": "Checkout errors dropped from 2% to 0.3%.",
        "quotes": ["Checkout errors dropped from 2% to 0.3%"],
        "before": "2",
        "after": "0.3",
        "unit": "%",
    }
    kept = craft.apply(
        StoryOutline.empty(StoryStyle.STAR),
        CraftReply.model_validate({"message": "Ok.", "slot_updates": [metric]}),
        _said(T3),
    )
    m = kept.outline.section(S.RESULT).metric
    assert m is not None and m.before == "2" and m.after == "0.3"
    invented = {**metric, "after": "0.1"}
    dropped = craft.apply(
        StoryOutline.empty(StoryStyle.STAR),
        CraftReply.model_validate({"message": "Ok.", "slot_updates": [invented]}),
        _said(T3),
    )
    assert dropped.kept == []


# --- SC-14: the legacy columns ----------------------------------------------------------------


def test_sc14_render_legacy_star() -> None:
    """SC-14, D-12: context, stakes, action, result and reflection come from the mapped slots,
    as plain text with the Markdown stripped."""
    o = outline(
        situation__org=typed("Acme, the checkout team"),
        situation__role=typed("I was the **tech lead**."),
        situation__constraints=typed("- Black Friday\n- no budget"),
        situation__problem=typed("The migration was two weeks late."),
        task__goal=typed("Ship before Black Friday."),
        task__assigned_by=typed("The CTO asked me."),
        action=[
            {
                "did": typed("I split the rollout by country."),
                "why": typed("A full switch could not roll back."),
            },
            {"did": typed("I ran a daily check-in")},
        ],
        result__metric=typed("Errors dropped from 2% to 0.3%."),
        result__recognition=typed("A shout-out at the all-hands."),
        result__impact=typed("_No_ lost sales."),
        learning__lesson=typed("Cut big launches into small steps."),
    )
    legacy = render_legacy(o)
    assert legacy[StoryPart.CONTEXT] == (
        "Acme, the checkout team. I was the tech lead. Black Friday no budget."
    )
    assert legacy[StoryPart.STAKES] == (
        "The migration was two weeks late. Ship before Black Friday."
    )
    assert legacy[StoryPart.ACTION] == (
        "I split the rollout by country, because a full switch could not roll back. "
        "I ran a daily check-in."
    )
    assert legacy[StoryPart.RESULT] == "Errors dropped from 2% to 0.3%. No lost sales."
    assert legacy[StoryPart.REFLECTION] == "Cut big launches into small steps."
    assert render_legacy(StoryOutline.empty(StoryStyle.STAR)) == dict.fromkeys(StoryPart)


def test_sc14_render_legacy_carl() -> None:
    """SC-14: in CARL the Challenge holds both the context slots and the Task slots."""
    o = outline(
        StoryStyle.CARL,
        challenge__role=typed("I was the tech lead."),
        challenge__problem=typed("The migration was late."),
        challenge__goal=typed("Ship before Black Friday."),
        action=[{"why": typed("Rollback had to be fast.")}],
        learning__differently=typed("Start the cutover earlier."),
    )
    legacy = render_legacy(o)
    assert legacy[StoryPart.CONTEXT] == "I was the tech lead."
    assert legacy[StoryPart.STAKES] == "The migration was late. Ship before Black Friday."
    assert legacy[StoryPart.ACTION] == "Rollback had to be fast."
    assert legacy[StoryPart.RESULT] is None
    assert legacy[StoryPart.REFLECTION] == "Start the cutover earlier."


def test_sc14_strip_markdown() -> None:
    """SC-14, D-14: bold, italic and list markers go; the words stay."""
    assert strip_markdown("**Bold** and *italic* and __under__ and _it_") == (
        "Bold and italic and under and it"
    )
    assert strip_markdown("1. one\n2. two\n- three") == "one two three"
    assert strip_markdown("snake_case_name and 2 * 3") == "snake_case_name and 2 * 3"


def test_sc14_existing_readers_see_the_same_story_text() -> None:
    """SC-14: the scorer and story fit read a styled story through the legacy columns, exactly as
    they read a classic story with the same text."""
    styled = row(outline(**core()))
    classic = row()
    for part in StoryPart:
        setattr(classic, part.value, getattr(styled, part.value))
    assert styled.context and styled.action and styled.result
    assert render_story("S1", story_from_row(styled)) == render_story("S1", story_from_row(classic))
    assert load_outline(styled) is not None and load_outline(classic) is None


def test_sc14_every_outline_save_renders_the_columns() -> None:
    """SC-14: save_outline stores the outline and renders the five columns from it."""
    story = row(StoryOutline.empty(StoryStyle.STAR))
    assert story.style == StoryStyle.STAR and story.context is None
    save_outline(story, outline(situation__role=typed("I led checkout.")))
    assert story.context == "I led checkout."
    o = load_outline(story)
    assert o is not None and o.section(S.SITUATION).slot("role").by_user


# --- the API, end to end on the fake model -----------------------------------------------------


async def start(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/coach/sessions", json=body)
    assert response.status_code == 201, response.text
    out: dict[str, Any] = response.json()
    return out


async def turn(client: httpx.AsyncClient, sid: str, text: str) -> dict[str, Any]:
    response = await client.post(f"/coach/sessions/{sid}/turns", json={"text": text})
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    return out


def use_fixtures(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    gateway = ModelGateway(fake_models_config(), fake=FakeBackend(folder))
    monkeypatch.setattr(coach_router, "get_gateway", lambda: gateway)


def set_reply(folder: Path, reply: dict[str, Any]) -> None:
    (folder / "coach" / "CraftReply.json").write_text(json.dumps(reply), encoding="utf-8")


ROLE_AND_PROBLEM = {
    "message": "Thank you. Which team were you on?",
    "slot_updates": [
        {
            "section": "situation",
            "slot": "role",
            "text": "I was the tech lead on checkout at Acme.",
            "quotes": ["at Acme I was the tech lead on checkout"],
        },
        {
            "section": "situation",
            "slot": "problem",
            "text": "Our move to a new payments provider was two weeks late, with Black Friday "
            "a month away.",
            "quotes": [
                "we were moving checkout to the new payments provider",
                "the rollout was already two weeks late",
                "Black Friday was a month out",
            ],
        },
    ],
    "skills": ["ownership"],
}


async def test_sc1_start_a_styled_session(client: httpx.AsyncClient) -> None:
    """SC-1, SC-2, SC-4: a styled start gives the story an empty outline, opens the first section
    with one open question, and names the slots Strova asks about."""
    await sign_in(client)
    started = await start(client, target_skill="ownership", story_style="carl")
    story = started["story"]
    assert story["style"] == "carl"
    assert [s["section"] for s in story["outline"]["sections"]] == [
        "challenge",
        "action",
        "result",
        "learning",
    ]
    assert started["session"]["section"] == "challenge"
    assert started["asking"]["section"] == "challenge"
    assert [s["slot"] for s in started["asking"]["slots"]][:2] == ["org", "role"]
    assert started["suggested_style"] is None
    [opener] = started["turns"]
    assert opener["text"].startswith("Let's build one story that shows ownership, as CARL.")
    assert opener["text"].endswith(craft.SECTION_OPENERS[S.CHALLENGE])


async def test_sc1_classic_start_carries_the_suggested_style(client: httpx.AsyncClient) -> None:
    """SC-1, D-2: a start without a style stays classic and returns Strova's suggestion; the
    suggestion endpoint gives the same answer before a session starts."""
    await sign_in(client)
    started = await start(client, target_skill="conflict_handling")
    assert started["suggested_style"] == "carl"
    assert started["story"]["style"] is None and started["story"]["outline"] is None
    assert started["session"]["section"] is None and started["asking"] is None
    got = await client.get("/coach/style-suggestion", params={"target_skill": "collaboration"})
    assert got.json() == {"style": "star"}


async def test_sc6_a_turn_fills_slots_from_the_candidates_words(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """SC-6, SC-14: a turn fills slots with quotes, renders the legacy columns, and keeps the
    session in its section while slots are left; the prompt ref is stored."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(fake_fixtures, ROLE_AND_PROBLEM)
    await sign_in(client)
    sid = (await start(client, story_style="star"))["session"]["id"]
    out = await turn(client, sid, T1)
    assert {(u["section"], u["slot"]) for u in out["craft"]["slot_updates"]} == {
        ("situation", "role"),
        ("situation", "problem"),
    }
    situation = out["story"]["outline"]["sections"][0]
    assert situation["slots"]["role"]["quotes"] == ["at Acme I was the tech lead on checkout"]
    assert out["story"]["context"] == "I was the tech lead on checkout at Acme."
    assert out["story"]["stakes"].startswith("Our move to a new payments provider")
    assert out["asking"]["section"] == "situation"
    assert "role" not in [s["slot"] for s in out["asking"]["slots"]]
    assert out["craft"]["section_done"] is False
    assert out["reply"]["message"] == "Thank you. Which team were you on?"
    detail = (await client.get(f"/coach/sessions/{sid}")).json()
    assert detail["session"]["section"] == "situation"
    async with sessionmaker() as db:
        session = await db.get(CoachSession, uuid.UUID(sid))
        assert session is not None and "coach/craft_turn.v3" in (session.prompt_version or "")


async def test_sc5_skip_and_move_on(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-5: a bare "skip" marks the slot Strova just asked about skipped; "move on" ends the
    section, and Strova opens the next one."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(fake_fixtures, {"message": "Thank you. What was your role at the time?"})
    await sign_in(client)
    sid = (await start(client, story_style="star"))["session"]["id"]
    skipped = await turn(client, sid, "I can't share that.")
    assert skipped["craft"]["skips"] == [{"section": "situation", "slot": "org", "step": None}]
    org = skipped["story"]["outline"]["sections"][0]["slots"]["org"]
    assert org == {"quotes": [], "by_user": False, "status": "skipped", "text": None}
    assert "org" not in [s["slot"] for s in skipped["asking"]["slots"]]
    moved = await turn(client, sid, "move on")
    assert moved["craft"]["section_done"] is True
    assert moved["asking"]["section"] == "task"
    assert moved["reply"]["message"] == craft.SECTION_OPENERS[S.TASK]
    nxt = await turn(client, sid, "My goal was to ship before Black Friday.")
    assert nxt["asking"]["section"] == "action"  # Task has only its open question


async def test_sc4_the_model_is_told_the_section_and_its_slots(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-4: the prompt the model gets names the section in progress and only its empty slots."""
    use_fixtures(monkeypatch, fake_fixtures)
    seen: list[str] = []
    real = craft.craft_messages

    def spy(*args: Any, **kwargs: Any) -> Any:
        messages = real(*args, **kwargs)
        seen.append(messages[1].content)
        return messages

    monkeypatch.setattr(craft, "craft_messages", spy)
    set_reply(fake_fixtures, ROLE_AND_PROBLEM)
    await sign_in(client)
    sid = (await start(client, story_style="star"))["session"]["id"]
    await turn(client, sid, T1)
    await turn(client, sid, "It was the payments team.")
    first, second = (_asked(m) for m in seen)
    assert 'Section in progress: "situation"' in seen[0]
    assert 'slot "role"' in first and 'slot "goal"' not in first
    assert 'slot "role"' not in second and 'slot "org"' in second
    assert 'the "task" section' in seen[0]


def _asked(message: str) -> str:
    """The "Empty slots to ask about" block of the craft prompt's input."""
    start = message.index("Empty slots to ask about")
    return message[start : message.index("Skipped slots", start)]


async def test_sc6_classic_sessions_are_unchanged(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-11: a session on a classic story keeps today's five-part turn."""
    use_fixtures(monkeypatch, fake_fixtures)
    (fake_fixtures / "coach" / "CraftReply.json").unlink()
    await sign_in(client)
    sid = (await start(client))["session"]["id"]
    out = await turn(client, sid, T1)
    assert out["craft"] is None and out["asking"] is None
    assert out["story"]["style"] is None


async def test_sc14_a_styled_story_rejects_part_edits(client: httpx.AsyncClient) -> None:
    """SC-14: the five parts of a styled story are rendered from its outline, so PATCH refuses a
    part edit (409) and still takes the title."""
    await sign_in(client)
    story = (await start(client, story_style="star"))["story"]
    bad = await client.patch(f"/stories/{story['id']}", json={"context": "New text"})
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "styled_story"
    ok = await client.patch(f"/stories/{story['id']}", json={"title": "Checkout"})
    assert ok.status_code == 200 and ok.json()["style"] == "star"


async def test_sc14_ending_an_empty_styled_session_drops_the_story(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-14: a new styled story with no slot filled is dropped at the end, as a classic one is;
    one with a filled slot is kept."""
    await sign_in(client)
    sid = (await start(client, story_style="star"))["session"]["id"]
    ended = (await client.post(f"/coach/sessions/{sid}/end")).json()
    assert ended["story"] is None
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(fake_fixtures, ROLE_AND_PROBLEM)
    sid = (await start(client, story_style="star"))["session"]["id"]
    await turn(client, sid, T1)
    kept = (await client.post(f"/coach/sessions/{sid}/end")).json()
    assert kept["story"]["style"] == "star"


# --- CO-1: a scripted crafting session, with exact recordings ---------------------------------
#
# CRAFT_SCRIPT has exact recordings in packages/core/src/strong_core/gateway/fixtures/coach/
# <hash>.json, one per Strova reply. A change to the craft prompts changes the hashes: the
# scripted test then fails, and the recordings need writing again:
# RECORD_CRAFT_SCRIPT=1 pytest apps/api/tests/test_story_crafting_api.py -k record

CRAFT_SCRIPT = (
    T1,
    "move on",
    "My job was to get checkout onto the new provider before Black Friday, and success meant "
    "not one failed payment.",
    T2,
    T3,
    T4,
)
CRAFT_REPLIES: tuple[dict[str, Any], ...] = (
    {
        "message": "Thank you. How many orders a day went through checkout?",
        "slot_updates": [
            {
                "section": "situation",
                "slot": "org",
                "text": "Acme, on the checkout team.",
                "quotes": ["Last year at Acme I was the tech lead on checkout"],
            },
            *ROLE_AND_PROBLEM["slot_updates"],
        ],
        "skills": ["ownership"],
    },
    {
        "message": "What were you responsible for, and what would success have looked like?",
        "section_done": True,
    },
    {
        "message": "Thank you. Walk me through what you did, step by step, and why.",
        "slot_updates": [
            {
                "section": "task",
                "slot": "goal",
                "text": "Get checkout onto the new provider before Black Friday.",
                "quotes": ["get checkout onto the new provider before Black Friday"],
            },
            {
                "section": "task",
                "slot": "success",
                "text": "Not one failed payment.",
                "quotes": ["success meant not one failed payment"],
            },
        ],
        "section_done": True,
    },
    {
        "message": "Thank you. What changed in the end?",
        "slot_updates": [
            {
                "section": "action",
                "slot": "did",
                "step": 0,
                "text": "I split the rollout by country instead of one big switch.",
                "quotes": ["I split the rollout by country instead of one big switch"],
            },
            {
                "section": "action",
                "slot": "why",
                "step": 0,
                "text": "A full switch could not be rolled back fast.",
                "quotes": ["a full switch could not be rolled back fast"],
            },
        ],
        "section_done": True,
        "skills": ["ownership", "judgment"],
    },
    {
        "message": "Thank you. Looking back, what did you learn?",
        "slot_updates": [
            {
                "section": "result",
                "slot": "metric",
                "text": "Checkout errors dropped from 2% to 0.3%.",
                "quotes": ["Checkout errors dropped from 2% to 0.3%"],
                "before": "2%",
                "after": "0.3%",
            },
            {
                "section": "result",
                "slot": "impact",
                "text": "We shipped a week before Black Friday.",
                "quotes": ["we shipped a week before Black Friday"],
            },
        ],
        "section_done": True,
        "skills": ["ownership", "judgment", "impact"],
    },
    {
        "message": "We've been through every section. Do you want to sharpen anything, or are "
        "you done?",
        "slot_updates": [
            {
                "section": "learning",
                "slot": "lesson",
                "text": "I learned to cut big launches into small, reversible steps.",
                "quotes": ["I learned to cut big launches into small reversible steps"],
            }
        ],
        "section_done": True,
    },
)


async def test_sc4_scripted_star_session_builds_a_ready_story(client: httpx.AsyncClient) -> None:
    """CO-1, SC-3, SC-4, SC-6, SC-14: six turns walk Situation, Task, Action, Result and Learning
    in order on the recorded replies; the story ends Ready with its legacy columns rendered."""
    await sign_in(client)
    started = await start(client, target_skill="ownership", story_style="star")
    sid = started["session"]["id"]
    sections = []
    out: dict[str, Any] = {}
    for text in CRAFT_SCRIPT:
        out = await turn(client, sid, text)
        sections.append(out["asking"]["section"])
    assert sections == ["situation", "task", "action", "result", "learning", None]
    assert out["reply"]["message"].startswith("We've been through every section.")
    story = out["story"]
    got = (await client.get(f"/stories/{story['id']}")).json()
    assert got["display_status"] == "ready"
    assert got["context"].startswith("Acme, on the checkout team.")
    assert got["action"] == (
        "I split the rollout by country instead of one big switch, because a full switch could "
        "not be rolled back fast."
    )
    assert got["result"] == (
        "Checkout errors dropped from 2% to 0.3%. We shipped a week before Black Friday."
    )
    assert got["reflection"] == "I learned to cut big launches into small, reversible steps."
    assert "judgment" in got["skills"]


@pytest.mark.skipif(
    os.environ.get("RECORD_CRAFT_SCRIPT") != "1",
    reason="set RECORD_CRAFT_SCRIPT=1 after a craft prompt change, then commit the fixtures",
)
async def test_record_craft_script(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strong_core.gateway import Role
    from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR, Recording, messages_hash

    replies = iter(CRAFT_REPLIES)
    real = craft.craft_messages

    def record(*args: Any, **kwargs: Any) -> Any:
        messages = real(*args, **kwargs)
        recording = Recording(
            role=Role.COACH,
            profile="scripted",  # written by hand for this test, not by a model
            model="scripted",
            output_type="CraftReply",
            messages=messages,
            prompt_refs=[m.prompt_ref for m in messages if m.prompt_ref],
            output=CraftReply.model_validate(next(replies)).model_dump(mode="json"),
            recorded_at="2026-11-02T00:00:00+00:00",
        )
        path = DEFAULT_FIXTURES_DIR / Role.COACH.value / f"{messages_hash(messages)}.json"
        path.write_text(recording.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return messages

    monkeypatch.setattr(craft, "craft_messages", record)
    await sign_in(client)
    sid = (await start(client, target_skill="ownership", story_style="star"))["session"]["id"]
    for text in CRAFT_SCRIPT:
        await turn(client, sid, text)
