"""Story fit (ST-5), the story each answer used (ST-6) and the Proven rule (ST-7)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Turn as TurnRow
from strong_core.gateway import FakeBackend, Message, ModelGateway, Role, TokenUsage
from strong_core.gateway.registry import CapabilityTier, ModelsConfig, fake_models_config
from strong_core.schemas import (
    Competency,
    Mode,
    QuestionScore,
    SessionStatus,
    Story,
    StoryFit,
    StoryFitStrength,
    StorySource,
    StoryStatus,
)
from strong_worker.gap import jobs as gap_jobs
from strong_worker.gap.story_fit import (
    NO_STORIES_REASON,
    StoryFitRecord,
    compute_story_fit,
    run_story_fit,
    story_fit_key,
)
from strong_worker.main import WorkerSettings
from strong_worker.scoring import jobs
from strong_worker.scoring.stories import (
    StoryMatcher,
    parse_reply,
    proves_story,
    story_from_row,
)
from strong_worker.scoring.testing import (
    RATIONALE,
    ScriptedBackend,
    first_answers,
    load_scripted,
    scorecard_reply,
)

C = Competency
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _config(tier: CapabilityTier | None, *roles: Role) -> ModelsConfig:
    config = fake_models_config()
    if tier is None:
        return config
    models = dict(config.models)
    for role in roles:
        alias = config.roles[role]
        models[alias] = models[alias].model_copy(update={"tier": tier})
    return config.model_copy(update={"models": models})


def _gateway(backend: FakeBackend, tier: CapabilityTier | None = None) -> ModelGateway:
    return ModelGateway(_config(tier, Role.PLANNER, Role.SCORER), fake=backend)


def _story(title: str, skills: Sequence[str] = (), **parts: str) -> Story:
    return Story.model_validate(
        {
            "id": str(uuid.uuid4()),
            "title": title,
            "skills": list(skills),
            "source": "manual",
            "created_at": NOW,
            "updated_at": NOW,
            **parts,
        }
    )


def _fit_item(competency: str, story: Story | None, strength: str) -> dict[str, Any]:
    return {
        "competency": competency,
        "story_id": str(story.id) if story else None,
        "strength": strength,
        "reason": f"Reason for {competency}.",
    }


# --- ST-5: story fit -------------------------------------------------------------------------


async def test_st5_story_fit_has_one_item_per_tested_skill_with_the_users_stories() -> None:
    """ST-5: one item per tested skill, in order; invented ids, other skills and repeats from
    the model are dropped, and a skill the reply leaves out is missing."""
    checkout = _story("Checkout migration", ["ownership"], action="I wrote the rollback plan.")
    roadmap = _story("Roadmap fight", ["conflict_handling"])
    reply = {
        "items": [
            _fit_item("ownership", checkout, "strong"),
            _fit_item("impact", None, "missing"),
            _fit_item("conflict_handling", _story("Invented"), "thin"),
            _fit_item("communication", roadmap, "thin"),
        ]
    }
    backend = ScriptedBackend([reply])
    wanted = [C.OWNERSHIP, C.CONFLICT_HANDLING, C.LEARNING_FROM_FAILURE]
    result = await compute_story_fit(
        _gateway(backend), [checkout, roadmap], wanted, "Senior engineer at Example Corp"
    )

    assert [i.competency for i in result.fit.items] == wanted
    items = {i.competency: i for i in result.fit.items}
    assert items[C.OWNERSHIP].story_id == checkout.id
    assert items[C.OWNERSHIP].strength == StoryFitStrength.STRONG
    assert items[C.CONFLICT_HANDLING].strength == StoryFitStrength.MISSING  # invented id
    assert items[C.LEARNING_FROM_FAILURE].strength == StoryFitStrength.MISSING
    assert result.model_calls == 1
    assert result.prompt_version == "planner/story_fit.v1"
    ((messages, output_type),) = backend.calls
    assert output_type is StoryFit
    prompt = messages[1].content
    assert str(checkout.id) in prompt and "rollback plan" in prompt
    assert "- ownership" in prompt and "- impact" not in prompt


async def test_st5_no_stories_means_every_skill_is_missing_without_a_model_call() -> None:
    """ST-5: with an empty library every skill is missing, and no model is called."""
    backend = ScriptedBackend([])
    result = await compute_story_fit(_gateway(backend), [], [C.OWNERSHIP, C.IMPACT], "")
    assert {i.strength for i in result.fit.items} == {StoryFitStrength.MISSING}
    assert result.fit.items[0].reason == NO_STORIES_REASON
    assert result.model_calls == 0 and backend.calls == []


async def test_st5_pl5_small_models_get_one_skill_at_a_time() -> None:
    """ST-5, PL-5: a small-tier planner gets one call per skill, with the small prompt."""
    story = _story("Checkout migration", ["ownership"])
    backend = ScriptedBackend([{"items": [_fit_item("ownership", story, "thin")]}])
    result = await compute_story_fit(
        _gateway(backend, CapabilityTier.SMALL), [story], [C.OWNERSHIP, C.IMPACT], "Job"
    )
    assert result.model_calls == 2
    assert result.prompt_version == "planner/story_fit.small.v1"
    assert [m[0].prompt_ref for m, _ in backend.calls] == ["planner/story_fit.small.v1"] * 2
    assert "Skill: - ownership" in backend.calls[0][0][1].content
    items = {i.competency: i for i in result.fit.items}
    assert items[C.OWNERSHIP].story_id == story.id
    assert items[C.IMPACT].strength == StoryFitStrength.MISSING  # the reply named another skill


async def test_st5_default_fake_fixture_gives_a_valid_table() -> None:
    """ST-5: the default fake StoryFit fixture runs through the engine (its ids are not the
    user's, so every skill comes back missing)."""
    story = _story("Checkout migration", ["ownership"])
    result = await compute_story_fit(_gateway(FakeBackend()), [story], [C.OWNERSHIP], "Job")
    assert [i.strength for i in result.fit.items] == [StoryFitStrength.MISSING]


class _Cache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        self.ttl[key] = ex


async def _add_story(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    skills: Sequence[str] = (),
    **parts: str,
) -> uuid.UUID:
    async with maker() as db:
        row = StoryRow(
            org_id=org_id,
            user_id=user_id,
            title=title,
            skills=list(skills),
            source=StorySource.MANUAL,
            **parts,
        )
        db.add(row)
        await db.commit()
        return row.id


def test_st5_story_fit_job_is_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert "run_story_fit" in names


async def test_st5_pl6_job_caches_the_table_with_provenance_and_reruns_when_stories_change(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ST-5, PL-6: the job caches the table with profile, model and prompt; the same inputs
    reuse it without a call; a changed story runs the planner again."""
    org_id, user_id = account
    story_id = await _add_story(sessionmaker, org_id, user_id, "Checkout", ["ownership"])
    async with sessionmaker() as db:
        target = JobTarget(org_id=org_id, user_id=user_id, name="Backend role")
        db.add(target)
        await db.commit()
    reply = {
        "items": [
            {
                "competency": "ownership",
                "story_id": str(story_id),
                "strength": "strong",
                "reason": "The checkout story shows you owning the rollout.",
            }
        ]
    }
    backend = ScriptedBackend([reply])
    cache = _Cache()
    ctx = {
        gap_jobs.CTX_KEY: gap_jobs.GapContext(sessionmaker=sessionmaker, gateway=_gateway(backend)),
        "redis": cache,
    }
    args = (str(org_id), str(target.id), ["ownership", "impact"])

    first = await run_story_fit(ctx, *args)
    assert first["outcome"] == "computed" and first["model_calls"] == 1
    record = StoryFitRecord.model_validate_json(cache.data[story_fit_key(org_id, target.id)])
    assert record.fit.items[0].story_id == story_id
    assert record.fit.items[1].strength == StoryFitStrength.MISSING
    assert record.model_profile == "fake"
    assert record.model_id == "fake-planner"
    assert record.prompt_version == "planner/story_fit.v1"
    assert cache.ttl[story_fit_key(org_id, target.id)]

    again = await run_story_fit(ctx, *args)
    assert again == {"outcome": "cached", "input_hash": first["input_hash"], "model_calls": 0}
    assert len(backend.calls) == 1

    async with sessionmaker() as db:
        row = await db.get(StoryRow, story_id)
        assert row is not None
        row.result = "Checkout errors fell by half."
        await db.commit()
    changed = await run_story_fit(ctx, *args)
    assert changed["outcome"] == "computed" and changed["input_hash"] != first["input_hash"]
    assert len(backend.calls) == 2

    other_org = await run_story_fit(ctx, str(uuid.uuid4()), str(target.id), ["ownership"])
    assert other_org["outcome"] == "failed"


# --- ST-6: the story each answer used --------------------------------------------------------


def test_st6_parse_reply() -> None:
    """ST-6: the two-line reply; NONE and odd spacing are handled."""
    assert parse_reply("STORY: S2\nFIX: Say the result in numbers.") == (
        "S2",
        "Say the result in numbers.",
    )
    assert parse_reply("story :  none\nfix: NONE") == (None, None)
    assert parse_reply("I think it is S1.") == (None, None)
    assert parse_reply('Sure!\nSTORY: YES\nFIX: "Name the trade-off."') == (
        "YES",
        "Name the trade-off.",
    )


def _question(
    ref: str = "q1",
    competencies: Sequence[str] = ("ownership",),
    score: int = 3,
    story_id: uuid.UUID | None = None,
) -> QuestionScore:
    return QuestionScore.model_validate(
        {
            "question_ref": ref,
            "question_text": "Tell me about a time you owned a hard project.",
            "scores": [
                {"competency": c, "score": score, "justification": "x", "quotes": ["I owned"]}
                for c in competencies
            ],
            "misses": ["The result had no numbers."],
            "story_id": str(story_id) if story_id else None,
        }
    )


async def test_st6_matcher_picks_the_story_the_answer_told() -> None:
    """ST-6: the matcher shows short labels, maps the reply back to the story id, and keeps
    the fix; an id that was not offered is no match."""
    checkout = _story("Checkout migration", ["ownership"], action="I wrote the rollback plan.")
    other = _story("Hiring loop", ["collaboration"])
    backend = ScriptedBackend(
        ["STORY: S1\nFIX: Say what the migration saved.", "STORY: S9\nFIX: x"]
    )
    matcher = StoryMatcher(_gateway(backend))
    answers = {"q1": "I led the checkout migration.", "q2": "We hired three people."}
    result = await matcher.match(
        [_question("q1"), _question("q2", ["collaboration"])], answers, [other, checkout]
    )
    assert [(m.question_ref, m.story_id, m.fix) for m in result.matches] == [
        ("q1", checkout.id, "Say what the migration saved.")
    ]
    assert result.model_calls == 2
    assert result.prompt_ref == "scorer/story_match.v1"
    first_prompt = backend.calls[0][0][1].content
    assert 'S1: "Checkout migration"' in first_prompt  # ranked by skill overlap
    assert "The result had no numbers." in first_prompt


async def test_st6_no_fix_from_the_model_uses_the_answers_first_miss() -> None:
    """ST-6: a match without a fix still sends the answer's main miss to the story."""
    story = _story("Checkout migration", ["ownership"])
    backend = ScriptedBackend(["STORY: S1\nFIX: NONE"])
    result = await StoryMatcher(_gateway(backend)).match(
        [_question()], {"q1": "I led the checkout migration."}, [story]
    )
    assert result.matches[0].fix == "The result had no numbers."


async def test_st6_pl5_small_models_check_one_story_at_a_time() -> None:
    """ST-6, PL-5: a small-tier scorer is asked YES or NO about one story per call, best
    ranked first, and stops at the first YES."""
    a = _story("Checkout migration", ["ownership"])
    b = _story("Billing outage", ["ownership", "learning_from_failure"])
    c = _story("Hiring loop", ["collaboration"])
    backend = ScriptedBackend(["STORY: NO\nFIX: NONE", "STORY: YES\nFIX: Name the root cause."])
    result = await StoryMatcher(_gateway(backend, CapabilityTier.SMALL)).match(
        [_question("q3", ["learning_from_failure", "ownership"])],
        {"q3": "The billing outage was my fault."},
        [a, b, c],
    )
    assert len(backend.calls) == 2
    assert {m[0].prompt_ref for m, _ in backend.calls} == {"scorer/story_match.small.v1"}
    assert '"Billing outage"' in backend.calls[0][0][1].content
    assert '"Checkout migration"' in backend.calls[1][0][1].content
    assert result.matches[0].story_id == a.id
    assert result.matches[0].fix == "Name the root cause."


# --- the step in the scoring job (ST-6, ST-7) ------------------------------------------------


async def _make_session(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    mode: Mode = Mode.REALISTIC,
    model_profile: str | None = "hosted",
) -> InterviewSession:
    brief, turns = load_scripted("beh-01")
    brief = brief.model_copy(update={"session": brief.session.model_copy(update={"mode": mode})})
    async with maker() as db:
        target = JobTarget(org_id=org_id, user_id=user_id)
        db.add(target)
        await db.flush()
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target.id,
            type=brief.session.interview_type,
            difficulty=brief.session.difficulty,
            mode=mode,
            duration_min=30,
            profile_version=brief.profile_version,
            brief_json=brief.model_dump(mode="json"),
            model_profile=model_profile,
            status=SessionStatus.SCORING,
            started_at=datetime.now(UTC) - timedelta(minutes=30),
            ended_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()
        db.add_all(TurnRow(org_id=org_id, session_id=session.id, **t.model_dump()) for t in turns)
        await db.commit()
        return session


def _ctx(maker: async_sessionmaker[AsyncSession], backend: FakeBackend) -> dict[str, Any]:
    return {jobs.CTX_KEY: jobs.ScoringContext(sessionmaker=maker, gateway=_gateway(backend))}


async def _score(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    backend: FakeBackend,
    **session: Any,
) -> tuple[dict[str, Any], InterviewSession]:
    row = await _make_session(maker, org_id, user_id, **session)
    result = await jobs.score_session(_ctx(maker, backend), str(row.id), str(org_id))
    return result, row


async def _card(maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID) -> ScorecardRow:
    async with maker() as db:
        card = await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session_id))
        assert card is not None
        return card


