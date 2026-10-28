"""Takes: one telling of a story, scored by the session scorer on the story's skills (CO-7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession, JobTarget, Story, Take, User
from strong_core.db.models import ProgressSnapshot as SnapshotRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import (
    Competency,
    Difficulty,
    InterviewType,
    Level,
    Mode,
    SessionChannel,
    SessionStatus,
    StorySource,
    StoryStatus,
)
from strong_worker.main import WorkerSettings
from strong_worker.scoring import jobs, takes
from strong_worker.scoring.scorer import ScoringError
from strong_worker.scoring.testing import ScriptedBackend, scorecard_reply

C = Competency
TAKE = (
    "At Acme I owned the checkout migration. I wrote the rollback plan myself and moved traffic "
    "in five percent steps, and we finished a week early with no failed payments."
)


def _ctx(maker: async_sessionmaker[AsyncSession], backend: ScriptedBackend) -> dict[str, Any]:
    gateway = ModelGateway(fake_models_config(), fake=backend)
    return {jobs.CTX_KEY: jobs.ScoringContext(sessionmaker=maker, gateway=gateway)}


def _reply(skills: list[Competency], level: Level, score: int = 3, **kw: Any) -> dict[str, Any]:
    brief = takes.take_brief("the checkout migration", skills, level)
    return scorecard_reply(brief, takes.take_turns(brief.questions[0].text, TAKE), score, **kw)


async def _story(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    skills: list[Competency],
    *,
    status: StoryStatus = StoryStatus.DRAFT,
    source_session_id: uuid.UUID | None = None,
) -> Story:
    async with maker() as db:
        story = Story(
            org_id=org_id,
            user_id=user_id,
            title="the checkout migration",
            skills=[s.value for s in skills],
            notes_json=[],
            status=status,
            source=StorySource.COACH,
            source_session_id=source_session_id,
        )
        db.add(story)
        await db.commit()
        return story


async def _take(maker: async_sessionmaker[AsyncSession], story: Story, text: str = TAKE) -> Take:
    async with maker() as db:
        take = Take(
            org_id=story.org_id,
            user_id=story.user_id,
            story_id=story.id,
            channel=SessionChannel.TEXT,
            text=text,
        )
        db.add(take)
        await db.commit()
        return take


async def _session_with_level(
    maker: async_sessionmaker[AsyncSession], org_id: uuid.UUID, user_id: uuid.UUID, level: Level
) -> uuid.UUID:
    async with maker() as db:
        target = JobTarget(org_id=org_id, user_id=user_id, level=level)
        db.add(target)
        await db.flush()
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target.id,
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.REALISTIC,
            mode=Mode.REALISTIC,
            duration_min=30,
            status=SessionStatus.COMPLETED,
            started_at=datetime.now(UTC),
        )
        db.add(session)
        await db.commit()
        return session.id


def test_co7_score_take_is_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert "score_take" in names


def test_co7_take_brief_scores_only_the_story_skills_its_type_can_score() -> None:
    """CO-7: one asked question carrying the story's skills; skills of another type are left out."""
    brief = takes.take_brief("x", [C.OWNERSHIP, C.TECHNICAL_DEPTH, C.IMPACT], Level.SENIOR)
    assert brief.session.interview_type == InterviewType.BEHAVIORAL
    assert brief.session.level == Level.SENIOR
    assert brief.generic_mode
    assert brief.questions[0].id == takes.TAKE_REF
    assert brief.questions[0].competencies == [C.OWNERSHIP, C.IMPACT]
    assert takes.take_interview_type([C.TECHNICAL_DEPTH]) == InterviewType.TECHNICAL_QA
    with pytest.raises(ScoringError):
        takes.take_brief("x", [], Level.MID)


