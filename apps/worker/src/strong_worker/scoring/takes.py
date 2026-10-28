"""Arq job that scores a take: one telling of a story (CO-7).

The API (strong_api.takes) stores the take and enqueues `score_take`. The job scores it with the
existing scorer (scorer/rubric, PL-3), as one answer to one question, on the story's skill tags:

- the take becomes a one-question transcript: the interviewer asks for the story, the candidate
  tells it. The brief is a mini behavioral-style brief whose one asked question carries the
  story's skills; the scorer keeps only asked questions, so the brief's two filler questions are
  never scored;
- the level is the story's linked job level (the job of the session the story came from), else
  the user's target level, else mid;
- generic mode: a take is practice on the candidate's own story, not a company interview;
- quotes are checked by the scorer (FB-2); per-skill 1 to 4 scores with quotes and PL-6
  provenance are stored on the take row.

A take never changes the story's Draft or Proven status (only ST-7 does) and never writes a
progress snapshot, so it never counts toward readiness. The scorer's rationale is not shown for
a take, so it is built in code (no model call).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core import runtime_settings as rs
from strong_core.db.models import InterviewSession, JobTarget, Story, Take, User
from strong_core.gateway import ModelGateway, Role
from strong_core.profiles import GENERIC_PERSONA, generic_profile
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    STANDARD_INTERVIEW_TYPES,
    BriefQuestion,
    Competency,
    CompetencyScore,
    Difficulty,
    InterviewerBrief,
    InterviewType,
    Level,
    Mode,
    PersonaBrief,
    Phase,
    QuestionScore,
    SessionConfig,
    Speaker,
    Turn,
)
from strong_core.sim import gateway_for_org
from strong_worker.ops.context import job_context
from strong_worker.pause import wait_if_paused
from strong_worker.scoring.jobs import ScoringContext, _ctx
from strong_worker.scoring.scorer import ScoringError, SessionScorer, fallback_rationale
from strong_worker.scoring.signal import SignalResult

log = logging.getLogger(__name__)

TAKE_REF = "take"
TAKE_QUESTION = "Tell me about {title}."
DEFAULT_LEVEL = Level.MID
_FILLER = ("filler-1", "filler-2")  # brief questions that are never asked, so never scored


class TakeScorer(SessionScorer):
    """The session scorer with its rationale built in code: a take shows scores, not a signal."""

    async def _rationale(
        self,
        brief: InterviewerBrief,
        signal: SignalResult,
        comp_avgs: dict[Competency, float],
        value_avgs: dict[str, float],
        profile: Any,
        per_question: list[QuestionScore],
    ) -> tuple[str, str, int]:
        return fallback_rationale(signal, comp_avgs, value_avgs), "code", 0


def take_interview_type(skills: Sequence[Competency]) -> InterviewType:
    """The standard type whose competencies cover most of the story's skills (first wins)."""
    counts = Counter(
        t for t in STANDARD_INTERVIEW_TYPES for s in skills if s in COMPETENCIES_BY_TYPE[t]
    )
    return max(STANDARD_INTERVIEW_TYPES, key=lambda t: counts[t])


def take_brief(title: str, skills: Sequence[Competency], level: Level) -> InterviewerBrief:
    """A mini brief with one scored question: the story, on the skills its type can score."""
    kind = take_interview_type(skills)
    pool = COMPETENCIES_BY_TYPE[kind]
    scored = [s for s in skills if s in pool]
    if not scored:
        raise ScoringError("None of the story's skills can be scored.")
    targets = list(dict.fromkeys([*scored, *pool]))[: max(2, min(len(scored), 6))]
    persona = PersonaBrief(
        tone=GENERIC_PERSONA.tone,
        pushback_style=GENERIC_PERSONA.pushback_style,
        closing_style=GENERIC_PERSONA.closing_style,
    )
    question = BriefQuestion(
        id=TAKE_REF, text=TAKE_QUESTION.format(title=title), competencies=scored, priority=1
    )
    fillers = [
        BriefQuestion(id=ref, text="(not asked)", competencies=[pool[0]], priority=i + 2)
        for i, ref in enumerate(_FILLER)
    ]
    return InterviewerBrief(
        session=SessionConfig(
            interview_type=kind,
            difficulty=Difficulty.REALISTIC,
            mode=Mode.COACH,
            duration_min=10,
            level=level,
        ),
        generic_mode=True,
        target_competencies=targets,
        questions=[question, *fillers],
        persona=persona,
        max_probes_per_question=0,
    )


