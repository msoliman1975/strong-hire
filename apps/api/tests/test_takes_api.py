"""Takes (CO-7) and the coach's 60-second and full versions (CO-8) on the fake model.

The versions tests use the default fixture `fixtures/coach/StoryVersions.json`. The candidate's
words below (coach turns and a take) hold every quote in it; the coach's parts do not.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.takes import router as takes_router  # the module
from strong_api.takes import versions
from strong_api.takes.words import own_words
from strong_core.db.models import (
    CoachSession,
    CoachTurn,
    InterviewSession,
    JobTarget,
    ProgressSnapshot,
    Story,
    Take,
    User,
)
from strong_core.db.models import Turn as TurnRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import (
    CoachSessionStatus,
    CoachSpeaker,
    CoachStyle,
    Competency,
    Difficulty,
    InterviewType,
    Level,
    Mode,
    Phase,
    SessionChannel,
    SessionStatus,
    Speaker,
    StorySource,
    StoryStatus,
    StoryVersion,
)
from strong_worker.scoring import jobs, takes
from strong_worker.scoring.testing import ScriptedBackend, scorecard_reply

from .conftest import InlineQueue, sign_in

CONTEXT = (
    "Last year we were moving checkout to the new payments provider, and the rollout was "
    "already two weeks late."
)
STAKES = "Black Friday was a month out and checkout could not break."
ACTION = "I wrote the rollback plan, and we moved traffic in five percent steps."
REFLECTION = "Next time I would get the rollback plan agreed up front."
RESULT_TAKE = "In the end we were done a week before Black Friday and not one payment failed."


async def _user(maker: async_sessionmaker[AsyncSession], email: str) -> User:
    async with maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user


async def _story(
    maker: async_sessionmaker[AsyncSession],
    user: User,
    *,
    skills: list[str] | None = None,
    parts: bool = True,
    status: StoryStatus = StoryStatus.DRAFT,
    source: StorySource = StorySource.COACH,
) -> Story:
    async with maker() as db:
        story = Story(
            org_id=user.org_id,
            user_id=user.id,
            title="the checkout migration",
            context=CONTEXT if parts else None,
            stakes=STAKES if parts else None,
            action=ACTION if parts else None,
            reflection=REFLECTION if parts else None,
            skills=["ownership"] if skills is None else skills,
            notes_json=[],
            status=status,
            source=source,
        )
        db.add(story)
        await db.commit()
        return story


async def _run_take_job(
    queue: InlineQueue, maker: async_sessionmaker[AsyncSession], reply: dict[str, Any]
) -> dict[str, Any]:
    """Run the queued score_take job the way the worker would, on a scripted scorer reply."""
    function, job_id, kwargs = queue.enqueued[-1]
    assert function == takes_router.SCORE_TAKE
    gateway = ModelGateway(fake_models_config(), fake=ScriptedBackend([reply]))
    ctx = {jobs.CTX_KEY: jobs.ScoringContext(sessionmaker=maker, gateway=gateway)}
    result = await takes.score_take(ctx, **kwargs)
    queue.results[job_id] = result
    return result


def _reply(text: str, **kw: Any) -> dict[str, Any]:
    brief = takes.take_brief("the checkout migration", [Competency.OWNERSHIP], Level.MID)
    return scorecard_reply(brief, takes.take_turns(brief.questions[0].text, text), 3, **kw)


def test_co7_queue_name_matches_the_worker_job() -> None:
    assert takes_router.SCORE_TAKE in {f.__name__ for f in takes.FUNCTIONS}


# --- CO-7: takes -----------------------------------------------------------------------------


async def test_co7_take_is_stored_queued_and_scored(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue
) -> None:
    """CO-7: a typed take is stored, scored 1 to 4 on the story's skills by the scorer job, and
    never changes the story's status or writes a progress snapshot."""
    queue.run_jobs = False
    await sign_in(client)
    story = await _story(sessionmaker, await _user(sessionmaker, "dev@example.com"))
    text = f"{ACTION} {RESULT_TAKE}"

    resp = await client.post(f"/stories/{story.id}/takes", json={"text": text})
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["status"] == "scoring" and created["scores"] == []
    assert created["channel"] == "text" and created["duration_s"] is None

    result = await _run_take_job(queue, sessionmaker, _reply(text))
    assert result["outcome"] == "scored"

    got = (await client.get(f"/stories/{story.id}/takes/{created['id']}")).json()
    assert got["status"] == "scored"
    [score] = got["scores"]
    assert score["competency"] == "ownership" and score["score"] == 3
    assert all(q in text for q in score["quotes"])

    listed = (await client.get(f"/stories/{story.id}/takes")).json()
    assert [t["id"] for t in listed] == [created["id"]]
    async with sessionmaker() as db:
        row = await db.get(Story, story.id)
        assert row is not None and row.status == StoryStatus.DRAFT
        assert await db.scalar(select(func.count()).select_from(ProgressSnapshot)) == 0
        take = await db.get(Take, uuid.UUID(created["id"]))
        assert take is not None and take.model_profile == "fake" and take.prompt_version


