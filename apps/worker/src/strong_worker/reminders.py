"""Plan reminders by email (PS-6, ux-spec section 7). Rules in code, no model.

`plan_reminders` runs every hour. A user gets at most one reminder a day, sent at SEND_HOUR in
their time zone (UTC when they set none), only when:
- their plan style is weekly, `product_email` is on and `plan_email_muted` is off, and they are
  not suspended;
- it is Monday to Saturday (the weekly plan's days), and either an interview of a live role is
  3 days away with readiness below 75, or the plan has an open item, which the weekly plan always
  puts on today: an interview below 75, or a started Draft story.

The plan itself is built by the API (strong_api.plan.personal); the worker has no API code, so
these rules read the same data. Readiness is RH-2 (`readiness_score`); an API test checks it
matches the API's. Resume items are not reminded about here: their checks run in the API.

Each reminder is one `email_logs` row (kind plan_reminder, ref = the user's local date), so a
rerun never sends twice. The email comes from Strova (SV-9, strong_worker.strova_email).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import EmailLog, InterviewSession, JobTarget, TargetInterview, User
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.db.models import Story as StoryRow
from strong_core.email import Email, EmailSender, make_email_sender, send_email
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    READINESS_GOAL,
    Competency,
    CompetencyScore,
    CustomSessionSpec,
    EmailKind,
    InterviewType,
    Mode,
    PlanStyle,
)
from strong_worker.scoring.stories import DEV_PROFILES
from strong_worker.strova_email import strova_email

log = logging.getLogger(__name__)

CTX_KEY = "reminders"
SEND_HOUR = 8  # local time
COUNTDOWN_DAYS = 3
TAKES_COUNTED = 3
WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "http://localhost:5180").rstrip("/")
TYPE_NAME = {
    InterviewType.BEHAVIORAL: "Behavioral",
    InterviewType.HIRING_MANAGER: "Hiring manager",
    InterviewType.TECHNICAL_QA: "Technical Q&A",
    InterviewType.CASE: "Case",
    InterviewType.RECRUITER_SCREEN: "Recruiter screen",
    InterviewType.CUSTOM: "Custom",
}
PARTS = ("context", "stakes", "action", "result", "reflection")


@dataclass
class RemindersContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    sender: EmailSender


async def startup(ctx: dict[str, Any]) -> None:
    ctx[CTX_KEY] = RemindersContext(sessionmaker=get_sessionmaker(), sender=make_email_sender())


# --- RH-2 readiness, as the API computes it ---------------------------------------------------


def interview_competencies(row: TargetInterview) -> list[Competency]:
    if row.interview_type == InterviewType.CUSTOM:
        if not row.custom_json:
            return []
        return list(CustomSessionSpec.model_validate(row.custom_json).competencies())
    return list(COMPETENCIES_BY_TYPE.get(row.interview_type, ()))


def readiness_score(
    competencies: list[Competency], counted_newest_first: list[list[CompetencyScore]]
) -> int | None:
    """RH-2: the last three counted takes; the most recent score per competency; the mean on
    1 to 4 as 0 to 100."""
    latest: dict[Competency, int] = {}
    for scores in counted_newest_first[:TAKES_COUNTED]:
        for s in scores:
            if s.competency in competencies and s.competency not in latest:
                latest[s.competency] = s.score
    if not latest:
        return None
    mean = sum(latest.values()) / len(latest)
    return round((mean - 1) / 3 * 100)


async def _readiness(db: AsyncSession, row: TargetInterview) -> int | None:
    result = await db.execute(
        select(InterviewSession, ScorecardRow)
        .join(ScorecardRow, ScorecardRow.session_id == InterviewSession.id)
        .where(
            InterviewSession.org_id == row.org_id,
            InterviewSession.job_target_id == row.job_target_id,
            InterviewSession.resume_id == row.resume_id,
            InterviewSession.type == row.interview_type,
            InterviewSession.mode == Mode.REALISTIC,
            InterviewSession.model_profile.is_not(None),
        )
    )
    counted = sorted(
        (
            (s.started_at or s.created_at, str(s.id), card)
            for s, card in result.all()
            if s.model_profile not in DEV_PROFILES
        ),
        key=lambda t: (t[0], t[1]),
        reverse=True,
    )
    return readiness_score(
        interview_competencies(row),
        [
            [CompetencyScore.model_validate(c) for c in card.competency_scores_json]
            for *_, card in counted
        ],
    )


# --- the rules ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reminder:
    subject: str
    lines: list[str]
    action_label: str
    action_url: str


def local_now(user: User, now: datetime) -> datetime:
    try:
        zone = ZoneInfo(user.time_zone) if user.time_zone else UTC
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return now.astimezone(zone)


def wants_reminders(user: User) -> bool:
    """PS-6: weekly style, product email on, plan email not muted, not suspended."""
    return (
        user.plan_style == PlanStyle.WEEKLY
        and bool(user.product_email)
        and not user.plan_email_muted
        and user.suspended_at is None
    )


async def reminder_for(db: AsyncSession, user: User, today: date) -> Reminder | None:
    """What to remind the user of today, or None. The countdown comes first."""
    if today.weekday() == 6:
        return None  # the weekly plan runs Monday to Saturday
    targets = list(
        await db.scalars(
            select(JobTarget).where(
                JobTarget.org_id == user.org_id,
                JobTarget.user_id == user.id,
                JobTarget.deleted_at.is_(None),
                JobTarget.archived_at.is_(None),
            )
        )
    )
    below: list[tuple[date | None, str, int | None, uuid.UUID]] = []
    for target in targets:
        company = _company(target)
        rows = await db.scalars(
            select(TargetInterview)
            .where(
                TargetInterview.job_target_id == target.id, TargetInterview.archived_at.is_(None)
            )
            .order_by(TargetInterview.created_at, TargetInterview.id)
        )
        for row in rows:
            score = await _readiness(db, row)
            if score is None or score < READINESS_GOAL:
                name = f"{company} · {TYPE_NAME[row.interview_type]}"
                below.append((target.interview_date, name, score, row.id))
    countdown = [b for b in below if b[0] is not None and (b[0] - today).days == COUNTDOWN_DAYS]
    if countdown:
        _, name, score, iv = countdown[0]
        now = "not started yet" if score is None else f"{score} of 75"
        return Reminder(
            subject=f"Your {name.split(' · ')[0]} interview is in {COUNTDOWN_DAYS} days",
            lines=[
                f"Your {name} interview is in {COUNTDOWN_DAYS} days, and your readiness is {now}.",
                "A take today gives you time to work on what it finds.",
            ],
            action_label="Start a take",
            action_url=f"{WEB_BASE_URL}/interviews/{iv}",
        )
    if below:
        below.sort(key=lambda b: (b[0] is None, b[0] or date.max, -1 if b[2] is None else b[2]))
        _, name, score, iv = below[0]
        now = "Not started yet." if score is None else f"Readiness {score} of 75."
        return Reminder(
            subject=f"Today's plan: a take of {name}",
            lines=[
                f"Today's item in your plan is a take of {name}. {now}",
            ],
            action_label="Start the take",
            action_url=f"{WEB_BASE_URL}/interviews/{iv}",
        )
    drafts = [
        s
        for s in await db.scalars(
            select(StoryRow)
            .where(StoryRow.org_id == user.org_id, StoryRow.user_id == user.id)
            .order_by(StoryRow.created_at, StoryRow.id)
        )
        if 0 < sum(bool((getattr(s, p) or "").strip()) for p in PARTS) < len(PARTS)
    ]
    if drafts:
        story = drafts[0]
        filled = sum(bool((getattr(story, p) or "").strip()) for p in PARTS)
        return Reminder(
            subject=f"Today's plan: get “{story.title}” to Ready",
            lines=[
                f"Today's item in your plan is your story “{story.title}”: {filled} of 5 parts "
                "are written.",
            ],
            action_label="Open the story",
            action_url=f"{WEB_BASE_URL}/stories/{story.id}",
        )
    return None


def _company(target: JobTarget) -> str:
    posting = target.parsed_json or {}
    return str(posting.get("company_name") or target.name or "Your role")


def message(user: User, reminder: Reminder) -> Email:
    """SV-9: the reminder as an email from Strova."""
    first = (user.full_name or "").split(" ")[0] or "there"
    return strova_email(
        user.email,
        reminder.subject,
        [f"Hi {first},", *reminder.lines],
        action_label=reminder.action_label,
        action_url=reminder.action_url,
        footer="You get this because your plan is weekly. Mute plan emails in Profile: "
        f"{WEB_BASE_URL}/account/profile",
    )


async def send_reminders(
    sessionmaker: async_sessionmaker[AsyncSession], sender: EmailSender, now: datetime
) -> dict[str, int]:
    sent = skipped = 0
    async with sessionmaker() as db:
        users = list(
            await db.scalars(
                select(User).where(
                    User.plan_style == PlanStyle.WEEKLY,
                    User.product_email.is_(True),
                    User.plan_email_muted.is_(False),
                    User.suspended_at.is_(None),
                )
            )
        )
        for user in users:
            if not wants_reminders(user):
                continue
            local = local_now(user, now)
            if local.hour != SEND_HOUR:
                continue
            ref = local.date().isoformat()
            already = await db.scalar(
                select(EmailLog.id).where(
                    EmailLog.user_id == user.id,
                    EmailLog.kind == EmailKind.PLAN_REMINDER,
                    EmailLog.ref == ref,
                )
            )
            if already is not None:
                skipped += 1
                continue
            reminder = await reminder_for(db, user, local.date())
            if reminder is None:
                continue
            db.add(
                EmailLog(org_id=user.org_id, user_id=user.id, kind=EmailKind.PLAN_REMINDER, ref=ref)
            )
            await db.commit()  # logged first: a failed send is not retried into a double email
            try:
                await send_email(sender, message(user, reminder))
                sent += 1
            except Exception:
                log.exception("plan reminder to user %s failed", user.id)
    return {"sent": sent, "already_sent": skipped}


async def plan_reminders(ctx: dict[str, Any]) -> dict[str, int]:
    """PS-6: the hourly reminder pass."""
    value = ctx[CTX_KEY]
    assert isinstance(value, RemindersContext)
    return await send_reminders(value.sessionmaker, value.sender, datetime.now(UTC))
