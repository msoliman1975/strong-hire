"""Deep story crafting, the story page's outline actions (SC03): inline edits (SC-10), Improve
with Strova (SC-11), Switch to STAR/CARL (SC-12) and Organize with Strova (SC-13). On the fake
model; the default fixtures (coach/SectionImprove.json, OrganizeResult.json, StyleRewrite.json)
quote the checkout story below."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.stories import outline_api
from strong_api.stories.outline import convert_style
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import (
    StoryOutline,
    StoryPartEdit,
    StoryStyle,
    SuggestionKind,
    TuneStoryPayload,
)

from .conftest import sign_in

# A classic story in the user's words; the fixtures quote it.
CLASSIC = {
    "title": "Checkout migration",
    "context": "I was the tech lead on checkout, and we were moving checkout to the new payments "
    "provider. The rollout was already two weeks late.",
    "stakes": "Black Friday was a month out and checkout could not break.",
    "action": "I split it so five percent of traffic went to the new provider first, because if "
    "it broke I wanted it to break small.",
    "result": "We were done a week before Black Friday and not one payment failed.",
    "reflection": "Small slices made it a bunch of small launches instead of one scary one.",
}


def use_fixtures(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    gateway = ModelGateway(fake_models_config(), fake=FakeBackend(folder))
    monkeypatch.setattr(outline_api, "get_gateway", lambda: gateway)


def set_fixture(folder: Path, name: str, data: dict[str, Any]) -> None:
    (folder / "coach" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


async def classic(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/stories", json=CLASSIC)
    assert response.status_code == 201, response.text
    out: dict[str, Any] = response.json()
    return out


async def organized(client: httpx.AsyncClient) -> dict[str, Any]:
    story = await classic(client)
    preview = (await client.post(f"/stories/{story['id']}/organize")).json()
    response = await client.post(f"/stories/{story['id']}/organize/accept", json=preview)
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    return out


async def styled(client: httpx.AsyncClient, style: str = "star") -> dict[str, Any]:
    """A new, empty styled story, as a crafting session starts one."""
    started = await client.post("/coach/sessions", json={"story_style": style})
    assert started.status_code == 201, started.text
    story: dict[str, Any] = started.json()["story"]
    return story


async def patch(client: httpx.AsyncClient, sid: str, **body: Any) -> httpx.Response:
    return await client.patch(f"/stories/{sid}/outline", json=body)


def slot(story: dict[str, Any], section: str, key: str) -> dict[str, Any]:
    sec = next(s for s in story["outline"]["sections"] if s["section"] == section)
    if key == "metric":
        out: dict[str, Any] = sec["metric"]
        return out
    found: dict[str, Any] = sec["slots"].get(key, {"status": "empty"})
    return found


# --- SC-10: inline edits ------------------------------------------------------------------------


async def test_sc10_an_inline_edit_rerenders_the_legacy_columns(client: httpx.AsyncClient) -> None:
    """SC-10, SC-14: the user's text goes in as typed (by_user, no quotes); the five parts are
    rendered again, and Ready follows the core slots (SC-3)."""
    await sign_in(client)
    story = await styled(client)
    out = await patch(
        client,
        story["id"],
        slots=[
            {"section": "situation", "slot": "role", "text": "I was the **tech lead**."},
            {"section": "situation", "slot": "problem", "text": "Checkout was late."},
            {"section": "action", "slot": "did", "step": 0, "text": "I split the rollout."},
            {"section": "action", "slot": "why", "step": 0, "text": "A rollback had to be fast."},
            {
                "section": "result",
                "slot": "metric",
                "text": "Errors fell from 2% to 0.3%.",
                "before": "2%",
                "after": "0.3%",
            },
            {"section": "learning", "slot": "lesson", "text": "Ship in small steps."},
        ],
    )
    assert out.status_code == 200, out.text
    got = out.json()
    role = slot(got, "situation", "role")
    assert role == {
        "text": "I was the **tech lead**.",
        "quotes": [],
        "by_user": True,
        "status": "filled",
    }
    assert got["context"] == "I was the tech lead."
    assert got["action"] == "I split the rollout, because a rollback had to be fast."
    assert slot(got, "result", "metric")["after"] == "0.3%"
    assert got["display_status"] == "ready"


async def test_sc10_clear_skip_add_and_reorder_steps(client: httpx.AsyncClient) -> None:
    """SC-10: a blank text empties a slot, `skipped` marks it, a step index at the end adds a
    step, and `steps` reorders or removes them."""
    await sign_in(client)
    story = await styled(client)
    sid = story["id"]
    one = {"section": "action", "slot": "did", "step": 0, "text": "First I wrote the plan."}
    two = {"section": "action", "slot": "did", "step": 1, "text": "Then I split the rollout."}
    got = (await patch(client, sid, slots=[one, two])).json()
    assert got["action"] == "First I wrote the plan. Then I split the rollout."
    got = (await patch(client, sid, steps=[1, 0])).json()
    assert got["action"] == "Then I split the rollout. First I wrote the plan."
    got = (await patch(client, sid, steps=[0])).json()
    assert got["action"] == "Then I split the rollout."
    got = (
        await patch(
            client,
            sid,
            slots=[
                {"section": "action", "slot": "did", "step": 0, "text": "  "},
                {"section": "situation", "slot": "org", "skipped": True},
            ],
        )
    ).json()
    assert got["action"] is None
    assert slot(got, "situation", "org")["status"] == "skipped"


async def test_sc10_bad_edits_are_refused(client: httpx.AsyncClient) -> None:
    """SC-10: an unknown slot, a step gap, six steps or a bad order is 422; a classic story is
    409 until it is organized."""
    await sign_in(client)
    sid = (await styled(client))["id"]
    bad = [
        {"slots": [{"section": "situation", "slot": "goal", "text": "x"}]},
        {"slots": [{"section": "action", "slot": "did", "step": 2, "text": "x"}]},
        {"steps": [0, 0]},
        {"steps": [3]},
    ]
    for body in bad:
        assert (await patch(client, sid, **body)).status_code == 422, body
    six = [{"section": "action", "slot": "did", "step": i, "text": f"Step {i}"} for i in range(5)]
    assert (await patch(client, sid, slots=six)).status_code == 200
    extra = {"section": "action", "slot": "did", "step": 5, "text": "Six"}
    assert (await patch(client, sid, slots=[extra])).status_code == 422
    plain = await classic(client)
    refused = await patch(client, plain["id"], slots=[])
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "classic_story"


# --- SC-11: Improve with Strova -----------------------------------------------------------------


async def _with_result_words(client: httpx.AsyncClient) -> str:
    sid = (await styled(client))["id"]
    await patch(
        client,
        sid,
        slots=[
            {"section": "result", "slot": "metric", "text": "The migration went well."},
            {
                "section": "result",
                "slot": "impact",
                "text": "We were done a week before Black Friday and not one payment failed.",
            },
        ],
    )
    return sid


async def test_sc11_improve_returns_edits_with_quotes_and_writes_nothing(
    client: httpx.AsyncClient,
) -> None:
    """SC-11, D-10: Improve returns before-and-after edits from the user's words, with quotes,
    and changes nothing until the user accepts; accepting writes Strova's slot with its quotes."""
    await sign_in(client)
    sid = await _with_result_words(client)
    got = await client.post(f"/stories/{sid}/sections/result/improve", json={"note": "Sharper"})
    assert got.status_code == 200, got.text
    improve = got.json()
    [edit] = improve["edits"]
    assert edit["slot"] == "metric" and edit["quotes"]
    assert edit["before"] == "The migration went well."
    story = (await client.get(f"/stories/{sid}")).json()
    assert slot(story, "result", "metric")["text"] == "The migration went well."
    accepted = await client.post(
        f"/stories/{sid}/sections/result/improve/accept", json={"edits": [edit]}
    )
    assert accepted.status_code == 200, accepted.text
    metric = slot(accepted.json(), "result", "metric")
    assert metric["text"] == edit["after"] and metric["quotes"] == edit["quotes"]
    assert metric["by_user"] is False
    assert accepted.json()["result"].startswith(edit["after"])


