"""Suggestions from Strova, the worker side (U08): tune a story (SG-2), new story (SG-3), missing
skill (SG-4), tailor for a role (SG-5), improve a resume line (SG-6), the no-new-facts check
(SG-7), dismissed ones never return (SG-8), and the story review (ST-11)."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import find_repo_root
from strong_core.db.models import JobTarget
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.gateway import FakeBackend, Message, ModelGateway, Role, TokenUsage
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import (
    Competency,
    NewStoryPayload,
    StoryPartEdit,
    StoryReview,
    Suggestion,
    SuggestionKind,
    SuggestionStatus,
)
from strong_worker.gap import jobs as gap_jobs
from strong_worker.gap.story_fit import run_story_fit
from strong_worker.main import WorkerSettings
from strong_worker.scoring import jobs
from strong_worker.scoring.testing import (
    RATIONALE,
    ScriptedBackend,
    first_answers,
    load_scripted,
    scorecard_reply,
)
from strong_worker.suggestions import facts
from strong_worker.suggestions import jobs as suggestion_jobs
from strong_worker.suggestions.after_take import apply_suggestion_step, missing_skills
from strong_worker.suggestions.jobs import best_line
from strong_worker.suggestions.store import add_suggestion

from .test_stories import _add_story, _make_session

FIXTURES = find_repo_root() / "packages/core/src/strong_core/gateway/fixtures"
_INPUT = re.compile(r"<untrusted_input>\n(.*?)\n</untrusted_input>", re.DOTALL)


def _words(text: str, n: int = 8) -> str:
    return " ".join(text.split()[:n])


class CoachBackend(ScriptedBackend):
    """Scripted scorer replies; coach replies built from the answer in the prompt, so the
    quotes are the candidate's words. `add` appends words to every coach text (SG-7)."""

    def __init__(self, replies: Sequence[dict[str, Any] | str], add: str = "") -> None:
        super().__init__(replies)
        self.add = add
        self.coach_calls: list[type[BaseModel] | None] = []

    def complete(
        self, role: Role, messages: Sequence[Message], output_type: type[BaseModel] | None
    ) -> tuple[object, TokenUsage]:
        if role != Role.COACH:
            return super().complete(role, messages, output_type)
        self.coach_calls.append(output_type)
        quote = _words(_INPUT.findall(messages[1].content)[-1])  # the answer
        text = quote[0].upper() + quote[1:] + "." + self.add
        if output_type is StoryPartEdit:
            reply: dict[str, Any] = {
                "part": "result",
                "before": None,
                "after": text,
                "quotes": [quote],
            }
        elif output_type is NewStoryPayload:
            reply = {
                "kind": "new_story",
                "title": "Story from the answer",
                "context": text,
                "action": text,
                "result": text,
                "skills": ["ownership"],
                "quotes": [quote],
            }
        else:
            raise AssertionError(f"unexpected coach call {output_type}")
        return output_type.model_validate(reply), TokenUsage()


def _ctx(maker: async_sessionmaker[AsyncSession], backend: FakeBackend) -> dict[str, Any]:
    gateway = ModelGateway(fake_models_config(), fake=backend)
    return {jobs.CTX_KEY: jobs.ScoringContext(sessionmaker=maker, gateway=gateway)}


def _scored(
    score: int, *, story_reply: str = "STORY: NONE\nFIX: none", add: str = ""
) -> CoachBackend:
    brief, turns = load_scripted("beh-01")
    return CoachBackend([scorecard_reply(brief, turns, score), RATIONALE, story_reply], add=add)


async def _suggestions(
    maker: async_sessionmaker[AsyncSession], kind: SuggestionKind | None = None
) -> list[SuggestionRow]:
    async with maker() as db:
        query = select(SuggestionRow).order_by(SuggestionRow.created_at)
        if kind is not None:
            query = query.where(SuggestionRow.kind == kind)
        return list(await db.scalars(query))


def _contract(row: SuggestionRow) -> Suggestion:
    return Suggestion.model_validate(
        {
            "id": row.id,
            "kind": row.kind,
            "status": row.status,
            "payload": row.payload,
            "reason": row.reason,
            "source_session_id": row.source_session_id,
            "source_question_ref": row.source_question_ref,
            "job_target_id": row.job_target_id,
            "story_id": row.story_id,
            "resume_id": row.resume_id,
            "prompt_ref": row.prompt_ref,
            "created_at": row.created_at,
        }
    )


ANSWERS = first_answers(load_scripted("beh-01")[1])


# --- SG-7: no new facts ----------------------------------------------------------------------


