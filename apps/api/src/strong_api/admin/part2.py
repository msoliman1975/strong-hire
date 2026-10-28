"""Admin Part 2 story library metrics (AD-4): is the story library working, without reading it.

    GET /admin/part2/stories?weeks=8   story save rate (the v2 launch gate: 40% of users save a
                                       story within 30 days of their first debrief), stories per
                                       user, the Draft to Proven rate, and delivery metric
                                       trends (DM-1) per UTC week (Monday start)

Aggregate only. No story text, title, note or skill list is selected here, and no answer text
from the scorecards: only counts, statuses, timestamps and the numeric delivery fields. A test
checks that no admin endpoint returns story text.

A user is an org: every candidate org has one user, and stories, sessions and scorecards all
carry org_id.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from strong_api.admin import metrics as m
from strong_api.admin.deps import Admin
from strong_api.admin.part1 import week_start
from strong_api.auth.deps import DbSession
from strong_core.db.models import Scorecard, Story
from strong_core.schemas.enums import StorySource, StoryStatus

router = APIRouter(prefix="/admin", tags=["admin"])

SAVE_WINDOW = timedelta(days=30)
SAVE_RATE_TARGET = 0.40  # spec: v2 launch gate

SAVE_RATE_NOTE = (
    "Users whose first debrief is at least 30 days old, and the share of them who saved a story "
    "by 30 days after it."
)
SAVE_RATE_EMPTY = "No user has a first debrief 30 or more days ago yet."
PER_USER_NOTE = "Stories per user who saved at least one."
PROVEN_NOTE = "Proven stories as a share of all stories (ST-7)."


class StoryCounts(BaseModel):
    total: int
    draft: int
    proven: int
    by_source: dict[StorySource, int] = Field(description="Stories per source; every source")
    users_with_stories: int


class SaveCohort(BaseModel):
    users: int = Field(description="Users whose first debrief is 30 or more days old")
    saved: int = Field(description="Of them, users who saved a story within the 30 days")


class DeliveryWeek(BaseModel):
    week_start: datetime = Field(description="Monday 00:00 UTC")
    answers: int = Field(description="Scored answers with delivery metrics")
    words_per_minute: float | None = Field(description="Mean over those answers")
    fillers_per_minute: float | None
    duration_seconds: float | None


class StoryWeek(BaseModel):
    week_start: datetime = Field(description="Monday 00:00 UTC")
    saved: int = Field(description="Stories created that week")


class Part2Stories(BaseModel):
    story_save_rate: m.AdminMetric
    stories_per_user: m.AdminMetric
    draft_to_proven_rate: m.AdminMetric
    save_cohort: SaveCohort
    counts: StoryCounts
    stories_by_week: list[StoryWeek] = Field(description="Oldest first; the last is this week")
    delivery: list[DeliveryWeek] = Field(description="Oldest first; the last is this week")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def delivery_values(per_question: Any) -> list[tuple[float, float, float]]:
    """The (wpm, fillers per minute, seconds) of each answer that has delivery metrics.

    Reads only the numeric `delivery` field of each QuestionScore, never the answer's text."""
    out: list[tuple[float, float, float]] = []
    if not isinstance(per_question, list):
        return out
    for item in per_question:
        delivery = item.get("delivery") if isinstance(item, dict) else None
        if not isinstance(delivery, dict):
            continue
        wpm = _number(delivery.get("words_per_minute"))
        fpm = _number(delivery.get("fillers_per_minute"))
        secs = _number(delivery.get("duration_seconds"))
        if wpm is None or fpm is None or secs is None:
            continue
        out.append((wpm, fpm, secs))
    return out