async def test_co7_voice_take_and_failed_scoring(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue
) -> None:
    """CO-7: a spoken take keeps its channel and length; a take whose quotes are not found shows
    as failed with a reason."""
    queue.run_jobs = False
    await sign_in(client)
    story = await _story(sessionmaker, await _user(sessionmaker, "dev@example.com"))
    body = {"text": RESULT_TAKE, "channel": "voice", "duration_s": 48.5}
    created = (await client.post(f"/stories/{story.id}/takes", json=body)).json()
    assert created["channel"] == "voice" and created["duration_s"] == 48.5

    await _run_take_job(queue, sessionmaker, _reply(RESULT_TAKE, quote="never said these words"))
    got = (await client.get(f"/stories/{story.id}/takes/{created['id']}")).json()
    assert got["status"] == "failed" and got["reason"]


async def test_co7_take_needs_an_own_tagged_story(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue
) -> None:
    queue.run_jobs = False
    await sign_in(client, "other@example.com")
    other = await _story(sessionmaker, await _user(sessionmaker, "other@example.com"))
    await sign_in(client)
    me = await _user(sessionmaker, "dev@example.com")
    untagged = await _story(sessionmaker, me, skills=[])

    assert (await client.post(f"/stories/{other.id}/takes", json={"text": "x"})).status_code == 404
    assert (await client.get(f"/stories/{other.id}/takes")).status_code == 404
    resp = await client.post(f"/stories/{untagged.id}/takes", json={"text": "x"})
    assert resp.status_code == 422
    assert queue.enqueued == []


# --- CO-8: versions --------------------------------------------------------------------------


# The coach's wording of the parts (CO-3). Close to what the candidate said, but not the same
# words, so the versions must never quote it.
COACH_PARTS = {
    "context": "We were moving checkout to a new payments provider, two weeks behind plan.",
    "stakes": "Black Friday was a month away and checkout had to keep working.",
    "action": "I wrote the rollback plan and moved traffic in 5% steps.",
    "reflection": "Next time I would agree the rollback plan before starting.",
}


