"""Suggestions after a take is scored (SG-2, SG-3, SG-4).

score_session runs `run_suggestion_step` after the story step (ST-6), so each answer already has
its `story_id` and `story_fix`. Per scored answer:
- it used a story and has a fix: tune that story, one part, from the answer's words (SG-2);
- it used no story and scored 4, or 3 with context, action and result in its words: a new story
  (SG-3);
then per tested skill, by rule: no story shows it, or its answer scored 2 or less: missing skill,
for the session's role (SG-4).
Like the story step it never changes a score and never fails the scoring job.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import TURN_ORDER
from strong_core.gateway import ModelGateway
from strong_core.schemas import (
    Competency,
    MissingSkillPayload,
    NewStoryPayload,
    QuestionScore,
    SuggestionKind,
    TuneStoryPayload,
)
from strong_worker.scoring.stories import (
    answer_score,
    answers_by_question,
    load_user_stories,
    story_from_row,
)
from strong_worker.suggestions import generate
from strong_worker.suggestions.store import add_suggestion, payload_has

log = logging.getLogger(__name__)

NEW_STORY_SCORE = 4.0
NEW_STORY_SCORE_WITH_PARTS = 3.0
LOW_SCORE = 2.0
MAX_MODEL_SUGGESTIONS = 6  # tune and new story calls per take


def skill_label(c: Competency) -> str:
    return c.value.replace("_", " ").capitalize()


@dataclass
class SuggestionStepOutcome:
    tune: int = 0
    new_story: int = 0
    missing_skill: int = 0
    rejected: int = 0
    model_calls: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "suggestions_tune": self.tune,
            "suggestions_new_story": self.new_story,
            "suggestions_missing_skill": self.missing_skill,
            "suggestions_rejected": self.rejected,
            "suggestion_calls": self.model_calls,
            "suggestion_errors": len(self.errors),
        }


def missing_skills(
    per_question: list[QuestionScore], story_skills: set[Competency]
) -> dict[Competency, str]:
    """SG-4: each tested skill with no story, or with an answer that scored 2 or less, and why."""
    out: dict[Competency, str] = {}
    lowest: dict[Competency, float] = {}
    for q in per_question:
        for s in q.scores:
            lowest[s.competency] = min(lowest.get(s.competency, 5.0), float(s.score))
    for c, low in lowest.items():
        if c not in story_skills:
            out[c] = f"None of your stories shows {skill_label(c).lower()} yet."
        elif low <= LOW_SCORE:
            out[c] = f"Your answer on {skill_label(c).lower()} scored {low:g} of 4."
    return out


async def apply_suggestion_step(
    db: AsyncSession, gateway: ModelGateway, session: InterviewSession
) -> SuggestionStepOutcome:
    outcome = SuggestionStepOutcome()
    card = await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
    if card is None or not card.per_question_json:
        return outcome
    user_id = await db.scalar(
        select(JobTarget.user_id).where(
            JobTarget.id == session.job_target_id, JobTarget.org_id == session.org_id
        )
    )
    if user_id is None:
        return outcome
    stories = {
        r.id: story_from_row(r) for r in await load_user_stories(db, session.org_id, user_id)
    }
    per_question = [QuestionScore.model_validate(q) for q in card.per_question_json]
    turns = await db.scalars(
        select(TurnRow).where(TurnRow.session_id == session.id).order_by(*TURN_ORDER)
    )
    answers = answers_by_question(list(turns))
    common: dict[str, Any] = {"org_id": session.org_id, "user_id": user_id}

    calls_left = MAX_MODEL_SUGGESTIONS
    for q in per_question:
        answer = answers.get(q.question_ref, "").strip()
        if not answer or calls_left <= 0:
            continue
        score = answer_score(q) or 0.0
        try:
            if q.story_id is not None and q.story_fix and q.story_id in stories:
                calls_left -= 1
                tune = await generate.tune_story(gateway, stories[q.story_id], answer, q.story_fix)
                outcome.model_calls += tune.calls
                if tune.output is None:
                    outcome.rejected += 1
                    continue
                added = await add_suggestion(
                    db,
                    **common,
                    kind=SuggestionKind.TUNE_STORY,
                    payload=TuneStoryPayload(edit=tune.output),
                    reason=f"From your answer to “{q.question_text}”: {q.story_fix}",
                    prompt_ref=tune.prompt_ref,
                    source_session_id=session.id,
                    source_question_ref=q.question_ref,
                    job_target_id=session.job_target_id,
                    story_id=q.story_id,
                )
                outcome.tune += added
            elif q.story_id is None and score >= NEW_STORY_SCORE_WITH_PARTS:
                calls_left -= 1
                skills = [s.competency for s in q.scores if s.score >= NEW_STORY_SCORE_WITH_PARTS]
                written = await generate.new_story(gateway, q.question_text, answer, skills)
                outcome.model_calls += written.calls
                story: NewStoryPayload | None = written.output
                if story is None or (
                    score < NEW_STORY_SCORE and not generate.has_story_parts(story)
                ):
                    outcome.rejected += story is None
                    continue
                added = await add_suggestion(
                    db,
                    **common,
                    kind=SuggestionKind.NEW_STORY,
                    payload=story,
                    reason=f"Your answer to “{q.question_text}” scored {score:g} of 4. "
                    "It is not a story yet.",
                    prompt_ref=written.prompt_ref,
                    source_session_id=session.id,
                    source_question_ref=q.question_ref,
                    job_target_id=session.job_target_id,
                )
                outcome.new_story += added
        except Exception as exc:  # one answer's suggestion never stops the others
            log.warning("suggestion for %s/%s failed: %s", session.id, q.question_ref, exc)
            outcome.errors.append(type(exc).__name__)

    story_skills = {c for s in stories.values() for c in s.skills}
    for c, reason in missing_skills(per_question, story_skills).items():
        added = await add_suggestion(
            db,
            **common,
            kind=SuggestionKind.MISSING_SKILL,
            payload=MissingSkillPayload(competency=c),
            reason=reason,
            same=payload_has("competency", c.value),
            # Shown on this debrief; later takes of the role do not add it again.
            extra={"source_session_id": session.id},
            job_target_id=session.job_target_id,
        )
        outcome.missing_skill += added
    await db.commit()
    return outcome


async def run_suggestion_step(
    sessionmaker: async_sessionmaker[AsyncSession],
    gateway: ModelGateway,
    session_id: uuid.UUID,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """The step score_session runs after the story step. It never raises."""
    try:
        async with sessionmaker() as db:
            session = await db.scalar(
                select(InterviewSession).where(
                    InterviewSession.id == session_id, InterviewSession.org_id == org_id
                )
            )
            if session is None:
                return SuggestionStepOutcome().as_dict()
            outcome = await apply_suggestion_step(db, gateway, session)
    except Exception:
        log.exception("suggestions failed for session %s; the scorecard is unchanged", session_id)
        return {**SuggestionStepOutcome().as_dict(), "suggestion_errors": 1}
    return outcome.as_dict()