async def _stored_story(maker: async_sessionmaker[AsyncSession], story_id: uuid.UUID) -> Story:
    async with maker() as db:
        row = await db.get(StoryRow, story_id)
        assert row is not None
        return story_from_row(row)


def _scored(score: int = 3) -> ScriptedBackend:
    brief, turns = load_scripted("beh-01")
    reply = scorecard_reply(brief, turns, score)
    return ScriptedBackend([reply, RATIONALE, "STORY: S1\nFIX: Say what the migration saved."])


async def test_st6_st7_scoring_writes_the_story_used_sends_the_fix_and_proves_the_story(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ST-6: after scoring, each answer names the story it used and its fix, and the fix is a
    note on the story. ST-7: a Realistic answer that scores 3 or more makes it Proven."""
    org_id, user_id = account
    story_id = await _add_story(sessionmaker, org_id, user_id, "Checkout migration", ["ownership"])
    result, session = await _score(sessionmaker, org_id, user_id, _scored(3))

    assert result["outcome"] == "scored"
    assert result["stories_matched"] == len(first_answers(load_scripted("beh-01")[1]))
    assert result["stories_proven"] == 1
    card = await _card(sessionmaker, session.id)
    per_question = [QuestionScore.model_validate(q) for q in card.per_question_json]
    assert {q.story_id for q in per_question} == {story_id}
    assert {q.story_fix for q in per_question} == {"Say what the migration saved."}
    story = await _stored_story(sessionmaker, story_id)
    assert story.status == StoryStatus.PROVEN
    assert len(story.notes) == len(per_question)
    assert story.notes[0].session_id == session.id
    assert story.notes[0].question_ref == per_question[0].question_ref


async def test_st7_coach_mode_never_proves_a_story(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ST-7: Coach mode never proves a story, even with top scores. ST-6 still records the
    story and the fix."""
    org_id, user_id = account
    story_id = await _add_story(sessionmaker, org_id, user_id, "Checkout migration", ["ownership"])
    result, _ = await _score(sessionmaker, org_id, user_id, _scored(4), mode=Mode.COACH)

    assert result["stories_matched"] > 0 and result["stories_proven"] == 0
    story = await _stored_story(sessionmaker, story_id)
    assert story.status == StoryStatus.DRAFT
    assert story.notes


@pytest.mark.parametrize("profile", ["fake", "tiny", "local", None])
async def test_st7_pl6_development_profiles_never_prove_a_story(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    profile: str | None,
) -> None:
    """ST-7, PL-6: sessions on a development model profile are not real data."""
    org_id, user_id = account
    story_id = await _add_story(sessionmaker, org_id, user_id, "Checkout migration", ["ownership"])
    await _score(sessionmaker, org_id, user_id, _scored(4), model_profile=profile)
    assert (await _stored_story(sessionmaker, story_id)).status == StoryStatus.DRAFT


async def test_st7_a_score_under_3_does_not_prove_a_story(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ST-7: an answer that used the story but scored 2 leaves it a Draft."""
    org_id, user_id = account
    story_id = await _add_story(sessionmaker, org_id, user_id, "Checkout migration", ["ownership"])
    await _score(sessionmaker, org_id, user_id, _scored(2))
    assert (await _stored_story(sessionmaker, story_id)).status == StoryStatus.DRAFT


@pytest.mark.parametrize(
    ("mode", "profile", "score", "used", "expected"),
    [
        (Mode.REALISTIC, "hosted", 3, True, True),
        (Mode.REALISTIC, "claude", 4, True, True),
        (Mode.REALISTIC, "hosted", 2, True, False),
        (Mode.REALISTIC, "hosted", 4, False, False),
        (Mode.COACH, "hosted", 4, True, False),
        (Mode.REALISTIC, "tiny", 4, True, False),
        (Mode.REALISTIC, "local", 4, True, False),
    ],
)
def test_st7_proven_rule(mode: Mode, profile: str, score: int, used: bool, expected: bool) -> None:
    """ST-7: the rule is code: Realistic, a real profile, a story used, a score of 3 or more."""
    question = _question(score=score, story_id=uuid.uuid4() if used else None)
    assert proves_story(mode, profile, question) is expected


def test_st7_the_answer_score_is_the_mean_of_its_competencies() -> None:
    """ST-7: 4 and 2 average to 3, which proves; 3 and 2 average to 2.5, which does not."""
    q = _question(competencies=("ownership", "impact"), story_id=uuid.uuid4())
    scores = q.scores
    high = q.model_copy(
        update={
            "scores": [
                scores[0].model_copy(update={"score": 4}),
                scores[1].model_copy(update={"score": 2}),
            ]
        }
    )
    low = q.model_copy(
        update={
            "scores": [
                scores[0].model_copy(update={"score": 3}),
                scores[1].model_copy(update={"score": 2}),
            ]
        }
    )
    assert proves_story(Mode.REALISTIC, "hosted", high)
    assert not proves_story(Mode.REALISTIC, "hosted", low)


class _StoryMatchFails(ScriptedBackend):
    """Scores normally, and fails every story_match call."""

    def complete(
        self, role: Role, messages: Sequence[Message], output_type: type[BaseModel] | None
    ) -> tuple[object, TokenUsage]:
        if (messages[0].prompt_ref or "").startswith("scorer/story_match"):
            raise RuntimeError("simulated story match failure")
        return super().complete(role, messages, output_type)


async def test_st6_the_scorecard_is_unchanged_when_story_matching_fails(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-6: a failing story step never blocks or changes scoring: the session completes and
    the scorecard equals the one scored with no stories at all."""
    org_id, user_id = account
    brief, turns = load_scripted("beh-01")
    reply = scorecard_reply(brief, turns, 3)
    _, baseline = await _score(sessionmaker, org_id, user_id, ScriptedBackend([reply, RATIONALE]))
    story_id = await _add_story(sessionmaker, org_id, user_id, "Checkout migration", ["ownership"])

    result, failing = await _score(
        sessionmaker, org_id, user_id, _StoryMatchFails([reply, RATIONALE])
    )
    assert result["outcome"] == "scored" and result["stories_matched"] == 0
    assert result["story_errors"] > 0
    assert (await _card(sessionmaker, failing.id)).per_question_json == (
        await _card(sessionmaker, baseline.id)
    ).per_question_json
    story = await _stored_story(sessionmaker, story_id)
    assert story.status == StoryStatus.DRAFT and story.notes == []

    # A crash in the step itself (not one model call) is caught too.
    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database went away")

    monkeypatch.setattr("strong_worker.scoring.stories.apply_story_step", boom)
    result, crashed = await _score(
        sessionmaker, org_id, user_id, ScriptedBackend([reply, RATIONALE])
    )
    assert result["outcome"] == "scored" and result["story_errors"] == 1
    async with sessionmaker() as db:
        row = await db.get(InterviewSession, crashed.id)
        assert row is not None and row.status == SessionStatus.COMPLETED
    assert (await _card(sessionmaker, crashed.id)).per_question_json == (
        await _card(sessionmaker, baseline.id)
    ).per_question_json


async def test_st6_other_users_stories_are_never_matched(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ST-6: only the session owner's stories are offered to the matcher."""
    org_id, user_id = account
    from strong_core.db.models import User
    from strong_core.schemas import AuthProvider

    async with sessionmaker() as db:
        other = User(org_id=org_id, email="other@example.com", auth_provider=AuthProvider.DEV)
        db.add(other)
        await db.commit()
    await _add_story(sessionmaker, org_id, other.id, "Someone else's story", ["ownership"])
    backend = _scored(3)
    result, _ = await _score(sessionmaker, org_id, user_id, backend)
    assert result["stories_matched"] == 0 and result["story_calls"] == 0