async def test_co7_take_is_scored_per_skill_and_never_changes_status_or_readiness(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """CO-7: per-skill 1 to 4 scores with quotes and provenance. The story stays Draft and no
    progress snapshot is written (takes never count toward readiness)."""
    org_id, user_id = account
    story = await _story(sessionmaker, org_id, user_id, [C.OWNERSHIP, C.IMPACT])
    take = await _take(sessionmaker, story)
    backend = ScriptedBackend([_reply([C.OWNERSHIP, C.IMPACT], Level.MID, 3)])

    result = await takes.score_take(_ctx(sessionmaker, backend), str(take.id), str(org_id))

    assert result["outcome"] == "scored"
    assert result["level"] == "mid"
    assert result["scores"] == {"ownership": 3, "impact": 3}
    # one scorer call: the rubric only, the rationale is built in code
    assert len(backend.calls) == 1
    async with sessionmaker() as db:
        row = await db.get(Take, take.id)
        assert row is not None and row.skill_scores_json is not None
        assert [s["competency"] for s in row.skill_scores_json] == ["ownership", "impact"]
        assert all(1 <= s["score"] <= 4 and s["quotes"] for s in row.skill_scores_json)
        assert all(s["quotes"][0] in TAKE for s in row.skill_scores_json)
        assert row.model_profile == "fake"
        assert row.model_id
        assert row.prompt_version and row.prompt_version.startswith("scorer/rubric")
        stored = await db.get(Story, story.id)
        assert stored is not None and stored.status == StoryStatus.DRAFT
        snaps = await db.scalar(select(func.count()).select_from(SnapshotRow))
        assert snaps == 0

    again = await takes.score_take(_ctx(sessionmaker, backend), str(take.id), str(org_id))
    assert again["outcome"] == "exists"


async def test_co7_take_of_a_proven_story_scored_low_stays_proven(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """CO-7: only ST-7 changes the status; a weak take does not demote a Proven story."""
    org_id, user_id = account
    story = await _story(sessionmaker, org_id, user_id, [C.OWNERSHIP], status=StoryStatus.PROVEN)
    take = await _take(sessionmaker, story)
    backend = ScriptedBackend([_reply([C.OWNERSHIP], Level.MID, 1)])
    result = await takes.score_take(_ctx(sessionmaker, backend), str(take.id), str(org_id))
    assert result["scores"] == {"ownership": 1}
    async with sessionmaker() as db:
        stored = await db.get(Story, story.id)
        assert stored is not None and stored.status == StoryStatus.PROVEN


async def test_co7_level_is_the_linked_job_level_else_the_target_level(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """CO-7: the story's linked job level wins; else the user's target level; else mid."""
    org_id, user_id = account
    plain = await _story(sessionmaker, org_id, user_id, [C.OWNERSHIP])
    async with sessionmaker() as db:
        assert await takes.take_level(db, plain) == Level.MID
        user = await db.get(User, user_id)
        assert user is not None
        user.target_level = Level.NEW_GRAD
        await db.commit()
        assert await takes.take_level(db, plain) == Level.NEW_GRAD

    sid = await _session_with_level(sessionmaker, org_id, user_id, Level.STAFF_PRINCIPAL)
    linked = await _story(sessionmaker, org_id, user_id, [C.OWNERSHIP], source_session_id=sid)
    take = await _take(sessionmaker, linked)
    backend = ScriptedBackend([_reply([C.OWNERSHIP], Level.STAFF_PRINCIPAL)])
    result = await takes.score_take(_ctx(sessionmaker, backend), str(take.id), str(org_id))
    assert result["level"] == "staff_principal"
    user_message = backend.calls[0][0][1].content
    assert "Candidate level: staff_principal" in user_message


async def test_co7_take_with_no_valid_quote_is_not_scored(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """CO-7, FB-2: quotes are checked by the scorer; a take with none valid stays unscored."""
    org_id, user_id = account
    story = await _story(sessionmaker, org_id, user_id, [C.OWNERSHIP])
    take = await _take(sessionmaker, story)
    bad = _reply([C.OWNERSHIP], Level.MID, quote="words the candidate never said")
    result = await takes.score_take(
        _ctx(sessionmaker, ScriptedBackend([bad])), str(take.id), str(org_id)
    )
    assert result["outcome"] == "failed"
    async with sessionmaker() as db:
        row = await db.get(Take, take.id)
        assert row is not None and row.skill_scores_json is None