async def test_sc11_unbacked_edits_become_a_question(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-11, CO-9: an edit whose quotes are not the user's words is dropped; with nothing left,
    Strova asks a question instead. Questions come back as they are."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_fixture(
        fake_fixtures,
        "SectionImprove",
        {
            "edits": [
                {
                    "section": "result",
                    "slot": "metric",
                    "after": "Revenue grew 40% after the launch.",
                    "quotes": ["revenue grew forty percent"],
                }
            ]
        },
    )
    await sign_in(client)
    sid = await _with_result_words(client)
    out = (await client.post(f"/stories/{sid}/sections/result/improve", json={})).json()
    assert out == {"edits": [], "questions": [outline_api.NO_QUESTION]}
    set_fixture(fake_fixtures, "SectionImprove", {"questions": ["By how much did errors fall?"]})
    out = (await client.post(f"/stories/{sid}/sections/result/improve", json={})).json()
    assert out == {"edits": [], "questions": ["By how much did errors fall?"]}


async def test_sc11_accept_refuses_an_edit_that_is_not_the_users_words(
    client: httpx.AsyncClient,
) -> None:
    """SC-11, D-6: accept checks the edits again; one with a fact the user never gave is 422 and
    nothing is written. A note's words count as the user's."""
    await sign_in(client)
    sid = await _with_result_words(client)
    forged = {
        "section": "result",
        "slot": "metric",
        "after": "Revenue grew 40%.",
        "quotes": ["revenue grew 40 percent overall"],
    }
    bad = await client.post(
        f"/stories/{sid}/sections/result/improve/accept", json={"edits": [forged]}
    )
    assert bad.status_code == 422
    with_note = await client.post(
        f"/stories/{sid}/sections/result/improve/accept",
        json={"edits": [forged], "note": "Add that revenue grew 40 percent overall."},
    )
    assert with_note.status_code == 200, with_note.text
    other_section = {**forged, "section": "learning", "slot": "lesson"}
    wrong = await client.post(
        f"/stories/{sid}/sections/result/improve/accept",
        json={"edits": [other_section], "note": "revenue grew 40 percent overall"},
    )
    assert wrong.status_code == 422


