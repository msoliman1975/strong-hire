"""Write it yourself in STAR or CARL (SC-1, SC-10): POST /stories with a style creates a styled
story whose outline holds the user's typed slots, with no model call; classic stays classic."""

from __future__ import annotations

from typing import Any

import httpx

from .conftest import sign_in


async def create(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/stories", json={"title": "Checkout migration", **body})


def slot(story: dict[str, Any], section: str, key: str) -> dict[str, Any]:
    sec = next(s for s in story["outline"]["sections"] if s["section"] == section)
    if key == "metric":
        out: dict[str, Any] = sec["metric"]
        return out
    found: dict[str, Any] = sec["slots"].get(key, {"status": "empty"})
    return found


async def test_sc1_sc10_write_a_star_story_in_its_slots(client: httpx.AsyncClient) -> None:
    """SC-1, SC-10, SC-14: a written STAR story keeps the user's text in its slots (by_user, no
    quotes), renders the five parts, and is Ready when the core slots are filled (SC-3)."""
    await sign_in(client)
    slots = [
        {"section": "situation", "slot": "role", "text": "I was the **tech lead**."},
        {"section": "situation", "slot": "problem", "text": "Checkout was two weeks late."},
        {"section": "action", "slot": "did", "step": 0, "text": "I split the rollout."},
        {"section": "action", "slot": "why", "step": 0, "text": "A rollback had to be fast."},
        {"section": "action", "slot": "did", "step": 1, "text": "I ran a daily check-in."},
        {"section": "result", "slot": "metric", "text": "Errors fell to 0.3%.", "after": "0.3%"},
        {"section": "learning", "slot": "lesson", "text": "Ship in small steps."},
    ]
    response = await create(client, style="star", slots=slots, skills=["ownership"])
    assert response.status_code == 201, response.text
    story = response.json()
    assert story["style"] == "star" and story["source"] == "manual"
    assert slot(story, "situation", "role") == {
        "text": "I was the **tech lead**.",
        "quotes": [],
        "by_user": True,
        "status": "filled",
    }
    assert slot(story, "result", "metric")["after"] == "0.3%"
    assert story["context"] == "I was the tech lead."
    assert story["action"] == (
        "I split the rollout, because a rollback had to be fast. I ran a daily check-in."
    )
    assert story["display_status"] == "ready"


async def test_sc1_a_carl_story_can_start_with_only_a_title(client: httpx.AsyncClient) -> None:
    """SC-1: a CARL story with no slot yet is an empty outline, a Draft, ready to fill later."""
    await sign_in(client)
    story = (await create(client, style="carl")).json()
    assert [s["section"] for s in story["outline"]["sections"]] == [
        "challenge",
        "action",
        "result",
        "learning",
    ]
    assert story["display_status"] == "draft" and story["context"] is None


async def test_sc1_classic_writing_is_unchanged(client: httpx.AsyncClient) -> None:
    """ST-1: without a style, the five parts are written as today."""
    await sign_in(client)
    story = (await create(client, context="We were late.", stakes="Black Friday.")).json()
    assert story["style"] is None and story["outline"] is None
    assert story["context"] == "We were late."


async def test_sc10_bad_written_stories_are_refused(client: httpx.AsyncClient) -> None:
    """SC-10: parts with a style, slots without one, or an unknown slot are 422."""
    await sign_in(client)
    assert (await create(client, style="star", context="x")).status_code == 422
    one = [{"section": "situation", "slot": "role", "text": "x"}]
    assert (await create(client, slots=one)).status_code == 422
    goal = [{"section": "situation", "slot": "goal", "text": "x"}]
    assert (await create(client, style="star", slots=goal)).status_code == 422
    gap = [{"section": "action", "slot": "did", "step": 2, "text": "x"}]
    assert (await create(client, style="star", slots=gap)).status_code == 422
