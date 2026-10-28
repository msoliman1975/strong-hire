"""The day-by-day plan to the interview (RD-2). Rules in code, no model.

    GET /plan/{job_target_id}/{resume_id}/day-plan

The plan is computed on every read from the pair's current data, so it is rebuilt after each
debrief: a new scorecard changes the PR-2 next session, and the page reads the plan again.

Inputs:
- rehearsals: PR-2's next session first, then the GA-3 session plan by priority, without
  repeating a type at the same difficulty. With neither, one Realistic Behavioral rehearsal;
- story work: the ST-5 story fit items that are missing, then thin, in the order of the skills
  the interview tests. A thin item whose story was deleted since counts as missing. Story fit is
  read from the worker's cache; when it is not there yet, the plan has no story items.

Mode: a rehearsal of a type this pair has no completed session of yet runs in Coach mode the
first time it shows up in the plan; every later one runs in Realistic mode.

With an interview date `days_left` days ahead:
- 0 (the interview is today): one item, a short Coach-mode warm-up of the first rehearsal at
  Friendly difficulty;
- 1 or more: one entry per day from today to the day before the interview, at most MAX_DAYS
  (the nearest ones; `days_not_shown` counts the rest). Each day gets the next rehearsal from
  the list, which starts over at the end. Every other day, starting today, also gets the next
  story item while there are any left. The day before the interview gets one item only: a
  Realistic dress rehearsal of the first rehearsal's type.

With no date, or a date that has passed: `next_steps`, the next three items, taking a
rehearsal and a story item in turn.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.inputs.deps import Db, Me
from strong_api.inputs.router import _owned_job_target, _owned_resume
from strong_api.plan import service
from strong_api.scoring.router import get_progress
from strong_core.config import get_settings
from strong_core.db.models import InterviewSession, Story
from strong_core.schemas import (
    Competency,
    Difficulty,
    GapStatus,
    InterviewType,
    Mode,
    PlannedSession,
    SessionStatus,
    StoryFit,
    StoryFitItem,
    StoryFitStrength,
)

router = APIRouter(tags=["interview plan"])

MAX_DAYS = 28
NEXT_STEPS = 3

StoryFitReader = Callable[[uuid.UUID, uuid.UUID], Awaitable[StoryFit | None]]


def story_fit_key(org_id: uuid.UUID | str, job_target_id: uuid.UUID | str) -> str:
    """Same key as strong_worker.gap.story_fit.story_fit_key (a test checks this)."""
    return f"story_fit:{org_id}:{job_target_id}"


async def redis_story_fit(org_id: uuid.UUID, job_target_id: uuid.UUID) -> StoryFit | None:
    """The cached StoryFitRecord's table, or None when it is missing or Redis is down."""
    client = Redis.from_url(get_settings().redis_url)
    try:
        raw = await client.get(story_fit_key(org_id, job_target_id))
        if raw is None:
            return None
        return StoryFit.model_validate(json.loads(raw)["fit"])
    except Exception:  # the plan works without story items
        return None
    finally:
        await client.aclose()


def get_story_fit_reader() -> StoryFitReader:
    return redis_story_fit


Reader = Annotated[StoryFitReader, Depends(get_story_fit_reader)]


class DayPlanItem(BaseModel):
    """One thing to do: a rehearsal (type, difficulty, mode) or work on one story."""

    kind: Literal["rehearsal", "story"]
    interview_type: InterviewType | None = Field(description="Rehearsals only.")
    difficulty: Difficulty | None = Field(description="Rehearsals only.")
    mode: Mode | None = Field(description="Rehearsals only.")
    focus_topics: list[str] = Field(description="Rehearsals only; empty for story items.")
    competency: Competency | None = Field(description="Story items: the skill to cover.")
    story_id: uuid.UUID | None = Field(description="Story items: the thin story to improve.")
    strength: StoryFitStrength | None = Field(description="Story items: thin or missing.")
    reason: str


class DayPlanDay(BaseModel):
    day: date
    items: list[DayPlanItem] = Field(min_length=1, max_length=2)


