"""Story library API (S20): ST-1 (owner only, org scoping, export, delete), ST-2, ST-6 notes."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import Scorecard
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Turn as TurnRow
from strong_core.schemas import HireSignal, Speaker, Story

from .accounts_support import FakeStripe
from .conftest import sign_in
from .test_scoring_api import make_session, make_target

Maker = async_sessionmaker[AsyncSession]


def story_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Payments outage",
        "context": "Checkout failed for 2% of users.",
        "action": "I traced it to a retry storm and added backoff.",
        "skills": ["impact", "ownership"],
    }
    body.update(over)
    return body


async def other_client(app: FastAPI) -> httpx.AsyncClient:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    await sign_in(http, "bo@example.com")
    return http


async def scored_session(maker: Maker) -> tuple[uuid.UUID, dict[str, Any]]:
    """An ended session of the dev user with a scorecard for its first answered question.
    Returns the session id and that QuestionScore."""
    session_id = await make_session(maker, await make_target(maker))
    async with maker() as db:
        turns = list(
            await db.scalars(
                select(TurnRow)
                .where(
                    TurnRow.session_id == session_id,
                    TurnRow.speaker == Speaker.CANDIDATE,
                    TurnRow.question_ref.is_not(None),
                )
                .order_by(TurnRow.start_ms)
            )
        )
        ref = turns[0].question_ref
        assert ref is not None
        question = {
            "question_ref": ref,
            "question_text": "Tell me about a time you fixed a production problem.",
            "scores": [
                {
                    "competency": "impact",
                    "score": 3,
                    "justification": "Clear steps.",
                    "quotes": ["I traced it"],
                },
                {
                    "competency": "ownership",
                    "score": 2,
                    "justification": "Some ownership.",
                    "quotes": ["I did it"],
                },
            ],
        }
        org_id = turns[0].org_id
        db.add(
            Scorecard(
                org_id=org_id,
                session_id=session_id,
                hire_signal=HireSignal.LEAN_HIRE,
                rationale="Fine.",
                competency_scores_json=[],
                per_question_json=[question],
                scorer_model="scorer",
                rubric_version="scorer/rubric.v1",
            )
        )
        await db.commit()
    return session_id, question


# --- ST-1 CRUD -------------------------------------------------------------------------------


async def test_st1_create_get_list_update_delete(client: httpx.AsyncClient) -> None:
    """ST-1: a story is created as a draft, read, edited by part and deleted."""
    resp = await client.post("/stories", json=story_body())
    assert resp.status_code == 201, resp.text
    story = Story.model_validate(resp.json())
    assert story.status == "draft" and story.source == "manual"
    assert story.context == "Checkout failed for 2% of users."
    assert story.stakes is None and story.notes == []

    got = await client.get(f"/stories/{story.id}")
    assert got.status_code == 200 and got.json() == resp.json()

    patched = await client.patch(
        f"/stories/{story.id}", json={"result": "  Errors fell to zero.  ", "context": None}
    )
    assert patched.status_code == 200, patched.text
    after = patched.json()
    assert after["result"] == "Errors fell to zero."
    assert after["context"] is None
    assert after["action"] == story.action  # not sent, so unchanged
    assert after["title"] == "Payments outage"

    tags = await client.patch(f"/stories/{story.id}", json={"skills": ["communication"]})
    assert tags.json()["skills"] == ["communication"]
    blank = await client.patch(f"/stories/{story.id}", json={"title": "   "})
    assert blank.status_code == 422
    # The status is set by scoring (ST-7), never by hand.
    assert (
        await client.patch(f"/stories/{story.id}", json={"status": "proven"})
    ).status_code == 422

    assert (await client.delete(f"/stories/{story.id}")).status_code == 204
    assert (await client.get(f"/stories/{story.id}")).status_code == 404
    assert (await client.get("/stories")).json() == []


async def test_st1_bad_bodies_are_refused(client: httpx.AsyncClient) -> None:
    """ST-1: repeated skills, unknown fields and the debrief source are refused on create."""
    assert (
        await client.post("/stories", json=story_body(skills=["ownership", "ownership"]))
    ).status_code == 422
    assert (await client.post("/stories", json=story_body(extra=1))).status_code == 422
    assert (
        await client.post("/stories", json=story_body(source="debrief_answer"))
    ).status_code == 422
    assert (await client.post("/stories", json=story_body(title=""))).status_code == 422


async def test_st1_list_filters_by_status_and_skill(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """ST-1: the list is newest first and filters by status and by skill tag."""
    first = (await client.post("/stories", json=story_body(title="One"))).json()
    second = (
        await client.post("/stories", json=story_body(title="Two", skills=["communication"]))
    ).json()
    async with sessionmaker() as db:
        row = await db.get(StoryRow, uuid.UUID(first["id"]))
        assert row is not None
        row.status = "proven"
        await db.commit()

    titles = [s["title"] for s in (await client.get("/stories")).json()]
    assert set(titles) == {"One", "Two"}
    proven = (await client.get("/stories", params={"status": "proven"})).json()
    assert [s["id"] for s in proven] == [first["id"]]
    drafts = (await client.get("/stories", params={"status": "draft"})).json()
    assert [s["id"] for s in drafts] == [second["id"]]
    comm = (await client.get("/stories", params={"skill": "communication"})).json()
    assert [s["id"] for s in comm] == [second["id"]]
    assert (await client.get("/stories", params={"skill": "nope"})).status_code == 422


async def test_st1_stories_are_owner_only(app: FastAPI, client: httpx.AsyncClient) -> None:
    """ST-1: another user can neither see, edit, delete nor add notes to a story (404)."""
    story = (await client.post("/stories", json=story_body())).json()
    other = await other_client(app)
    try:
        assert (await other.get("/stories")).json() == []
        assert (await other.get(f"/stories/{story['id']}")).status_code == 404
        assert (
            await other.patch(f"/stories/{story['id']}", json={"title": "Mine now"})
        ).status_code == 404
        assert (await other.delete(f"/stories/{story['id']}")).status_code == 404
        assert (
            await other.post(f"/stories/{story['id']}/notes", json={"text": "x"})
        ).status_code == 404
        assert (await other.get(f"/stories/{story['id']}/notes")).status_code == 404
    finally:
        await other.aclose()
    assert (await client.get(f"/stories/{story['id']}")).json()["title"] == "Payments outage"


async def test_st1_stories_are_scoped_by_org_and_user(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """ST-1: a story row with the user's id but another org is not theirs."""
    story = (await client.post("/stories", json=story_body())).json()
    async with sessionmaker() as db:
        from strong_core.db.models import Org

        row = await db.get(StoryRow, uuid.UUID(story["id"]))
        assert row is not None
        org = Org(name="elsewhere")
        db.add(org)
        await db.flush()
        row.org_id = org.id
        await db.commit()
    assert (await client.get(f"/stories/{story['id']}")).status_code == 404
    assert (await client.get("/stories")).json() == []


