"""Suggestions from Strova, the API (U08): list by place, accept, dismiss and undo (SG-8), and
what accepting each kind does: tune a story (SG-2), new story (SG-3), missing skill (SG-4),
tailor for a role (SG-5), improve a resume line (SG-6), story idea (RM-4) and review (ST-11).
The debrief carries the take's open suggestions (DB-4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.inputs import queue as queue_names
from strong_api.resume_checks.checks import check_resume
from strong_core.db.models import JobTarget, User
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.schemas import (
    ImproveResumeLinePayload,
    MissingSkillPayload,
    NewStoryPayload,
    Resume,
    ReviewPayload,
    StoryIdeaPayload,
    StoryPartEdit,
    StoryReview,
    StorySource,
    SuggestionKind,
    TailorRolePayload,
    TuneStoryPayload,
)
from strong_worker.suggestions import jobs as suggestion_jobs

from .conftest import InlineQueue, sign_in
from .test_library_api import add_resume, other_client
from .test_scoring_api import (
    ScoringQueue,
    make_session,
    make_target,
    replies,
    sclient,  # noqa: F401  (fixture)
    squeue,  # noqa: F401  (fixture)
)

EMAIL = "dev@example.com"  # the user sign_in() creates


async def _me(
    maker: async_sessionmaker[AsyncSession], email: str = EMAIL
) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user.org_id, user.id


async def _story(maker: async_sessionmaker[AsyncSession], **parts: Any) -> uuid.UUID:
    org_id, user_id = await _me(maker)
    async with maker() as db:
        row = StoryRow(
            org_id=org_id,
            user_id=user_id,
            title=parts.pop("title", "Checkout migration"),
            skills=["ownership"],
            source=StorySource.MANUAL,
            notes_json=[],
            **parts,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _suggest(
    maker: async_sessionmaker[AsyncSession],
    kind: SuggestionKind,
    payload: Any,
    **columns: Any,
) -> str:
    org_id, user_id = await _me(maker)
    async with maker() as db:
        row = SuggestionRow(
            org_id=org_id,
            user_id=user_id,
            kind=kind,
            payload=payload.model_dump(mode="json"),
            reason="Because.",
            **columns,
        )
        db.add(row)
        await db.commit()
        return str(row.id)


async def _get_story(maker: async_sessionmaker[AsyncSession], story_id: uuid.UUID) -> StoryRow:
    async with maker() as db:
        row = await db.get(StoryRow, story_id)
        assert row is not None
        return row


def _tune(after: str = "We finished a week early and not one payment failed.") -> TuneStoryPayload:
    return TuneStoryPayload(
        edit=StoryPartEdit(part="result", before="It went well.", after=after, quotes=[after])
    )


def test_u08_queue_names_match_the_worker_jobs() -> None:
    names = {f.__name__ for f in suggestion_jobs.FUNCTIONS}
    assert {queue_names.SUGGEST_RESUME_LINE, queue_names.REVIEW_STORY} <= names


async def test_sg2_sg8_accept_a_tune_then_undo_restores_the_part(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue
) -> None:
    """SG-2: accepting sets the part (or the user's edit); Undo restores it and reopens the
    suggestion. A result change queues the improve resume line job (SG-6)."""
    await sign_in(client)
    story_id = await _story(sessionmaker, result="It went well.")
    sid = await _suggest(sessionmaker, SuggestionKind.TUNE_STORY, _tune(), story_id=story_id)

    listed = (
        await client.get("/suggestions", params={"place": "story", "story_id": str(story_id)})
    ).json()
    assert [s["id"] for s in listed] == [sid]

    resp = await client.post(f"/suggestions/{sid}/accept", json={"after": "Edited by me."})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["suggestion"]["status"] == "accepted" and out["can_undo"] is True
    assert out["story_id"] == str(story_id)
    assert (await _get_story(sessionmaker, story_id)).result == "Edited by me."
    assert [f for f, _, _ in queue.enqueued] == [queue_names.SUGGEST_RESUME_LINE]
    listed = (
        await client.get("/suggestions", params={"place": "story", "story_id": str(story_id)})
    ).json()
    assert listed == []

    again = await client.post(f"/suggestions/{sid}/accept", json={})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "not_open"

    undo = await client.post(f"/suggestions/{sid}/undo")
    assert undo.status_code == 200, undo.text
    assert undo.json()["status"] == "open"
    assert (await _get_story(sessionmaker, story_id)).result == "It went well."
    nothing = await client.post(f"/suggestions/{sid}/undo")
    assert nothing.status_code == 409 and nothing.json()["detail"]["code"] == "cannot_undo"


async def test_sg2_undo_refuses_when_the_part_changed_since(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await sign_in(client)
    story_id = await _story(sessionmaker, result="It went well.")
    sid = await _suggest(sessionmaker, SuggestionKind.TUNE_STORY, _tune(), story_id=story_id)
    assert (await client.post(f"/suggestions/{sid}/accept", json={})).status_code == 200
    assert (
        await client.patch(f"/stories/{story_id}", json={"result": "Mine now."})
    ).status_code == 200
    undo = await client.post(f"/suggestions/{sid}/undo")
    assert undo.status_code == 409 and undo.json()["detail"]["code"] == "changed_since"
    assert (await _get_story(sessionmaker, story_id)).result == "Mine now."


async def test_sg8_dismiss_hides_it_and_other_users_get_404(
    app: FastAPI, client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """SG-8: a dismissed suggestion leaves every list and cannot be accepted. Another user's
    suggestion answers 404."""
    await sign_in(client)
    story_id = await _story(sessionmaker, result="It went well.")
    sid = await _suggest(sessionmaker, SuggestionKind.TUNE_STORY, _tune(), story_id=story_id)
    async with other_client(app) as other:
        assert (await other.post(f"/suggestions/{sid}/dismiss")).status_code == 404
        assert (await other.post(f"/suggestions/{sid}/accept", json={})).status_code == 404
    resp = await client.post(f"/suggestions/{sid}/dismiss")
    assert resp.status_code == 200 and resp.json()["status"] == "dismissed"
    assert resp.json()["resolved_at"]
    assert (await client.get("/suggestions", params={"place": "stories"})).json() == []
    assert (await client.post(f"/suggestions/{sid}/accept", json={})).status_code == 409
    assert (await client.post(f"/suggestions/{sid}/dismiss")).status_code == 409


async def test_sg8_list_needs_the_places_id(client: httpx.AsyncClient) -> None:
    await sign_in(client)
    assert (await client.get("/suggestions", params={"place": "debrief"})).status_code == 422
    assert (await client.get("/suggestions", params={"place": "elsewhere"})).status_code == 422


async def test_sg3_accept_a_new_story_saves_a_draft_from_the_answer(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await sign_in(client)
    payload = NewStoryPayload(
        title="Checkout before Black Friday",
        context="We moved checkout.",
        action="I wrote the rollback plan.",
        result="Not one payment failed.",
        skills=["ownership"],
        quotes=["I wrote the rollback plan"],
    )
    sid = await _suggest(sessionmaker, SuggestionKind.NEW_STORY, payload, source_question_ref="q1")
    out = (await client.post(f"/suggestions/{sid}/accept", json={})).json()
    assert out["can_undo"] is False
    story = (await client.get(f"/stories/{out['story_id']}")).json()
    assert story["title"] == "Checkout before Black Friday"
    assert story["status"] == "draft" and story["source"] == "debrief_answer"
    assert story["action"] == "I wrote the rollback plan." and story["skills"] == ["ownership"]
    assert out["suggestion"]["story_id"] == out["story_id"]


async def test_sg4_rm4_accept_opens_crafting_with_the_target(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """SG-4: a missing skill opens crafting aimed at that skill and role. RM-4: a story idea
    opens it with the achievement."""
    await sign_in(client)
    org_id, user_id = await _me(sessionmaker)
    async with sessionmaker() as db:
        target = JobTarget(org_id=org_id, user_id=user_id, name="Role")
        db.add(target)
        await db.commit()
    sid = await _suggest(
        sessionmaker,
        SuggestionKind.MISSING_SKILL,
        MissingSkillPayload(competency="conflict_handling"),
        job_target_id=target.id,
    )
    role = (
        await client.get("/suggestions", params={"place": "role", "job_target_id": str(target.id)})
    ).json()
    assert [s["payload"]["competency"] for s in role] == ["conflict_handling"]
    out = (await client.post(f"/suggestions/{sid}/accept", json={})).json()
    assert out["crafting"] == {
        "competency": "conflict_handling",
        "job_target_id": str(target.id),
        "achievement": None,
        "skills": [],
    }
    idea = await _suggest(
        sessionmaker,
        SuggestionKind.STORY_IDEA,
        StoryIdeaPayload(achievement="Built the refunds API", skills=["impact"]),
    )
    out = (await client.post(f"/suggestions/{idea}/accept", json={})).json()
    assert out["crafting"]["achievement"] == "Built the refunds API"
    assert out["crafting"]["skills"] == ["impact"]


async def test_sg5_accept_tailoring_adds_a_for_company_note_and_undo_removes_it(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await sign_in(client)
    story_id = await _story(sessionmaker)
    payload = TailorRolePayload(
        company="Stripe", competency="ownership", note="Lead with the rollback plan."
    )
    sid = await _suggest(sessionmaker, SuggestionKind.TAILOR_ROLE, payload, story_id=story_id)
    stories = (await client.get("/suggestions", params={"place": "stories"})).json()
    assert [s["id"] for s in stories] == [sid]
    assert (await client.post(f"/suggestions/{sid}/accept", json={})).status_code == 200
    notes = (await client.get(f"/stories/{story_id}/notes")).json()
    assert [n["text"] for n in notes] == ["For Stripe: Lead with the rollback plan."]
    assert (await client.post(f"/suggestions/{sid}/undo")).status_code == 200
    assert (await client.get(f"/stories/{story_id}/notes")).json() == []


async def test_sg6_accept_a_resume_line_updates_it_and_the_check_runs_again(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_fixtures: Path,
    queue: InlineQueue,
) -> None:
    """SG-6: the line changes in the resume, the resume check on its next read sees the new
    line, the story ideas job runs again; Undo puts the old line back."""
    await sign_in(client)
    resume = await add_resume(client, fake_fixtures)
    rid = resume["id"]
    line = resume["resume"]["roles"][0]["achievements"][0]
    new = "Led the payout redesign; failed payouts fell by 38% in one quarter"
    payload = ImproveResumeLinePayload(
        resume_line_ref="roles[0].achievements[0]", before=line, after=new, quotes=[new]
    )
    sid = await _suggest(
        sessionmaker, SuggestionKind.IMPROVE_RESUME_LINE, payload, resume_id=uuid.UUID(rid)
    )
    listed = (await client.get("/suggestions", params={"place": "resume", "resume_id": rid})).json()
    assert sid in [s["id"] for s in listed]
    queue.enqueued.clear()
    out = (await client.post(f"/suggestions/{sid}/accept", json={})).json()
    assert out["resume_id"] == rid and out["can_undo"] is True
    stored = (await client.get(f"/resumes/{rid}")).json()["resume"]
    assert stored["roles"][0]["achievements"][0] == new
    issues = (await client.get(f"/resumes/{rid}/issues")).json()
    today = datetime.now(UTC).strftime("%Y-%m")
    assert [i["key"] for i in issues["open"]] == [
        i.key for i in check_resume(Resume.model_validate(stored), today=today)
    ]
    assert queue_names.STORY_IDEA_SKILLS in [f for f, _, _ in queue.enqueued]

    assert (await client.post(f"/suggestions/{sid}/undo")).status_code == 200
    stored = (await client.get(f"/resumes/{rid}")).json()["resume"]
    assert stored["roles"][0]["achievements"][0] == line


async def test_st11_accept_a_review_applies_the_chosen_edits(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await sign_in(client)
    story_id = await _story(sessionmaker, context="Old context.", result="It went well.")
    review = StoryReview.model_validate(
        {
            "summary": "Good action. Fix the result.",
            "notes": [
                {
                    "part": "result",
                    "note": "Use your number.",
                    "edit": {
                        "part": "result",
                        "before": "x",
                        "after": "Not one payment failed.",
                        "quotes": [],
                    },
                },
                {
                    "part": "context",
                    "note": "Shorter.",
                    "edit": {
                        "part": "context",
                        "before": "x",
                        "after": "New context.",
                        "quotes": [],
                    },
                },
                {"part": "reflection", "note": "Add one."},
            ],
        }
    )
    sid = await _suggest(
        sessionmaker, SuggestionKind.REVIEW, ReviewPayload(review=review), story_id=story_id
    )
    out = (await client.post(f"/suggestions/{sid}/accept", json={"parts": ["result"]})).json()
    assert out["can_undo"] is True
    # One edit is left, so the review stays open (ST-11: accept or skip each edit).
    assert out["suggestion"]["status"] == "open"
    story = await _get_story(sessionmaker, story_id)
    assert story.result == "Not one payment failed." and story.context == "Old context."
    out = (await client.post(f"/suggestions/{sid}/accept", json={"parts": ["context"]})).json()
    assert out["suggestion"]["status"] == "accepted"
    assert (await _get_story(sessionmaker, story_id)).context == "New context."
    assert (await client.post(f"/suggestions/{sid}/undo")).status_code == 200
    story = await _get_story(sessionmaker, story_id)
    assert story.result == "It went well." and story.context == "Old context."


async def test_db4_the_debrief_lists_the_takes_open_suggestions(
    sessionmaker: async_sessionmaker[AsyncSession],
    squeue: ScoringQueue,  # noqa: F811
    sclient: httpx.AsyncClient,  # noqa: F811
) -> None:
    """DB-4, SG-4: after scoring, the debrief has the take's suggestions (with no stories, every
    tested skill is missing), and the plan item is null until U11."""
    target = await make_target(sessionmaker, gap=True)
    sid = await make_session(sessionmaker, target)
    squeue.replies = [*replies(), "STORY: NONE\nFIX: none"]
    assert (await sclient.post(f"/sessions/{sid}/scoring")).status_code == 202
    debrief = (await sclient.get(f"/sessions/{sid}/debrief")).json()
    kinds = {s["kind"] for s in debrief["suggestions"]}
    assert "missing_skill" in kinds
    assert all(s["source_session_id"] == str(sid) for s in debrief["suggestions"])
    assert debrief["next_plan_item"] is None
    listed = (
        await sclient.get("/suggestions", params={"place": "debrief", "session_id": str(sid)})
    ).json()
    assert [s["id"] for s in listed] == [s["id"] for s in debrief["suggestions"]]