class DayPlan(BaseModel):
    """RD-2: what to do each day until the interview, or the next three steps."""

    job_target_id: uuid.UUID
    resume_id: uuid.UUID
    interview_date: date | None
    days_left: int | None
    kind: Literal["by_day", "next_steps"] = Field(
        description="by_day with an interview date today or ahead, else next_steps."
    )
    days: list[DayPlanDay] = Field(description="by_day: one entry per day from today.")
    days_not_shown: int = Field(ge=0, description="by_day: days after the last one listed.")
    next_steps: list[DayPlanItem] = Field(description="next_steps: up to three items.")


def rehearsal_list(
    next_session: PlannedSession | None, session_plan: Sequence[PlannedSession]
) -> list[PlannedSession]:
    """PR-2 first, then GA-3 by priority; one entry per type and difficulty."""
    candidates = [next_session] if next_session else []
    candidates += sorted(session_plan, key=lambda p: p.priority)
    out: list[PlannedSession] = []
    seen: set[tuple[InterviewType, Difficulty]] = set()
    for p in candidates:
        if (p.interview_type, p.difficulty) not in seen:
            seen.add((p.interview_type, p.difficulty))
            out.append(p)
    if not out:
        out.append(
            PlannedSession(
                priority=1,
                interview_type=InterviewType.BEHAVIORAL,
                difficulty=Difficulty.REALISTIC,
                focus_topics=["Behavioral practice"],
                reason="Start with a behavioral rehearsal: it scores the skills most loops test.",
            )
        )
    return out


def story_gaps(fit: StoryFit | None, live_story_ids: set[uuid.UUID]) -> list[StoryFitItem]:
    """ST-5 items that need work: missing first, then thin, in table order."""
    if fit is None:
        return []
    items = []
    for item in fit.items:
        if item.story_id is not None and item.story_id not in live_story_ids:
            item = StoryFitItem(
                competency=item.competency,
                story_id=None,
                strength=StoryFitStrength.MISSING,
                reason="The story that fit this skill was deleted.",
            )
        if item.strength != StoryFitStrength.STRONG:
            items.append(item)
    return sorted(items, key=lambda i: i.strength != StoryFitStrength.MISSING)


def _skill(c: Competency) -> str:
    return c.value.replace("_", " ")


def story_item(item: StoryFitItem) -> DayPlanItem:
    if item.strength == StoryFitStrength.MISSING:
        reason = f"No story shows {_skill(item.competency)} yet. Build one with the coach."
    else:
        reason = f"Your {_skill(item.competency)} story is thin. {item.reason}"
    return DayPlanItem(
        kind="story",
        interview_type=None,
        difficulty=None,
        mode=None,
        focus_topics=[],
        competency=item.competency,
        story_id=item.story_id,
        strength=item.strength,
        reason=reason,
    )


def rehearsal_item(
    p: PlannedSession,
    mode: Mode,
    *,
    difficulty: Difficulty | None = None,
    reason: str | None = None,
) -> DayPlanItem:
    return DayPlanItem(
        kind="rehearsal",
        interview_type=p.interview_type,
        difficulty=difficulty or p.difficulty,
        mode=mode,
        focus_topics=p.focus_topics,
        competency=None,
        story_id=None,
        strength=None,
        reason=reason or p.reason,
    )


class _Rehearsals:
    """Hands out rehearsals in turn, starting over at the end; Coach mode for an untried type."""

    def __init__(self, items: Sequence[PlannedSession], practiced: set[InterviewType]) -> None:
        self.items = list(items)
        self.tried = set(practiced)
        self.i = 0

    def next(self) -> DayPlanItem:
        p = self.items[self.i % len(self.items)]
        self.i += 1
        mode = Mode.REALISTIC if p.interview_type in self.tried else Mode.COACH
        self.tried.add(p.interview_type)
        return rehearsal_item(p, mode)