async def test_st1_stories_need_sign_in(anon_client: httpx.AsyncClient) -> None:
    """ST-1: every story route needs a signed-in user."""
    assert (await anon_client.get("/stories")).status_code == 401
    assert (await anon_client.post("/stories", json=story_body())).status_code == 401


# --- ST-6 notes ------------------------------------------------------------------------------


async def test_st6_notes_append_and_list(client: httpx.AsyncClient) -> None:
    """ST-6: fix notes are appended in order and come back with the story."""
    story = (await client.post("/stories", json=story_body())).json()
    session_id = str(uuid.uuid4())
    first = await client.post(
        f"/stories/{story['id']}/notes",
        json={"text": "Say the result in numbers.", "session_id": session_id, "question_ref": "q1"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["session_id"] == session_id
    await client.post(f"/stories/{story['id']}/notes", json={"text": "Shorter context."})

    notes = (await client.get(f"/stories/{story['id']}/notes")).json()
    assert [n["text"] for n in notes] == ["Say the result in numbers.", "Shorter context."]
    assert (await client.get(f"/stories/{story['id']}")).json()["notes"] == notes
    assert (
        await client.post(f"/stories/{story['id']}/notes", json={"text": ""})
    ).status_code == 422


# --- ST-2 ------------------------------------------------------------------------------------


async def test_st2_save_debrief_answer_as_draft_story(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """ST-2: a debrief answer becomes a draft story with the answer, the scored skills and a
    link to its source; the same answer cannot be saved twice."""
    session_id, question = await scored_session(sessionmaker)
    ref = question["question_ref"]
    async with sessionmaker() as db:
        said = list(
            await db.scalars(
                select(TurnRow.text)
                .where(
                    TurnRow.session_id == session_id,
                    TurnRow.question_ref == ref,
                    TurnRow.speaker == Speaker.CANDIDATE,
                )
                .order_by(TurnRow.start_ms)
            )
        )

    resp = await client.post(
        "/stories/from-answer", json={"session_id": str(session_id), "question_ref": ref}
    )
    assert resp.status_code == 201, resp.text
    story = Story.model_validate(resp.json())
    assert story.status == "draft" and story.source == "debrief_answer"
    assert story.title == question["question_text"]
    assert story.action == "\n\n".join(t.strip() for t in said)
    assert story.context is None and story.result is None
    assert [s.value for s in story.skills] == ["impact", "ownership"]
    assert story.source_session_id == session_id and story.source_question_ref == ref

    again = await client.post(
        "/stories/from-answer",
        json={"session_id": str(session_id), "question_ref": ref, "title": "Other"},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "story_exists"
    assert again.json()["detail"]["story_id"] == str(story.id)


async def test_st2_from_answer_errors(
    app: FastAPI, client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """ST-2: an unknown question, a session without a debrief, or another user's session."""
    session_id, question = await scored_session(sessionmaker)
    missing = await client.post(
        "/stories/from-answer", json={"session_id": str(session_id), "question_ref": "nope"}
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "question_not_found"

    unscored = await make_session(sessionmaker, await make_target(sessionmaker))
    resp = await client.post(
        "/stories/from-answer",
        json={"session_id": str(unscored), "question_ref": question["question_ref"]},
    )
    assert resp.status_code == 404 and resp.json()["detail"]["code"] == "scorecard_not_found"

    other = await other_client(app)
    try:
        resp = await other.post(
            "/stories/from-answer",
            json={"session_id": str(session_id), "question_ref": question["question_ref"]},
        )
        assert resp.status_code == 404
    finally:
        await other.aclose()


async def test_st2_answer_without_text_is_refused(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """ST-2: a scored question the candidate said nothing for gives 422 answer_empty."""
    session_id, question = await scored_session(sessionmaker)
    async with sessionmaker() as db:
        card = await db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        assert card is not None
        card.per_question_json = [{**question, "question_ref": "silent"}]
        await db.commit()
    resp = await client.post(
        "/stories/from-answer", json={"session_id": str(session_id), "question_ref": "silent"}
    )
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "answer_empty"


# --- ST-1, AC-1 export and delete ------------------------------------------------------------


@pytest.fixture
def account_app(app: FastAPI) -> FastAPI:
    app.state.stripe = FakeStripe()
    return app


async def test_st1_ac1_export_has_stories_and_notes_and_delete_removes_them(
    account_app: FastAPI,
    client: httpx.AsyncClient,
    sessionmaker: Maker,
    ctx: dict[str, Any],
) -> None:
    """ST-1, AC-1: the data export holds the user's stories with their notes (and no one
    else's); deleting the account removes every story."""
    story = (await client.post("/stories", json=story_body())).json()
    await client.post(f"/stories/{story['id']}/notes", json={"text": "Add the numbers."})
    other = await other_client(account_app)
    try:
        await other.post("/stories", json=story_body(title="Bo's story"))
    finally:
        await other.aclose()

    export = (await client.post("/account/export")).json()
    assert export["status"] == "ready"
    resp = await client.get(f"/account/export/{export['id']}/download")
    data = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("data.json"))
    rows = data["tables"]["stories"]
    assert [r["id"] for r in rows] == [story["id"]]
    assert rows[0]["title"] == "Payments outage"
    assert [n["text"] for n in rows[0]["notes_json"]] == ["Add the numbers."]

    assert (await client.delete("/account")).status_code == 202
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count(StoryRow.id))) == 1  # only Bo's is left
        left = await db.scalar(select(StoryRow.title))
        assert left == "Bo's story"