def test_sg7_text_from_the_users_words_passes_and_added_facts_fail() -> None:
    """SG-7: quotes must be the user's words; numbers and sentences must come from them."""
    said = facts.said_text(["We were done a week before Black Friday and not one payment failed."])
    quote = "we were done a week before Black Friday and not one payment failed"
    good = "We finished a week before Black Friday and not one payment failed."
    assert facts.unbacked(good, [quote], said) == []
    assert facts.unbacked("Not one payment failed, out of 5 million.", [quote], said)
    assert facts.unbacked(good + " I also hired three engineers for the team.", [quote], said)
    assert facts.unbacked(good, ["we were done two weeks before Black Friday"], said)
    assert facts.unbacked("We were done in 2 weeks.", ["we were done a week"], said)


# --- SG-2, SG-3, SG-4: after a take is scored ------------------------------------------------


async def test_sg2_a_scored_answer_that_used_a_story_suggests_one_edit_from_its_words(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SG-2: each answer that used a story and has a fix gets a tune suggestion: one part, a
    before taken from the story, an after built only from the answer's words."""
    org_id, user_id = account
    story_id = await _add_story(
        sessionmaker, org_id, user_id, "Checkout migration", ["ownership"], result="It went well."
    )
    backend = _scored(3, story_reply="STORY: S1\nFIX: Say what the migration saved.")
    session = await _make_session(sessionmaker, org_id, user_id)
    result = await jobs.score_session(_ctx(sessionmaker, backend), str(session.id), str(org_id))

    assert result["suggestions_tune"] == len(ANSWERS)
    tunes = await _suggestions(sessionmaker, SuggestionKind.TUNE_STORY)
    assert {t.source_question_ref for t in tunes} == set(ANSWERS)
    for row in tunes:
        s = _contract(row)
        assert s.story_id == story_id and s.source_session_id == session.id
        assert s.job_target_id == session.job_target_id
        assert s.payload.kind == "tune_story"
        assert s.payload.edit.before == "It went well."
        answer = facts.said_text([ANSWERS[row.source_question_ref or ""]])
        assert facts.unbacked(s.payload.edit.after, s.payload.edit.quotes, answer) == []
        assert s.prompt_ref == "coach/suggest_tune.v1,coach/suggest_tune_input.v1"
        assert "Say what the migration saved." in s.reason


async def test_sg7_a_tune_that_adds_a_fact_is_asked_again_then_dropped(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SG-7: an edit with a fact the answer never gave is rejected twice and not stored."""
    org_id, user_id = account
    await _add_story(sessionmaker, org_id, user_id, "Checkout migration", ["ownership"])
    backend = _scored(
        3, story_reply="STORY: S1\nFIX: Add the result.", add=" It saved 2 million dollars."
    )
    session = await _make_session(sessionmaker, org_id, user_id)
    result = await jobs.score_session(_ctx(sessionmaker, backend), str(session.id), str(org_id))

    assert result["outcome"] == "scored"
    assert result["suggestions_tune"] == 0
    assert result["suggestions_rejected"] == len(ANSWERS)
    assert backend.coach_calls.count(StoryPartEdit) == 2 * len(ANSWERS)
    assert await _suggestions(sessionmaker, SuggestionKind.TUNE_STORY) == []


async def test_sg3_sg4_a_strong_answer_with_no_story_becomes_a_new_story_and_skills_are_missing(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SG-3: an answer that scores 4 and matched no story gets a new story suggestion, its
    parts from the answer. SG-4: with no stories, every tested skill is a missing skill."""
    org_id, user_id = account
    backend = _scored(4)
    session = await _make_session(sessionmaker, org_id, user_id)
    result = await jobs.score_session(_ctx(sessionmaker, backend), str(session.id), str(org_id))

    assert result["suggestions_new_story"] == len(ANSWERS)
    for row in await _suggestions(sessionmaker, SuggestionKind.NEW_STORY):
        s = _contract(row)
        assert s.payload.kind == "new_story"
        answer = facts.said_text([ANSWERS[row.source_question_ref or ""]])
        assert facts.unbacked(s.payload.action or "", s.payload.quotes, answer) == []
        assert s.source_session_id == session.id

    brief, _ = load_scripted("beh-01")
    tested = {c for q in brief.questions if q.id in ANSWERS for c in q.competencies}
    missing = await _suggestions(sessionmaker, SuggestionKind.MISSING_SKILL)
    assert {_contract(m).payload.competency for m in missing} == tested  # type: ignore[union-attr]
    assert {m.job_target_id for m in missing} == {session.job_target_id}
    assert {m.source_session_id for m in missing} == {session.id}
    assert all(m.prompt_ref is None for m in missing)  # rule-based


def test_sg4_a_skill_with_a_story_is_missing_only_when_its_answer_scored_2_or_less() -> None:
    """SG-4: no story for the skill, or an answer scored 2 or less."""
    brief, turns = load_scripted("beh-01")
    reply = scorecard_reply(brief, turns, 2)
    from strong_core.schemas import QuestionScore

    per_question = [QuestionScore.model_validate(q) for q in reply["per_question"]]
    tested = {s.competency for q in per_question for s in q.scores}
    low = missing_skills(per_question, story_skills=tested)
    assert set(low) == tested
    assert all("scored 2 of 4" in r for r in low.values())
    good = [
        q.model_copy(update={"scores": [s.model_copy(update={"score": 3}) for s in q.scores]})
        for q in per_question
    ]
    assert missing_skills(good, story_skills=tested) == {}
    some = next(iter(tested))
    assert set(missing_skills(good, story_skills=tested - {some})) == {some}


async def test_sg8_a_dismissed_suggestion_never_comes_back(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SG-8: the step runs again (a rescore): nothing is added twice, and a dismissed missing
    skill stays dismissed, also after another take of the same role."""
    org_id, user_id = account
    backend = _scored(4)
    session = await _make_session(sessionmaker, org_id, user_id)
    await jobs.score_session(_ctx(sessionmaker, backend), str(session.id), str(org_id))
    before = await _suggestions(sessionmaker)
    async with sessionmaker() as db:
        row = await db.get(SuggestionRow, before[-1].id)
        assert row is not None and row.kind == SuggestionKind.MISSING_SKILL
        row.status = SuggestionStatus.DISMISSED
        await db.commit()
        again = await apply_suggestion_step(
            db, ModelGateway(fake_models_config(), fake=backend), session
        )
    assert again.tune == again.new_story == again.missing_skill == 0
    after = await _suggestions(sessionmaker)
    assert len(after) == len(before)
    assert {r.status for r in after if r.id == before[-1].id} == {SuggestionStatus.DISMISSED}

    async with sessionmaker() as db:
        added = await add_suggestion(
            db,
            org_id=org_id,
            user_id=user_id,
            kind=SuggestionKind.MISSING_SKILL,
            payload=_contract(before[-1]).payload,  # type: ignore[arg-type]
            reason="Another take of the role.",
            same=lambda p: p.get("competency") == before[-1].payload["competency"],
            extra={"source_session_id": None},
            job_target_id=session.job_target_id,
        )
    assert added is False


# --- SG-5: tailor for a role -----------------------------------------------------------------


async def test_sg5_story_fit_gives_the_lead_story_a_tailoring_note_for_the_company(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SG-5: a new story fit table adds a tailor suggestion for the lead story, titled with the
    posting's company (code owns the company and skill, not the model)."""
    org_id, user_id = account
    story_id = await _add_story(sessionmaker, org_id, user_id, "Checkout", ["ownership"])
    posting = json.loads((FIXTURES / "extractor/JobPosting.json").read_text(encoding="utf-8"))
    async with sessionmaker() as db:
        target = JobTarget(org_id=org_id, user_id=user_id, name="Role", parsed_json=posting)
        db.add(target)
        await db.commit()
    fit = {
        "items": [
            {
                "competency": "ownership",
                "story_id": str(story_id),
                "strength": "strong",
                "reason": "R.",
            }
        ]
    }
    tailor = {
        "kind": "tailor_role",
        "company": "Other",
        "competency": "impact",
        "note": "Lead with it.",
    }
    backend = ScriptedBackend([fit, tailor])
    gateway = ModelGateway(fake_models_config(), fake=backend)

    class Cache:
        data: dict[str, Any] = {}

        async def get(self, key: str) -> Any:
            return self.data.get(key)

        async def set(self, key: str, value: Any, ex: int | None = None) -> None:
            self.data[key] = value

    ctx = {
        gap_jobs.CTX_KEY: gap_jobs.GapContext(sessionmaker=sessionmaker, gateway=gateway),
        "redis": Cache(),
    }
    result = await run_story_fit(ctx, str(org_id), str(target.id), ["ownership"])
    assert result["tailor_added"] == 1
    (row,) = await _suggestions(sessionmaker, SuggestionKind.TAILOR_ROLE)
    s = _contract(row)
    assert s.payload.kind == "tailor_role"
    assert s.payload.company == posting["company_name"]
    assert s.payload.competency == Competency.OWNERSHIP
    assert s.story_id == story_id and s.job_target_id == target.id

    # The same table again (a changed story) does not add it twice.
    async with sessionmaker() as db:
        story = await db.get(StoryRow, story_id)
        assert story is not None
        story.result = "Errors fell."
        await db.commit()
    backend.replies = [fit, tailor]
    again = await run_story_fit(ctx, str(org_id), str(target.id), ["ownership"])
    assert again["tailor_added"] == 0


# --- SG-6: improve a resume line -------------------------------------------------------------


def _resume_json(lines: list[str]) -> dict[str, Any]:
    resume = json.loads((FIXTURES / "extractor/Resume.json").read_text(encoding="utf-8"))
    resume["roles"][0]["achievements"] = lines
    return dict(resume)


async def test_sg6_a_story_result_with_a_number_rewrites_the_matching_resume_line(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SG-6: the main resume's line about the same work, without a number, is rewritten from the
    story's words; a rewrite with a fact the story lacks is not stored."""
    org_id, user_id = account
    story_id = await _add_story(
        sessionmaker,
        org_id,
        user_id,
        "Refunds API rebuild",
        action="I rebuilt the refunds API for our merchants.",
        result="Refunds took 40 percent less time after the rebuild.",
    )
    lines = ["Cut invoice job runtime from 4 hours to 25 minutes", "Rebuilt the refunds API"]
    async with sessionmaker() as db:
        resume = ResumeRow(
            org_id=org_id, user_id=user_id, parsed_json=_resume_json(lines), is_main=True
        )
        db.add(resume)
        await db.commit()
    edit = {
        "resume_line_ref": "roles[9].achievements[9]",
        "before": "x",
        "after": "Rebuilt the refunds API; refunds took 40 percent less time",
        "quotes": ["I rebuilt the refunds API", "Refunds took 40 percent less time"],
    }
    ctx = _ctx(sessionmaker, ScriptedBackend([edit]))
    result = await suggestion_jobs.suggest_resume_line(ctx, str(org_id), str(story_id))
    assert result["outcome"] == "added"
    (row,) = await _suggestions(sessionmaker, SuggestionKind.IMPROVE_RESUME_LINE)
    s = _contract(row)
    assert s.payload.kind == "improve_resume_line"
    assert s.payload.resume_line_ref == "roles[0].achievements[1]"  # code's, not the model's
    assert s.payload.before == "Rebuilt the refunds API"
    assert s.resume_id == resume.id and s.story_id == story_id

    again = await suggestion_jobs.suggest_resume_line(ctx, str(org_id), str(story_id))
    assert again["outcome"] == "exists"

    bad = {
        **edit,
        "after": "Rebuilt the refunds API for 9 banks; refunds took 40 percent less time",
    }
    async with sessionmaker() as db:
        await db.delete(await db.get(SuggestionRow, row.id))
        await db.commit()
    rejected = await suggestion_jobs.suggest_resume_line(
        _ctx(sessionmaker, ScriptedBackend([bad])), str(org_id), str(story_id)
    )
    assert rejected["outcome"] == "rejected"


def test_sg6_the_line_is_the_one_about_the_same_work_without_a_number() -> None:
    from strong_core.schemas import Resume
    from strong_worker.inputs.story_ideas import achievements

    resume = Resume.model_validate(
        _resume_json(["Built the refunds API used by 2,000 merchants", "Rebuilt the refunds API"])
    )
    found = best_line(achievements(resume), "Refunds API rebuild. I rebuilt the refunds API.")
    assert found is not None and found.ref == "roles[0].achievements[1]"
    assert best_line(achievements(resume), "Hiring plan for the platform team") is None


# --- ST-11: review a story -------------------------------------------------------------------


async def test_st11_review_stores_notes_and_only_edits_from_the_users_words(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ST-11, SG-7: the review's edit stays when its words are the user's, and is dropped (the
    note kept) when they are not. One open review per story."""
    org_id, user_id = account
    with_words = await _add_story(
        sessionmaker,
        org_id,
        user_id,
        "Checkout",
        context="We were done a week before Black Friday and not one payment failed.",
        result="The migration went well.",
    )
    without = await _add_story(
        sessionmaker, org_id, user_id, "Hiring", result="The migration went well."
    )
    ctx = _ctx(sessionmaker, FakeBackend())
    for story_id in (with_words, with_words, without):
        result = await suggestion_jobs.review_story(ctx, str(org_id), str(story_id))
        assert result["outcome"] == "reviewed"
    reviews = await _suggestions(sessionmaker, SuggestionKind.REVIEW)
    assert len(reviews) == 2  # the second review of a story replaced the first
    by_story = {r.story_id: _contract(r) for r in reviews}
    kept = by_story[with_words].payload
    assert kept.kind == "review"
    result_note = next(n for n in kept.review.notes if n.part.value == "result")
    assert result_note.edit is not None
    assert result_note.edit.before == "The migration went well."
    dropped = by_story[without].payload
    assert dropped.kind == "review"
    assert all(n.edit is None for n in dropped.review.notes)
    assert len(dropped.review.notes) == len(
        StoryReview.model_validate_json(
            (FIXTURES / "coach/StoryReview.json").read_text(encoding="utf-8")
        ).notes
    )


def test_u08_jobs_are_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert {"suggest_resume_line", "review_story"} <= names