def _utc(at: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


@router.get("/part2/stories")
async def get_part2_stories(
    _: Admin,
    db: DbSession,
    weeks: Annotated[int, Query(ge=1, le=52, description="How many weeks, this one included")] = 8,
) -> Part2Stories:
    """AD-4: story save rate, stories per user, Draft to Proven rate, delivery trends."""
    now = m.now_utc()
    first = week_start(now) - timedelta(weeks=weeks - 1)
    starts = [first + timedelta(weeks=i) for i in range(weeks)]

    # Counts by status and source, and stories per org: no text columns.
    by_status: dict[StoryStatus, int] = dict.fromkeys(StoryStatus, 0)
    by_source: dict[StorySource, int] = dict.fromkeys(StorySource, 0)
    rows = await db.execute(
        select(Story.status, Story.source, func.count()).group_by(Story.status, Story.source)
    )
    for status, source, count in rows:
        by_status[StoryStatus(status)] += int(count)
        by_source[StorySource(source)] += int(count)
    total = sum(by_status.values())

    # Each org's first story, and its first debrief (first scorecard).
    first_story: dict[uuid.UUID, datetime] = {
        org: _utc(at)
        for org, at in await db.execute(
            select(Story.org_id, func.min(Story.created_at)).group_by(Story.org_id)
        )
        if at is not None
    }
    first_debrief: dict[uuid.UUID, datetime] = {
        org: _utc(at)
        for org, at in await db.execute(
            select(Scorecard.org_id, func.min(Scorecard.created_at)).group_by(Scorecard.org_id)
        )
        if at is not None
    }

    # Save rate cohort: the first debrief at least 30 days ago, so the window is complete. A
    # story saved before the first debrief (written by hand) counts as saved.
    cohort = [org for org, at in first_debrief.items() if at + SAVE_WINDOW <= now]
    saved = sum(
        1
        for org in cohort
        if org in first_story and first_story[org] <= first_debrief[org] + SAVE_WINDOW
    )
    if cohort:
        save_rate = m.AdminMetric(
            value=m.ratio(saved, len(cohort)),
            unit="pct",
            target=SAVE_RATE_TARGET,
            note=SAVE_RATE_NOTE,
        )
    else:
        save_rate = m.not_measured(SAVE_RATE_EMPTY, unit="pct")

    users_with = len(first_story)
    per_user = m.AdminMetric(value=m.ratio(total, users_with), unit="ratio", note=PER_USER_NOTE)
    proven = m.AdminMetric(
        value=m.ratio(by_status[StoryStatus.PROVEN], total), unit="pct", note=PROVEN_NOTE
    )

    # Stories saved per week.
    saved_by_week = {int(s.timestamp()): 0 for s in starts}
    for (created,) in await db.execute(select(Story.created_at).where(Story.created_at >= first)):
        key = int(week_start(_utc(created)).timestamp())
        if key in saved_by_week:
            saved_by_week[key] += 1

    # Delivery trends: the numeric delivery fields of the scorecards in the weeks shown.
    buckets: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    cards = await db.execute(
        select(Scorecard.created_at, Scorecard.per_question_json).where(
            Scorecard.created_at >= first
        )
    )
    for created, per_question in cards:
        key = int(week_start(_utc(created)).timestamp())
        buckets[key].extend(delivery_values(per_question))
    delivery = []
    for s in starts:
        values = buckets.get(int(s.timestamp()), [])
        delivery.append(
            DeliveryWeek(
                week_start=s,
                answers=len(values),
                words_per_minute=_mean([v[0] for v in values]),
                fillers_per_minute=_mean([v[1] for v in values]),
                duration_seconds=_mean([v[2] for v in values]),
            )
        )

    return Part2Stories(
        story_save_rate=save_rate,
        stories_per_user=per_user,
        draft_to_proven_rate=proven,
        save_cohort=SaveCohort(users=len(cohort), saved=saved),
        counts=StoryCounts(
            total=total,
            draft=by_status[StoryStatus.DRAFT],
            proven=by_status[StoryStatus.PROVEN],
            by_source=by_source,
            users_with_stories=users_with,
        ),
        stories_by_week=[
            StoryWeek(week_start=s, saved=saved_by_week[int(s.timestamp())]) for s in starts
        ],
        delivery=delivery,
    )
