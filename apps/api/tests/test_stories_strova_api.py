"""U10: the story API for Career Stories with Strova: the status to show (ST-8), Review with
Strova (ST-11) and Ask Strova (ST-13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from strong_api.coach.router import title_from_idea
from strong_api.inputs import queue as queue_names
from strong_api.stories.ask import FALLBACK

from .conftest import InlineQueue, sign_in
from .test_library_api import add_resume

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


async def test_st12_craft_from_a_resume_idea_seeds_the_context_and_asks_for_the_stakes(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """ST-12: starting from a story idea (RM-4), the achievement seeds the context and Strova's
    first question asks for the stakes. The story is first named after the achievement."""
    await sign_in(client)
    resume = await add_resume(client, fake_fixtures)
    line = resume["resume"]["roles"][0]["achievements"][0]
    resp = await client.post(
        "/coach/sessions",
        json={"resume_id": resume["id"], "resume_line_ref": "roles[0].achievements[0]"},
    )
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    assert detail["story"]["context"] == line
    assert detail["story"]["title"] == title_from_idea(line)
    first = detail["turns"][0]["text"]
    assert first.startswith(f'Let\'s turn this resume line into a story: "{line}".')
    assert "stake" in first.lower() or "matter" in first.lower()
    bad = await client.post(
        "/coach/sessions",
        json={"resume_id": resume["id"], "resume_line_ref": "roles[9].achievements[0]"},
    )
    assert bad.status_code == 404
    half = await client.post("/coach/sessions", json={"resume_id": resume["id"]})
    assert half.status_code == 422


def test_st12_a_story_from_an_idea_is_named_after_the_achievement() -> None:
    """ST-12: the first name is the achievement in the user's words, cut at a word near 60
    characters; a short line is used as it is, without its full stop."""
    assert title_from_idea("Built the refunds API used by 40,000 merchants.") == (
        "Built the refunds API used by 40,000 merchants"
    )
    long = "Led migration of 30 services to PostgreSQL 15 with zero downtime across three regions"
    title = title_from_idea(long)
    assert title == "Led migration of 30 services to PostgreSQL 15 with zero…"
    assert len(title) <= 60
    assert title_from_idea("   ") == "Untitled story"
