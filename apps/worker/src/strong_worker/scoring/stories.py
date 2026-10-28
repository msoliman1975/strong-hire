"""Stories in scoring: the story each answer used (ST-6) and the Proven rule (ST-7).

This runs as its own step after the scorecard is stored (score_session calls
`run_story_step`). It never changes a score and never fails the scoring job: any error is
logged and the scorecard stays as the scorer wrote it.

Steps, per scored answer:
1. Code ranks the user's stories by how many of the answer's scored competencies they are
   tagged with, and keeps the top few for the prompt.
2. One scorer-role call (prompt scorer/story_match) reads the answer, the misses and the
   stories, and replies "STORY: <id or NONE>" and "FIX: <one sentence>". Plain text, so it
   works without JSON mode (PL-3). A small-tier model (PL-5) is asked about one story at a
   time, YES or NO, in ranked order, and the first YES wins.
3. Code writes story_id and story_fix on the answer's QuestionScore, and adds the fix to the
   story as a note (StoryNote).
4. The Proven rule, in code: `proves_story`.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import ModelProfile
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import TURN_ORDER
from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.registry import CapabilityTier
from strong_core.prompts import PromptTemplate, load_prompt
from strong_core.schemas import (
    Competency,
    Mode,
    Phase,
    QuestionScore,
    Speaker,
    Story,
    StoryNote,
    StoryPart,
    StoryStatus,
)
from strong_worker.quoting import quote_untrusted

log = logging.getLogger(__name__)

ROLE = Role.SCORER
PROVEN_MIN_SCORE = 3.0
# PL-6: sessions on these profiles are development data. They never prove a story.
DEV_PROFILES = frozenset({ModelProfile.FAKE, ModelProfile.TINY, ModelProfile.LOCAL})
MAX_STORIES = 12  # stories in one story_match call, best ranked first
MAX_STORIES_SMALL = 3  # small tier: yes/no calls per answer
PART_CHARS = 400
ANSWER_CHARS = 4000
FIX_CHARS = 300
_LINE = re.compile(r"^\s*(STORY|FIX)\s*:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)


# --- stories as data -------------------------------------------------------------------------


def story_from_row(row: StoryRow) -> Story:
    return Story.model_validate(
        {
            "id": row.id,
            "title": row.title,
            "context": row.context,
            "stakes": row.stakes,
            "action": row.action,
            "result": row.result,
            "reflection": row.reflection,
            "skills": row.skills or [],
            "status": row.status,
            "source": row.source,
            "source_session_id": row.source_session_id,
            "source_question_ref": row.source_question_ref,
            "notes": row.notes_json or [],
            "created_at": row.created_at,
            "updated_at": row.updated_at or row.created_at,
        }
    )


async def load_user_stories(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[StoryRow]:
    rows = await db.scalars(
        select(StoryRow)
        .where(StoryRow.org_id == org_id, StoryRow.user_id == user_id)
        .order_by(StoryRow.created_at, StoryRow.id)
    )
    return list(rows)


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def render_story(label: str, story: Story, *, tags: bool = True) -> str:
    """One story for a prompt: '<label>: "title" [tags]' and one quoted line per filled part."""
    skills = f" [{', '.join(s.value for s in story.skills)}]" if tags and story.skills else ""
    lines = [f"{label}: {quote_untrusted(story.title)}{skills}"]
    for part in StoryPart:
        text = story.part(part)
        if text and text.strip():
            lines.append(f"  {part.value}: {quote_untrusted(_clip(text, PART_CHARS))}")
    return "\n".join(lines)


# --- the Proven rule (ST-7) ------------------------------------------------------------------


def answer_score(question: QuestionScore) -> float | None:
    """The answer's score: the mean of its competency scores (1 to 4)."""
    if not question.scores:
        return None
    return sum(s.score for s in question.scores) / len(question.scores)


def counts_for_proven(mode: Mode, model_profile: str | None) -> bool:
    """Only Realistic sessions on a real model profile can prove a story (ST-7, PL-6)."""
    return (
        mode == Mode.REALISTIC and model_profile is not None and (model_profile not in DEV_PROFILES)
    )