async def _coach_story(
    maker: async_sessionmaker[AsyncSession], user: User, candidate: list[str]
) -> Story:
    """A coach story: parts in the coach's words, the candidate's words in a coach session."""
    async with maker() as db:
        story = Story(
            org_id=user.org_id,
            user_id=user.id,
            title="the checkout migration",
            skills=["ownership"],
            notes_json=[],
            status=StoryStatus.DRAFT,
            source=StorySource.COACH,
            **COACH_PARTS,
        )
        db.add(story)
        await db.flush()
        session = CoachSession(
            org_id=user.org_id,
            user_id=user.id,
            story_id=story.id,
            style=CoachStyle.GENTLE,
            channel=SessionChannel.TEXT,
            status=CoachSessionStatus.ENDED,
            minutes=3,
            started_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()
        lines = [(s, t) for text in candidate for s, t in _exchange(text)]
        for seq, (speaker, text) in enumerate(lines, 1):
            db.add(
                CoachTurn(
                    org_id=user.org_id,
                    coach_session_id=session.id,
                    seq=seq,
                    speaker=speaker,
                    text=text,
                    start_ms=seq * 1000,
                    end_ms=seq * 1000 + 500,
                )
            )
        await db.commit()
        return story


def _exchange(text: str) -> list[tuple[CoachSpeaker, str]]:
    return [(CoachSpeaker.COACH, "Tell me more."), (CoachSpeaker.CANDIDATE, text)]


async def test_co8_versions_quote_the_candidates_turns_and_takes(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue
) -> None:
    """CO-8: a 60-second and a full version; every quote is in what the candidate said (coach
    turns and takes), never in the coach's parts."""
    queue.run_jobs = False
    await sign_in(client)
    user = await _user(sessionmaker, "dev@example.com")
    story = await _coach_story(sessionmaker, user, [CONTEXT, STAKES, ACTION, REFLECTION])
    await client.post(f"/stories/{story.id}/takes", json={"text": RESULT_TAKE})

    resp = await client.post(f"/stories/{story.id}/versions")
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["sixty_second"]["text"] and out["full"]["text"].startswith("Context:")
    said = versions.said_text([CONTEXT, STAKES, ACTION, REFLECTION, RESULT_TAKE])
    for v in ("sixty_second", "full"):
        assert all(versions.quote_found(q, said) for q in out[v]["quotes"])
    async with sessionmaker() as db:
        row = await db.get(Story, story.id)
        assert row is not None and row.status == StoryStatus.DRAFT


async def test_co8_a_quote_of_the_coachs_parts_is_rejected(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue
) -> None:
    """CO-8: the candidate said "checkout simply could not break"; the coach's part and the
    version's quote say "checkout could not break". That is not the candidate's words, so it is
    rejected even though the story's part holds the quote (the first coach eval's failure)."""
    queue.run_jobs = False
    await sign_in(client)
    user = await _user(sessionmaker, "dev@example.com")
    said = [
        CONTEXT,
        "Black Friday was a month out and checkout simply could not break.",
        ACTION,
        REFLECTION,
    ]
    story = await _coach_story(sessionmaker, user, said)
    async with sessionmaker() as db:
        row = await db.get(Story, story.id)
        assert row is not None
        row.stakes = STAKES  # the coach's part holds the version's quote word for word
        await db.commit()
    await client.post(f"/stories/{story.id}/takes", json={"text": RESULT_TAKE})
    resp = await client.post(f"/stories/{story.id}/versions")
    assert resp.status_code == 502
    assert "own words" in resp.json()["detail"]


async def test_co8_manual_story_parts_are_the_candidates_words(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue
) -> None:
    """CO-8: a story the candidate typed, with no coach session, may be quoted from its parts.
    A coach story's parts never count."""
    queue.run_jobs = False
    await sign_in(client)
    user = await _user(sessionmaker, "dev@example.com")
    manual = await _story(sessionmaker, user, source=StorySource.MANUAL)
    await client.post(f"/stories/{manual.id}/takes", json={"text": RESULT_TAKE})
    assert (await client.post(f"/stories/{manual.id}/versions")).status_code == 200

    coach = await _story(sessionmaker, user)
    await client.post(f"/stories/{coach.id}/takes", json={"text": RESULT_TAKE})
    assert (await client.post(f"/stories/{coach.id}/versions")).status_code == 502


async def test_co8_own_words_skip_parts_once_the_coach_touched_the_story(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """CO-8: a manual story worked on in a coach session may hold the coach's wording in its
    parts, so only the candidate's turns and takes count."""
    await sign_in(client)
    user = await _user(sessionmaker, "dev@example.com")
    story = await _coach_story(sessionmaker, user, ["I was the backend lead at Acme."])
    async with sessionmaker() as db:
        row = await db.get(Story, story.id)
        assert row is not None
        row.source = StorySource.MANUAL
        await db.commit()
        assert await own_words(db, row) == ["I was the backend lead at Acme."]


async def test_co8_debrief_story_quotes_the_interview_answer(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """CO-8, ST-2: a story saved from a debrief answer may quote the candidate's turns on that
    question; not the interviewer, not other questions, not the saved parts."""
    await sign_in(client)
    user = await _user(sessionmaker, "dev@example.com")
    async with sessionmaker() as db:
        target = JobTarget(org_id=user.org_id, user_id=user.id)
        db.add(target)
        await db.flush()
        session = InterviewSession(
            org_id=user.org_id,
            job_target_id=target.id,
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.REALISTIC,
            mode=Mode.REALISTIC,
            duration_min=30,
            status=SessionStatus.COMPLETED,
            started_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()
        rows = [
            (Speaker.INTERVIEWER, "q2", "Tell me about a launch."),
            (Speaker.CANDIDATE, "q2", CONTEXT),
            (Speaker.CANDIDATE, "q3", "Something about another project."),
            (Speaker.CANDIDATE, "q2", STAKES),
        ]
        for i, (speaker, ref, text) in enumerate(rows):
            db.add(
                TurnRow(
                    org_id=user.org_id,
                    session_id=session.id,
                    seq=i + 1,
                    speaker=speaker,
                    phase=Phase.CORE,
                    text=text,
                    start_ms=i * 1000,
                    end_ms=i * 1000 + 500,
                    question_ref=ref,
                )
            )
        story = Story(
            org_id=user.org_id,
            user_id=user.id,
            title="the checkout migration",
            context="A summary of the context.",
            skills=["ownership"],
            notes_json=[],
            source=StorySource.DEBRIEF_ANSWER,
            source_session_id=session.id,
            source_question_ref="q2",
        )
        db.add(story)
        await db.commit()
        assert await own_words(db, story) == [CONTEXT, STAKES]


async def test_co8_a_version_with_an_unsupported_sentence_is_rejected(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: InlineQueue,
    fake_fixtures: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CO-8: a sentence the candidate never said (all quotes valid) is rejected, after one
    retry."""
    queue.run_jobs = False
    path = fake_fixtures / "coach" / "StoryVersions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["full"]["text"] += " I also mentored the whole support team through the launch."
    path.write_text(json.dumps(data), encoding="utf-8")
    backend = FakeBackend(fake_fixtures)
    gateway = ModelGateway(fake_models_config(), fake=backend)
    monkeypatch.setattr(takes_router, "get_gateway", lambda: gateway)

    await sign_in(client)
    user = await _user(sessionmaker, "dev@example.com")
    story = await _coach_story(sessionmaker, user, [CONTEXT, STAKES, ACTION, REFLECTION])
    await client.post(f"/stories/{story.id}/takes", json={"text": RESULT_TAKE})
    resp = await client.post(f"/stories/{story.id}/versions")
    assert resp.status_code == 502
    assert "own words" in resp.json()["detail"]


async def test_co8_versions_need_the_candidates_words(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """CO-8: a coach story with parts but none of the candidate's words has nothing to quote."""
    await sign_in(client)
    story = await _story(sessionmaker, await _user(sessionmaker, "dev@example.com"))
    assert (await client.post(f"/stories/{story.id}/versions")).status_code == 422


def test_co8_the_writer_reads_the_parts_as_an_outline_only() -> None:
    """CO-8: the prompt keeps the outline apart from the words the versions may quote."""
    story = Story(title="t", skills=[], notes_json=[], source=StorySource.COACH, **COACH_PARTS)
    [system, user] = versions.version_messages(story, [CONTEXT, RESULT_TAKE])
    assert system.prompt_ref == "coach/story_versions.v2"
    outline, said = user.content.split("What the candidate said", 1)
    assert COACH_PARTS["stakes"] in outline and COACH_PARTS["stakes"] not in said
    assert CONTEXT in said and RESULT_TAKE in said


def test_co8_recent_words_keep_the_newest_within_budget() -> None:
    assert versions.recent_words(["a" * 10, "b" * 10, "c" * 10], budget=25) == ["b" * 10, "c" * 10]
    assert versions.recent_words(["x" * 50], budget=10) == ["x" * 50]  # always the newest one


# --- CO-8: the checks in code ----------------------------------------------------------------

SAID = versions.said_text([CONTEXT, STAKES, ACTION, REFLECTION, RESULT_TAKE])
QUOTES = ["I wrote the rollback plan", "we moved traffic in five percent steps"]


def test_co8_check_accepts_the_candidates_words() -> None:
    v = StoryVersion(text="I wrote the rollback plan and moved traffic in 5% steps.", quotes=QUOTES)
    assert versions.check_version("v", v, SAID) == []


def test_co8_check_rejects_an_unsupported_sentence() -> None:
    """CO-8: a version with an unsupported sentence is rejected."""
    v = StoryVersion(
        text="I wrote the rollback plan. I also mentored the whole support team.", quotes=QUOTES
    )
    [problem] = versions.check_version("v", v, SAID)
    assert "sentence not in the candidate's words" in problem
    assert "mentored" in problem


def test_co8_check_rejects_a_made_up_quote_and_number() -> None:
    made_up = StoryVersion(text="I wrote the rollback plan.", quotes=["I wrote the whole plan"])
    assert any("quote not found" in p for p in versions.check_version("v", made_up, SAID))
    number = StoryVersion(text="I wrote the rollback plan in 3 days.", quotes=QUOTES)
    assert any(
        "number not in the quotes: 3" in p for p in versions.check_version("v", number, SAID)
    )