def build_day_plan(
    *,
    job_target_id: uuid.UUID,
    resume_id: uuid.UUID,
    today: date,
    interview_date: date | None,
    rehearsals: Sequence[PlannedSession],
    stories: Sequence[StoryFitItem],
    practiced: set[InterviewType],
) -> DayPlan:
    """RD-2 (rules in the module docstring). `rehearsals` must not be empty."""
    left = service.days_left(interview_date, today)
    queue = _Rehearsals(rehearsals, practiced)
    story_queue = list(stories)
    first = rehearsals[0]

    def plan(**kw: object) -> DayPlan:
        base: dict[str, object] = {
            "job_target_id": job_target_id,
            "resume_id": resume_id,
            "interview_date": interview_date,
            "days_left": left,
            "days": [],
            "days_not_shown": 0,
            "next_steps": [],
        }
        return DayPlan.model_validate(base | kw)

    if left is None or left < 0:
        steps: list[DayPlanItem] = []
        while len(steps) < NEXT_STEPS:
            steps.append(queue.next())
            if story_queue and len(steps) < NEXT_STEPS:
                steps.append(story_item(story_queue.pop(0)))
        return plan(kind="next_steps", next_steps=steps)

    if left == 0:
        warm_up = rehearsal_item(
            first,
            Mode.COACH,
            difficulty=Difficulty.FRIENDLY,
            reason="Interview day: a short, easy warm-up, then rest.",
        )
        return plan(kind="by_day", days=[DayPlanDay(day=today, items=[warm_up])])

    days: list[DayPlanDay] = []
    for i in range(min(left, MAX_DAYS)):
        day = today + timedelta(days=i)
        if i == left - 1:
            dress = rehearsal_item(
                first,
                Mode.REALISTIC,
                difficulty=Difficulty.REALISTIC,
                reason="The day before: one full dress rehearsal, as close to the real "
                "interview as you can make it.",
            )
            days.append(DayPlanDay(day=day, items=[dress]))
            continue
        items = [queue.next()]
        if i % 2 == 0 and story_queue:
            items.append(story_item(story_queue.pop(0)))
        days.append(DayPlanDay(day=day, items=items))
    return plan(kind="by_day", days=days, days_not_shown=max(0, left - MAX_DAYS))


async def practiced_types(
    db: AsyncSession, job_target_id: uuid.UUID, resume_id: uuid.UUID
) -> set[InterviewType]:
    """The types of the pair's completed sessions."""
    rows = await db.scalars(
        select(InterviewSession.type)
        .where(
            InterviewSession.job_target_id == job_target_id,
            InterviewSession.resume_id == resume_id,
            InterviewSession.status == SessionStatus.COMPLETED,
        )
        .distinct()
    )
    return set(rows)


async def live_story_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    return set(await db.scalars(select(Story.id).where(Story.user_id == user_id)))


@router.get(
    "/plan/{job_target_id}/{resume_id}/day-plan",
    responses={404: {"description": "The job target or the resume does not exist."}},
)
async def get_day_plan(
    job_target_id: uuid.UUID, resume_id: uuid.UUID, db: Db, me: Me, read_fit: Reader
) -> DayPlan:
    """RD-2: the day-by-day plan to the interview date, or the next three steps without one."""
    target = await _owned_job_target(db, me, job_target_id)
    resume = await _owned_resume(db, me, resume_id)
    gap_row = await service.latest_pair_gap(db, target.id, resume.id)
    ready = gap_row is not None and gap_row.status == GapStatus.READY
    session_plan = [
        PlannedSession.model_validate(p)
        for p in ((gap_row.session_plan_json or []) if gap_row is not None and ready else [])
    ]
    progress = await get_progress(target.id, db, me)
    fit = await read_fit(me.org_id, target.id)
    return build_day_plan(
        job_target_id=target.id,
        resume_id=resume.id,
        today=service.today(),
        interview_date=target.interview_date,
        rehearsals=rehearsal_list(progress.next_session, session_plan),
        stories=story_gaps(fit, await live_story_ids(db, me.user_id)),
        practiced=await practiced_types(db, target.id, resume.id),
    )