def proves_story(mode: Mode, model_profile: str | None, question: QuestionScore) -> bool:
    """ST-7: a Realistic answer that used a story and scores 3 or more proves the story.

    Coach sessions and development-profile sessions never count."""
    score = answer_score(question)
    return (
        question.story_id is not None
        and score is not None
        and score >= PROVEN_MIN_SCORE
        and counts_for_proven(mode, model_profile)
    )


# --- matching (ST-6) -------------------------------------------------------------------------


@dataclass
class StoryMatch:
    question_ref: str
    story_id: uuid.UUID | None
    fix: str | None


@dataclass
class MatchResult:
    matches: list[StoryMatch] = field(default_factory=list)
    model_calls: int = 0
    prompt_ref: str | None = None
    errors: list[str] = field(default_factory=list)


def answers_by_question(turns: Sequence[TurnRow]) -> dict[str, str]:
    """question_ref -> the candidate's CORE words for it, in order."""
    out: dict[str, list[str]] = {}
    for t in turns:
        if (
            t.speaker == Speaker.CANDIDATE
            and t.phase == Phase.CORE
            and t.question_ref
            and t.text.strip()
        ):
            out.setdefault(t.question_ref, []).append(t.text.strip())
    return {ref: " ".join(parts) for ref, parts in out.items()}


def rank_stories(stories: Sequence[Story], competencies: Sequence[Competency]) -> list[Story]:
    """Stories tagged with more of the answer's competencies first; then newest first."""
    wanted = set(competencies)
    return sorted(
        stories,
        key=lambda s: (-len(wanted & set(s.skills)), -s.updated_at.timestamp(), str(s.id)),
    )


def parse_reply(text: str) -> tuple[str | None, str | None]:
    """(story token, fix) from a 'STORY: ...' / 'FIX: ...' reply. NONE becomes None."""
    found: dict[str, str] = {}
    for key, value in _LINE.findall(text):
        found.setdefault(key.upper(), value.strip().strip('"').strip())
    story = found.get("STORY")
    fix = found.get("FIX")
    if story is not None and story.upper() in {"NONE", "NO", ""}:
        story = None
    if fix is not None and (fix.upper() == "NONE" or not fix):
        fix = None
    return story, (_clip(fix, FIX_CHARS) if fix else None)


class StoryMatcher:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway
        self.small = gateway.capabilities(ROLE).tier == CapabilityTier.SMALL

    def _prompts(self) -> tuple[PromptTemplate, PromptTemplate]:
        tier = self.gateway.capabilities(ROLE).tier
        return (
            load_prompt(ROLE, "story_match", tier=tier),
            load_prompt(ROLE, "story_match_input", tier=tier),
        )

    async def match(
        self,
        per_question: Sequence[QuestionScore],
        answers: dict[str, str],
        stories: Sequence[Story],
    ) -> MatchResult:
        result = MatchResult()
        if not stories:
            return result
        system, user = self._prompts()
        result.prompt_ref = system.ref
        for q in per_question:
            answer = answers.get(q.question_ref)
            if not answer:
                continue
            ranked = rank_stories(stories, [s.competency for s in q.scores])
            try:
                if self.small:
                    match = await self._match_small(system, user, q, answer, ranked, result)
                else:
                    match = await self._match_all(system, user, q, answer, ranked, result)
            except Exception as exc:  # one answer's failure never stops the others
                log.warning("story match failed for %s: %s", q.question_ref, exc)
                result.errors.append(f"{q.question_ref}: {type(exc).__name__}")
                continue
            if match is not None:
                result.matches.append(match)
        return result

    def _user(self, user: PromptTemplate, q: QuestionScore, answer: str, stories: str) -> Any:
        return user.message(
            "user",
            question=quote_untrusted(q.question_text),
            misses="\n".join(f"- {m}" for m in q.misses) or "- none noted",
            answer=quote_untrusted(_clip(answer, ANSWER_CHARS)),
            stories=stories,
        )

    async def _match_all(
        self,
        system: PromptTemplate,
        user: PromptTemplate,
        q: QuestionScore,
        answer: str,
        ranked: list[Story],
        result: MatchResult,
    ) -> StoryMatch | None:
        shown = ranked[:MAX_STORIES]
        labels = {f"S{i}": s for i, s in enumerate(shown, start=1)}
        text = "\n".join(render_story(label, s, tags=False) for label, s in labels.items())
        result.model_calls += 1
        done = await self.gateway.complete(
            ROLE, [system.message("system"), self._user(user, q, answer, text)]
        )
        token, fix = parse_reply(done.output)
        if token is None:
            return None
        story = labels.get(token.upper().strip(" .[]"))
        if story is None:
            return None  # an id that was not offered: no match
        return StoryMatch(q.question_ref, story.id, fix or _fallback_fix(q))

    async def _match_small(
        self,
        system: PromptTemplate,
        user: PromptTemplate,
        q: QuestionScore,
        answer: str,
        ranked: list[Story],
        result: MatchResult,
    ) -> StoryMatch | None:
        for story in ranked[:MAX_STORIES_SMALL]:
            result.model_calls += 1
            done = await self.gateway.complete(
                ROLE,
                [
                    system.message("system"),
                    self._user(user, q, answer, render_story("", story, tags=False).lstrip(": ")),
                ],
            )
            token, fix = parse_reply(done.output)
            if token is not None and token.upper().startswith("YES"):
                return StoryMatch(q.question_ref, story.id, fix or _fallback_fix(q))
        return None