# --- SC-13: Organize with Strova ----------------------------------------------------------------


async def test_sc13_organize_writes_nothing_until_accept(client: httpx.AsyncClient) -> None:
    """SC-13, D-11: the preview is a STAR outline quoted from the user's words, and the story is
    unchanged; accept makes it STAR with its parts rendered from the outline."""
    await sign_in(client)
    story = await classic(client)
    preview = await client.post(f"/stories/{story['id']}/organize")
    assert preview.status_code == 200, preview.text
    outline = StoryOutline.model_validate(preview.json()["outline"])
    assert outline.style == StoryStyle.STAR
    same = (await client.get(f"/stories/{story['id']}")).json()
    assert same["style"] is None and same["outline"] is None
    assert same["context"] == CLASSIC["context"]
    accepted = await client.post(f"/stories/{story['id']}/organize/accept", json=preview.json())
    assert accepted.status_code == 200, accepted.text
    got = accepted.json()
    assert got["style"] == "star"
    assert got["context"] == "I was the tech lead for the checkout team."
    assert got["display_status"] == "ready"
    again = await client.post(f"/stories/{story['id']}/organize")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "styled_story"


async def test_sc13_organize_drops_slots_that_are_not_the_users_words(
    client: httpx.AsyncClient,
) -> None:
    """SC-13, D-6: a classic story without some of the quoted words gets those slots empty in the
    preview; an accept body with an invented slot is 422."""
    await sign_in(client)
    story = (
        await client.post("/stories", json={"title": "Checkout", "context": CLASSIC["context"]})
    ).json()
    preview = (await client.post(f"/stories/{story['id']}/organize")).json()
    assert slot(preview, "situation", "role")["status"] == "filled"
    assert slot(preview, "learning", "lesson")["status"] == "empty"
    forged = json.loads(json.dumps(preview))
    lesson = {
        "text": "Always test.",
        "quotes": ["always test everything twice"],
        "status": "filled",
    }
    next(s for s in forged["outline"]["sections"] if s["section"] == "learning")["slots"][
        "lesson"
    ] = lesson
    bad = await client.post(f"/stories/{story['id']}/organize/accept", json=forged)
    assert bad.status_code == 422