def take_turns(question: str, text: str) -> list[Turn]:
    return [
        Turn(
            speaker=Speaker.INTERVIEWER,
            phase=Phase.CORE,
            text=question,
            start_ms=0,
            end_ms=0,
            question_ref=TAKE_REF,
        ),
        Turn(
            speaker=Speaker.CANDIDATE,
            phase=Phase.CORE,
            text=text,
            start_ms=0,
            end_ms=0,
            question_ref=TAKE_REF,
        ),
    ]


async def take_level(db: AsyncSession, story: Story) -> Level:
    """The story's linked job level, else the user's target level, else mid."""
    if story.source_session_id is not None:
        level = await db.scalar(
            select(JobTarget.level)
            .join(InterviewSession, InterviewSession.job_target_id == JobTarget.id)
            .where(
                InterviewSession.id == story.source_session_id,
                InterviewSession.org_id == story.org_id,
            )
        )
        if level is not None:
            return level
    target = await db.scalar(
        select(User.target_level).where(User.id == story.user_id, User.org_id == story.org_id)
    )
    return target or DEFAULT_LEVEL


async def score_take_text(
    gateway: ModelGateway, title: str, skills: Sequence[Competency], level: Level, text: str
) -> tuple[list[CompetencyScore], str]:
    """(per-skill scores with checked quotes, the scorer prompt ref). Only the story's own
    skills are kept, not the brief's padding targets."""
    brief = take_brief(title, skills, level)
    turns = take_turns(brief.questions[0].text, text)
    outcome = await TakeScorer(gateway).score(brief, turns, generic_profile())
    asked = set(brief.questions[0].competencies)
    scores = [s for s in outcome.scorecard.competency_scores if s.competency in asked]
    if not scores:
        raise ScoringError("No skill of the story has a quote that appears in the take.")
    return scores, outcome.scorecard.rubric_version


@job_context()
async def score_take(ctx: dict[str, Any], take_id: str, org_id: str) -> dict[str, Any]:
    scoring: ScoringContext = _ctx(ctx)
    await wait_if_paused(ctx, scoring.sessionmaker, rs.JobKind.SCORING)  # OC-5
    async with scoring.sessionmaker() as db:
        take = await db.scalar(
            select(Take).where(Take.id == uuid.UUID(take_id), Take.org_id == uuid.UUID(org_id))
        )
        if take is None:
            return {"outcome": "failed", "reason": "take not found"}
        if take.skill_scores_json is not None:
            return {"outcome": "exists"}
        story = await db.scalar(
            select(Story).where(Story.id == take.story_id, Story.org_id == take.org_id)
        )
        if story is None:
            return {"outcome": "failed", "reason": "story not found"}
        skills = [Competency(s) for s in story.skills]
        level = await take_level(db, story)
        try:
            gateway = await gateway_for_org(db, take.org_id, scoring.gateway)  # P13
            scores, rubric = await score_take_text(gateway, story.title, skills, level, take.text)
        except ScoringError as exc:
            log.warning("take %s not scored: %s", take.id, exc)
            return {"outcome": "failed", "reason": str(exc)}
        except Exception as exc:  # a model or gateway failure: the take shows as not scored
            log.exception("scoring failed for take %s", take.id)
            return {"outcome": "failed", "reason": f"Scoring failed: {type(exc).__name__}"}
        take.skill_scores_json = [s.model_dump(mode="json") for s in scores]
        take.model_profile = gateway.profile
        take.model_id = gateway.config.alias_for(Role.SCORER)
        take.prompt_version = rubric[:200]
        await db.commit()
    return {
        "outcome": "scored",
        "level": level.value,
        "scores": {s.competency.value: s.score for s in scores},
    }


FUNCTIONS = [score_take]