def _fallback_fix(q: QuestionScore) -> str | None:
    """When the model names a story but no fix, the answer's first miss is the fix."""
    return _clip(q.misses[0], FIX_CHARS) if q.misses else None


# --- the step after scoring ------------------------------------------------------------------


@dataclass
class StoryStepOutcome:
    matched: int = 0
    notes: int = 0
    proven: list[str] = field(default_factory=list)
    model_calls: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stories_matched": self.matched,
            "story_notes": self.notes,
            "stories_proven": len(self.proven),
            "story_calls": self.model_calls,
            "story_errors": len(self.errors),
        }


async def apply_story_step(
    db: AsyncSession, gateway: ModelGateway, session: InterviewSession
) -> StoryStepOutcome:
    """Match the stored scorecard's answers to the user's stories and save the results."""
    outcome = StoryStepOutcome()
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
    rows = await load_user_stories(db, session.org_id, user_id)
    if not rows:
        return outcome
    by_id = {r.id: r for r in rows}
    stories = [story_from_row(r) for r in rows]
    per_question = [QuestionScore.model_validate(q) for q in card.per_question_json]
    turns = list(
        await db.scalars(
            select(TurnRow).where(TurnRow.session_id == session.id).order_by(*TURN_ORDER)
        )
    )
    result = await StoryMatcher(gateway).match(per_question, answers_by_question(turns), stories)
    outcome.model_calls = result.model_calls
    outcome.errors = result.errors
    if not result.matches:
        return outcome

    found = {m.question_ref: m for m in result.matches}
    now = datetime.now(UTC)
    updated: list[dict[str, Any]] = []
    for q in per_question:
        m = found.get(q.question_ref)
        if m is not None and m.story_id in by_id:
            q = q.model_copy(update={"story_id": m.story_id, "story_fix": m.fix})
            outcome.matched += 1
            row = by_id[m.story_id]
            if m.fix:
                note = StoryNote(
                    text=m.fix, session_id=session.id, question_ref=q.question_ref, at=now
                )
                row.notes_json = [*(row.notes_json or []), note.model_dump(mode="json")]
                outcome.notes += 1
            if row.status != StoryStatus.PROVEN and proves_story(
                session.mode, session.model_profile, q
            ):
                row.status = StoryStatus.PROVEN
                outcome.proven.append(str(row.id))
            row.updated_at = now
        updated.append(q.model_dump(mode="json"))
    card.per_question_json = updated
    await db.commit()
    return outcome


async def run_story_step(
    sessionmaker: async_sessionmaker[AsyncSession],
    gateway: ModelGateway,
    session_id: uuid.UUID,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """The step score_session runs after the scorecard is stored. It never raises."""
    try:
        async with sessionmaker() as db:
            session = await db.scalar(
                select(InterviewSession).where(
                    InterviewSession.id == session_id, InterviewSession.org_id == org_id
                )
            )
            if session is None:
                return StoryStepOutcome().as_dict()
            outcome = await apply_story_step(db, gateway, session)
    except Exception:
        log.exception(
            "story matching failed for session %s; the scorecard is unchanged", session_id
        )
        return {**StoryStepOutcome().as_dict(), "story_errors": 1}
    return outcome.as_dict()
