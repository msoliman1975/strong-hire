"""U10: the story API for Career Stories with Strova: the status to show (ST-8), Review with
Strova (ST-11) and Ask Strova (ST-13)."""

from __future__ import annotations

from typing import Any

import httpx

from strong_api.inputs import queue as queue_names
from strong_api.stories.ask import FALLBACK

from .conftest import InlineQueue, sign_in

FULL = {
    "context": "Our checkout ran on a payments service three teams depended on.",
    "stakes": "About 2 percent of checkouts failed every week.",
    "action": "I wrote the migration plan and ran a weekly review of error rates.",
    "result": "Checkout errors dropped 40 percent in six weeks.",
    "reflection": "I would bring the platform team in earlier.",
}


async def _story(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    resp = await client.post("/stories", json={"title": "Checkout migration", **body})
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


async def test_st8_display_status_is_draft_ready_or_proven(client: httpx.AsyncClient) -> None:
    """ST-8: a draft with all five parts filled shows as Ready; a part cleared makes it a draft
    again. Proven stays as stored (ST-7)."""
    await sign_in(client)
    partial = await _story(client, action="I wrote the plan.")
    assert partial["status"] == "draft" and partial["display_status"] == "draft"
    full = await _story(client, **FULL)
    assert full["status"] == "draft" and full["display_status"] == "ready"
    listed = {s["id"]: s["display_status"] for s in (await client.get("/stories")).json()}
    assert listed == {partial["id"]: "draft", full["id"]: "ready"}
    cleared = (await client.patch(f"/stories/{full['id']}", json={"reflection": "  "})).json()
    assert cleared["display_status"] == "draft"


async def test_st11_review_queues_strovas_review_as_a_story_suggestion(
    client: httpx.AsyncClient, queue: InlineQueue
) -> None:
    """ST-11: POST /stories/{id}/review queues the worker's review; it arrives as one open
    `review` suggestion for the story, with per-part notes and edits from the user's words."""
    await sign_in(client)
    story = await _story(
        client,
        context="We were done a week before Black Friday and not one payment failed.",
        result="The migration went well.",
    )
    resp = await client.post(f"/stories/{story['id']}/review")
    assert resp.status_code == 202, resp.text
    (function, job_id, kwargs) = queue.enqueued[-1]
    assert function == queue_names.REVIEW_STORY == "review_story"
    assert resp.json() == {"job_id": job_id}
    assert kwargs["story_id"] == story["id"]
    assert queue.results[job_id]["outcome"] == "reviewed"
    listed = (
        await client.get("/suggestions", params={"place": "story", "story_id": story["id"]})
    ).json()
    (review,) = [s for s in listed if s["kind"] == "review"]
    notes = {n["part"]: n for n in review["payload"]["review"]["notes"]}
    assert notes["result"]["edit"]["before"] == "The migration went well."
    assert notes["reflection"]["edit"] is None
    other = await client.post("/stories/00000000-0000-4000-8000-000000000000/review")
    assert other.status_code == 404


async def test_st13_ask_strova_answers_from_the_users_stories(client: httpx.AsyncClient) -> None:
    """ST-13: the answer leans on the user's own words (the quote is checked) and only their
    story ids."""
    await sign_in(client)
    await _story(client, **FULL)
    resp = await client.post("/stories/ask", json={"question": "Which story should I lead with?"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "40 percent" in data["answer"]
    assert data["quotes"] == ["Checkout errors dropped 40 percent in six weeks"]


async def test_st13_an_answer_with_facts_the_user_never_wrote_gives_the_fallback(
    client: httpx.AsyncClient,
) -> None:
    """ST-13, CO-9: with no story holding the quoted words, the checked answer fails twice and
    Strova gives the plain fallback instead of the unbacked one."""
    await sign_in(client)
    await _story(client, action="I wrote the plan.")
    data = (await client.post("/stories/ask", json={"question": "What should I lead with?"})).json()
    assert data == {"answer": FALLBACK, "story_ids": [], "quotes": []}
    assert (await client.post("/stories/ask", json={"question": ""})).status_code == 422