# --- SC-12: Switch to STAR or CARL --------------------------------------------------------------


async def test_sc12_switch_without_rewrite_keeps_every_slot_round_trip(
    client: httpx.AsyncClient,
) -> None:
    """SC-12, D-2: STAR to CARL to STAR renames and moves slots in code, keeping every text and
    quote; the Task slots sit in Challenge while the story is CARL."""
    await sign_in(client)
    story = await organized(client)
    before = StoryOutline.model_validate(story["outline"])
    carl = await client.post(f"/stories/{story['id']}/style", json={"style": "carl"})
    assert carl.status_code == 200, carl.text
    as_carl = carl.json()["story"]
    assert as_carl["style"] == "carl" and carl.json()["preview"] is None
    assert slot(as_carl, "challenge", "goal")["quotes"] == slot(story, "task", "goal")["quotes"]
    assert as_carl["stakes"] == story["stakes"] and as_carl["action"] == story["action"]
    back = (await client.post(f"/stories/{story['id']}/style", json={"style": "star"})).json()
    assert StoryOutline.model_validate(back["story"]["outline"]) == before
    assert convert_style(convert_style(before, StoryStyle.CARL), StoryStyle.STAR) == before


async def test_sc12_a_rewrite_needs_accept(client: httpx.AsyncClient) -> None:
    """SC-12, D-2: Rewrite the wording is one model call that returns a preview; the story stays
    as it is until accept, which checks the quotes again."""
    await sign_in(client)
    story = await organized(client)
    out = await client.post(
        f"/stories/{story['id']}/style", json={"style": "carl", "rewrite": True}
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["story"] is None and body["preview"]["style"] == "carl"
    still = (await client.get(f"/stories/{story['id']}")).json()
    assert still["style"] == "star"
    accepted = await client.post(f"/stories/{story['id']}/style/accept", json=body["preview"])
    assert accepted.status_code == 200, accepted.text
    got = accepted.json()
    assert got["style"] == "carl"
    assert slot(got, "challenge", "problem")["text"].startswith("Our move of checkout")
    assert slot(got, "challenge", "goal")["status"] == "filled"  # kept from the moved slots


async def test_sc12_a_rewrite_keeps_the_users_typed_slots(client: httpx.AsyncClient) -> None:
    """SC-12: a slot the user typed stays theirs (by_user) through a rewrite preview."""
    await sign_in(client)
    story = await styled(client)
    await patch(
        client, story["id"], slots=[{"section": "situation", "slot": "org", "text": "Acme"}]
    )
    body = (
        await client.post(f"/stories/{story['id']}/style", json={"style": "carl", "rewrite": True})
    ).json()
    org = slot({"outline": body["preview"]}, "challenge", "org")
    assert org["by_user"] is True and org["text"] == "Acme"


# --- SC-14: a styled story's parts are not edited by suggestions --------------------------------


async def test_sc14_a_part_edit_suggestion_is_refused_on_a_styled_story(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """SC-14: accepting a tune edit would write a part that the next outline save renders over,
    so it is 409 styled_story on a styled story."""
    await sign_in(client)
    story = await organized(client)
    async with sessionmaker() as db:
        row = await db.get(StoryRow, uuid.UUID(story["id"]))
        assert row is not None
        tune = TuneStoryPayload(
            edit=StoryPartEdit(part="result", before="x", after="y z w", quotes=["y z w"])
        )
        suggestion = SuggestionRow(
            org_id=row.org_id,
            user_id=row.user_id,
            kind=SuggestionKind.TUNE_STORY,
            payload=tune.model_dump(mode="json"),
            reason="Because.",
            story_id=row.id,
        )
        db.add(suggestion)
        await db.commit()
        sid = suggestion.id
    out = await client.post(f"/suggestions/{sid}/accept", json={})
    assert out.status_code == 409 and out.json()["detail"]["code"] == "styled_story"
