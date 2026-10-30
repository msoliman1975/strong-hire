"""PS-6: weekly-plan reminders by email. Who gets them (weekly style, product_email on, plan
email not muted), when (08:00 local, Monday to Saturday, at most one a day), and what about (an
interview 3 days away below 75, else today's open item)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import EmailLog, JobTarget, TargetInterview, User
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Story as StoryRow
from strong_core.email import Email
from strong_core.schemas import (
    Competency,
    CompetencyScore,
    EmailKind,
    InterviewType,
    PlanStyle,
    StorySource,
)
from strong_worker.main import WorkerSettings
from strong_worker.reminders import readiness_score, send_reminders

Maker = async_sessionmaker[AsyncSession]
# Wednesday 2026-10-28, 08:30 UTC.
WEDNESDAY_8 = datetime(2026, 10, 28, 8, 30, tzinfo=UTC)


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, text: str) -> None:
        self.sent.append((to, subject, text))


async def _user(maker: Maker, user_id: uuid.UUID, **fields: object) -> None:
    async with maker() as db:
        user = await db.get(User, user_id)
        assert user is not None
        defaults: dict[str, object] = {
            "plan_style": PlanStyle.WEEKLY,
            "product_email": True,
            "plan_email_muted": False,
            "full_name": "Ana Lopez",
        }
        for k, v in {**defaults, **fields}.items():
            setattr(user, k, v)
        await db.commit()


async def _interview(
    maker: Maker, org_id: uuid.UUID, user_id: uuid.UUID, interview_date: date | None
) -> uuid.UUID:
    async with maker() as db:
        resume = ResumeRow(org_id=org_id, user_id=user_id)
        target = JobTarget(
            org_id=org_id,
            user_id=user_id,
            parsed_json={"company_name": "Stripe", "title": "Senior engineer"},
            interview_date=interview_date,
        )
        db.add_all([resume, target])
        await db.flush()
        row = TargetInterview(
            org_id=org_id,
            user_id=user_id,
            job_target_id=target.id,
            resume_id=resume.id,
            interview_type=InterviewType.BEHAVIORAL,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _draft(maker: Maker, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with maker() as db:
        db.add(
            StoryRow(
                org_id=org_id,
                user_id=user_id,
                title="Pushback from platform",
                context="The platform team refused.",
                action="We talked it out.",
                skills=[],
                notes_json=[],
                source=StorySource.MANUAL,
            )
        )
        await db.commit()


async def test_ps6_today_item_is_sent_once_a_day_at_8_local(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """PS-6: a weekly-style user with an open item gets one email at 08:00 local, logged once."""
    org_id, user_id = account
    await _user(sessionmaker, user_id)
    iv = await _interview(sessionmaker, org_id, user_id, None)
    sender = Sender()
    assert await send_reminders(sessionmaker, sender, WEDNESDAY_8) == {"sent": 1, "already_sent": 0}
    ((to, subject, text),) = sender.sent
    assert to == "user@example.com"
    assert subject == "Today's plan: a take of Stripe · Behavioral"
    assert f"/interviews/{iv}" in text and text.startswith("Hi Ana,")
    assert "Mute plan emails in Profile" in text
    # A second pass the same day sends nothing more.
    assert await send_reminders(sessionmaker, sender, WEDNESDAY_8 + timedelta(minutes=20)) == {
        "sent": 0,
        "already_sent": 1,
    }
    async with sessionmaker() as db:
        logs = list(await db.scalars(select(EmailLog)))
    assert [(log.kind, log.ref) for log in logs] == [(EmailKind.PLAN_REMINDER, "2026-10-28")]
    # Other hours send nothing; the next day sends again.
    assert (await send_reminders(sessionmaker, sender, WEDNESDAY_8 + timedelta(hours=3)))[
        "sent"
    ] == 0
    assert (await send_reminders(sessionmaker, sender, WEDNESDAY_8 + timedelta(days=1)))[
        "sent"
    ] == 1


async def test_ps6_respects_product_email_the_mute_and_the_style(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    await _interview(sessionmaker, org_id, user_id, None)
    for fields in (
        {"product_email": False},
        {"plan_email_muted": True},
        {"plan_style": PlanStyle.CHECKLIST},
        {"plan_style": None},
        {"suspended_at": datetime(2026, 10, 1, tzinfo=UTC)},
    ):
        await _user(sessionmaker, user_id, **fields)
        sender = Sender()
        await send_reminders(sessionmaker, sender, WEDNESDAY_8)
        assert sender.sent == [], fields
        await _user(sessionmaker, user_id, suspended_at=None)


async def test_ps6_uses_the_users_time_zone_and_skips_sunday(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    await _user(sessionmaker, user_id, time_zone="America/New_York")
    await _interview(sessionmaker, org_id, user_id, None)
    sender = Sender()
    await send_reminders(sessionmaker, sender, WEDNESDAY_8)  # 04:30 in New York
    assert sender.sent == []
    await send_reminders(sessionmaker, sender, datetime(2026, 10, 28, 12, 30, tzinfo=UTC))
    assert len(sender.sent) == 1
    sunday = datetime(2026, 11, 1, 13, 30, tzinfo=UTC)  # 08:30 in New York
    await send_reminders(sessionmaker, sender, sunday)
    assert len(sender.sent) == 1


async def test_ps6_an_interview_3_days_away_below_75_comes_first(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    await _user(sessionmaker, user_id)
    await _draft(sessionmaker, org_id, user_id)
    iv = await _interview(sessionmaker, org_id, user_id, date(2026, 10, 31))
    sender = Sender()
    await send_reminders(sessionmaker, sender, WEDNESDAY_8)
    ((_, subject, text),) = sender.sent
    assert subject == "Your Stripe interview is in 3 days"
    assert "your readiness is not started yet" in text and f"/interviews/{iv}" in text


async def test_ps6_a_started_draft_is_todays_item_without_interviews(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    await _user(sessionmaker, user_id)
    await _draft(sessionmaker, org_id, user_id)
    sender = Sender()
    await send_reminders(sessionmaker, sender, WEDNESDAY_8)
    ((_, subject, text),) = sender.sent
    assert subject == "Today's plan: get “Pushback from platform” to Ready"
    assert "2 of 5 parts" in text


async def test_ps6_nothing_open_means_no_email(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _, user_id = account
    await _user(sessionmaker, user_id)
    sender = Sender()
    assert await send_reminders(sessionmaker, sender, WEDNESDAY_8) == {"sent": 0, "already_sent": 0}


def test_ps6_readiness_is_rh2() -> None:
    def scores(**s: int) -> list[CompetencyScore]:
        return [
            CompetencyScore(competency=c, score=v, justification="j", quotes=["q"])  # type: ignore[arg-type]
            for c, v in s.items()
        ]

    own = [Competency.OWNERSHIP, Competency.IMPACT]
    assert readiness_score(own, []) is None
    # The most recent score per competency, mean 3.5 on 1..4 -> 83.
    assert readiness_score(own, [scores(ownership=4), scores(ownership=1, impact=3)]) == 83


def test_ps6_reminder_job_is_registered() -> None:
    names = {getattr(j, "name", "") for j in WorkerSettings.cron_jobs}
    assert any("plan_reminders" in n for n in names)


class RichSender(Sender):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[Email] = []

    async def send_message(self, email: Email) -> None:
        self.messages.append(email)


async def test_sv9_the_reminder_comes_from_strova_with_her_avatar_beside_the_logo(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SV-9: the plan reminder is sent as "Strova from Strong Hire", with an HTML part that shows
    the 64 px coaching avatar (alt "Strova") beside the Strong Hire logo, as inline images."""
    org_id, user_id = account
    await _user(sessionmaker, user_id)
    await _interview(sessionmaker, org_id, user_id, None)
    sender = RichSender()
    assert (await send_reminders(sessionmaker, sender, WEDNESDAY_8))["sent"] == 1
    assert sender.sent == []  # the rich path, not the plain text
    (email,) = sender.messages
    assert email.from_name == "Strova from Strong Hire"
    assert email.html is not None
    assert '<img src="cid:strova" alt="Strova" width="64" height="64">' in email.html
    assert email.html.index('alt="Strong Hire"') < email.html.index('alt="Strova"')
    images = {i.cid: i.data for i in email.images}
    assert set(images) == {"strova", "strong-hire"}
    assert images["strova"][:8] == b"\x89PNG\r\n\x1a\n"
    assert "Start the take" in email.html and "Start the take: http" in email.text
