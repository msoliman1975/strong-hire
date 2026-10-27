"""Admin Part 1 usage (AD-3): plan page use, and the tone and difficulty mix across sessions.

    GET /admin/part1/usage?weeks=8    per UTC week (Monday start): sessions created, by the tone
                                      (TN-1) and the difficulty (IV-4) the user picked; plus the
                                      plan page views and the sessions started from it

Counted from the sessions table. Plan page views and the sessions started from the plan page need
an event that does not exist yet (no product-event store; PostHog is not wired), so they are
reported "not measured" with the reason (AO-8), never hidden.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, select

from strong_api.admin import metrics as m
from strong_api.admin.deps import Admin
from strong_api.auth.deps import DbSession
from strong_core.db.models import InterviewSession
from strong_core.schemas import Difficulty
from strong_core.schemas.enums import Tone

router = APIRouter(prefix="/admin", tags=["admin"])

WEEK_S = 7 * 24 * 3600
# 1970-01-01 was a Thursday; the first Monday is four days later.
MONDAY_OFFSET_S = 4 * 24 * 3600

PLAN_EVENT_MISSING = (
    "No plan page event is recorded yet: the app has no product-event store. "
    "Counts start once the plan page records its views and the sessions it starts."
)


class MixWeek(BaseModel):
    week_start: datetime = Field(description="Monday 00:00 UTC")
    sessions: int
    tone: dict[Tone, int] = Field(description="Sessions per tone; every tone is present")
    difficulty: dict[Difficulty, int] = Field(description="Sessions per difficulty; all present")


class Part1Usage(BaseModel):
    weeks: list[MixWeek] = Field(description="Oldest first; the last one is the current week")
    tone: dict[Tone, int] = Field(description="Totals over the weeks shown")
    difficulty: dict[Difficulty, int] = Field(description="Totals over the weeks shown")
    plan_page_views: m.AdminMetric
    plan_sessions: m.AdminMetric = Field(description="Sessions started from the plan page")


def week_start(at: datetime) -> datetime:
    """Monday 00:00 UTC of the week that holds `at`."""
    day = at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def _week_bucket() -> ColumnElement[int]:
    return (
        (m.epoch(InterviewSession.created_at) - MONDAY_OFFSET_S) // WEEK_S
    ) * WEEK_S + MONDAY_OFFSET_S


@router.get("/part1/usage")
async def get_part1_usage(
    _: Admin,
    db: DbSession,
    weeks: Annotated[int, Query(ge=1, le=52, description="How many weeks, this one included")] = 8,
) -> Part1Usage:
    """AD-3: the tone and difficulty mix by week, and plan page usage."""
    first = week_start(m.now_utc()) - timedelta(weeks=weeks - 1)
    starts = [first + timedelta(weeks=i) for i in range(weeks)]
    by_week = {
        int(s.timestamp()): MixWeek(
            week_start=s,
            sessions=0,
            tone=dict.fromkeys(Tone, 0),
            difficulty=dict.fromkeys(Difficulty, 0),
        )
        for s in starts
    }

    s = InterviewSession
    bucket = _week_bucket().label("week")
    rows = await db.execute(
        select(bucket, s.tone, s.difficulty, func.count())
        .where(s.created_at >= first)
        .group_by(bucket, s.tone, s.difficulty)
    )
    tone_total = dict.fromkeys(Tone, 0)
    difficulty_total = dict.fromkeys(Difficulty, 0)
    for week, tone, difficulty, count in rows:
        row = by_week.get(int(week))
        if row is None:  # created after now (clock skew): not in a week shown
            continue
        n = int(count)
        row.sessions += n
        row.tone[Tone(tone)] += n
        row.difficulty[Difficulty(difficulty)] += n
        tone_total[Tone(tone)] += n
        difficulty_total[Difficulty(difficulty)] += n

    return Part1Usage(
        weeks=list(by_week.values()),
        tone=tone_total,
        difficulty=difficulty_total,
        plan_page_views=m.not_measured(PLAN_EVENT_MISSING),
        plan_sessions=m.not_measured(PLAN_EVENT_MISSING),
    )
