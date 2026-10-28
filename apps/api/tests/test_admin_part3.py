"""Admin portal, Part 3 (v2 S38): coach, readiness by skill, recruiter screen setup (AD-5).

The clock is fixed at NOW, Wednesday 2030-03-13 12:00 UTC, so the current week starts Monday
2030-03-11. Coach turns, takes, stories and score justifications hold SECRET, and no admin
response may contain it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.admin import metrics, part3
from strong_api.admin.part3 import coach_evals, competency_scores
from strong_api.auth.settings import get_auth_settings
from strong_api.main import create_app
from strong_core import runtime_settings as rs
from strong_core.config import get_settings
from strong_core.db.models import (
    CoachSession,
    CoachTurn,
    InterviewSession,
    JobTarget,
    Org,
    Scorecard,
    Story,
    Subscription,
    Take,
    UsageEvent,
    User,
)
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
from strong_core.prompts import load_prompt
from strong_core.schemas import AuthProvider, Difficulty, InterviewType, Mode, SessionStatus
from strong_core.schemas.enums import (
    CoachSpeaker,
    CoachStyle,
    HireSignal,
    SessionChannel,
    StorySource,
    StoryStatus,
    SubscriptionStatus,
    UsageComponent,
)

from .accounts_support import sign_up
from .conftest import InlineQueue, sign_in_admin

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
SIM = "sim@getstronghire.com"
NOW = datetime(2030, 3, 13, 12, 0, tzinfo=UTC)
SECRET = "SECRET-COACH-TEXT"
BRIEF_FIXTURE = DEFAULT_FIXTURES_DIR / "planner" / "InterviewerBrief.json"
RUBRIC_REF = "scorer/rubric_recruiter_screen.v1"


async def _ok() -> None:
    return None


@pytest.fixture
def reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "reports"
    folder.mkdir()
    monkeypatch.setattr(part3, "eval_reports_dir", lambda: folder)
    return folder


@pytest.fixture
def app(
    sessionmaker: Maker,
    queue: InlineQueue,
    monkeypatch: pytest.MonkeyPatch,
    reports: Path,
    tmp_path: Path,
) -> Iterator[FastAPI]:
    monkeypatch.setattr(metrics, "now_utc", lambda: NOW)
    monkeypatch.setenv("SIM_ENABLED", "true")
    monkeypatch.setenv("SIM_TOKEN", "s" * 40)
    monkeypatch.setenv("SIM_RESULTS_DIR", str(tmp_path / "sim"))
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    rs.clear_cache()
    yield create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    rs.clear_cache()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # Errors come back as 500 responses, so the route sweep sees every body.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in_admin(http, app, ADMIN)
        yield http


@pytest.fixture
async def candidate(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


# ---------------------------------------------------------------- seed helpers


async def _user(db: AsyncSession, email: str, consent: bool = True) -> User:
    org = Org(name=email)
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id, email=email, auth_provider=AuthProvider.DEV, training_consent=consent
    )
    db.add(user)
    await db.flush()
    return user


def _score(competency: str, score: int) -> dict[str, Any]:
    return {
        "competency": competency,
        "score": score,
        "justification": f"{SECRET} why",
        "quotes": [f"{SECRET} quote"],
    }


def recruiter_brief() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(BRIEF_FIXTURE.read_text(encoding="utf-8"))
    data["session"]["interview_type"] = "recruiter_screen"
    return data


async def _session(
    db: AsyncSession,
    user: User,
    at: datetime,
    scores: list[dict[str, Any]] | None,
    *,
    kind: InterviewType = InterviewType.BEHAVIORAL,
    mode: Mode = Mode.REALISTIC,
    profile: str | None = "hosted",
    brief: dict[str, Any] | None = None,
    rubric: str = "scorer/rubric.v2",
) -> InterviewSession:
    """A completed session; with a scorecard when `scores` is not None."""
    job = JobTarget(org_id=user.org_id, user_id=user.id, raw_text="Engineer")
    db.add(job)
    await db.flush()
    session = InterviewSession(
        org_id=user.org_id,
        job_target_id=job.id,
        type=kind,
        difficulty=Difficulty.REALISTIC,
        mode=mode,
        duration_min=30,
        status=SessionStatus.COMPLETED if scores is not None else SessionStatus.CREATED,
        model_profile=profile,
        brief_json=brief,
        created_at=at,
    )
    db.add(session)
    await db.flush()
    if scores is not None:
        db.add(
            Scorecard(
                org_id=user.org_id,
                session_id=session.id,
                hire_signal=HireSignal.LEAN_HIRE,
                rationale="Solid.",
                competency_scores_json=scores,
                per_question_json=[],
                scorer_model="fake",
                rubric_version=rubric,
                created_at=at,
            )
        )
        await db.flush()
    return session


async def _coach(
    db: AsyncSession,
    user: User,
    at: datetime,
    minutes: int,
    channel: SessionChannel = SessionChannel.TEXT,
    style: CoachStyle = CoachStyle.GENTLE,
) -> CoachSession:
    story = Story(
        org_id=user.org_id,
        user_id=user.id,
        title=f"{SECRET} title",
        context=f"{SECRET} context",
        skills=["ownership"],
        status=StoryStatus.DRAFT,
        source=StorySource.COACH,
        created_at=at,
        updated_at=at,
    )
    db.add(story)
    await db.flush()
    row = CoachSession(
        org_id=user.org_id,
        user_id=user.id,
        story_id=story.id,
        style=style,
        channel=channel,
        minutes=minutes,
        model_profile="hosted",
        created_at=at,
    )
    db.add(row)
    await db.flush()
    for seq, speaker in enumerate((CoachSpeaker.COACH, CoachSpeaker.CANDIDATE), start=1):
        db.add(
            CoachTurn(
                org_id=user.org_id,
                coach_session_id=row.id,
                seq=seq,
                speaker=speaker,
                text=f"{SECRET} turn {seq}",
                start_ms=0,
                end_ms=1000,
            )
        )
    db.add(
        Take(
            org_id=user.org_id,
            user_id=user.id,
            story_id=story.id,
            channel=channel,
            text=f"{SECRET} take",
            duration_s=40.0,
        )
    )
    return row


def _usage(
    org: uuid.UUID, role: str, cost: str, at: datetime, session: uuid.UUID | None = None
) -> UsageEvent:
    component = {"stt": UsageComponent.STT, "tts": UsageComponent.TTS}.get(role, UsageComponent.LLM)
    return UsageEvent(
        org_id=org,
        session_id=session,
        component=component,
        units=Decimal(1),
        cost_usd=Decimal(cost),
        role=role,
        created_at=at,
    )


async def _seed(maker: Maker) -> dict[str, uuid.UUID]:
    """- ana: paid (cap 100, 90 used, period from 10 days ago), three coach sessions (19 minutes
      in her period), Realistic scores, a recruiter screen session with a brief and a scorecard
    - bo: free, one coach session (3 minutes), one Realistic score
    - cy: only a Coach-mode session and a tiny-profile one (both left out of readiness)
    """
    async with maker() as db:
        ana = await _user(db, "ana@example.com")
        db.add(
            Subscription(
                org_id=ana.org_id,
                user_id=ana.id,
                status=SubscriptionStatus.ACTIVE,
                period_start=NOW - timedelta(days=10),
                period_end=NOW + timedelta(days=20),
                minutes_cap=100,
                minutes_used=90,
            )
        )
        await _coach(db, ana, NOW - timedelta(hours=3), 10)
        await _coach(db, ana, NOW - timedelta(days=1), 5, SessionChannel.VOICE, CoachStyle.DIRECT)
        await _coach(db, ana, NOW - timedelta(days=8), 4)
        await _session(
            db, ana, NOW - timedelta(days=20), [_score("ownership", 3), _score("impact", 2)]
        )
        interview = await _session(
            db, ana, NOW - timedelta(days=5), [_score("ownership", 4), _score("impact", 2)]
        )
        recruiter = await _session(
            db,
            ana,
            NOW - timedelta(days=2),
            [_score("motivation", 3)],
            kind=InterviewType.RECRUITER_SCREEN,
            brief=recruiter_brief(),
            rubric=RUBRIC_REF,
        )
        pending = await _session(
            db, ana, NOW, None, kind=InterviewType.RECRUITER_SCREEN, brief=recruiter_brief()
        )

        bo = await _user(db, "bo@example.com")
        await _coach(db, bo, NOW - timedelta(days=2), 3)
        await _session(db, bo, NOW - timedelta(days=3), [_score("ownership", 2)])

        cy = await _user(db, "cy@example.com")
        await _session(db, cy, NOW - timedelta(days=3), [_score("ownership", 1)], mode=Mode.COACH)
        await _session(db, cy, NOW - timedelta(days=3), [_score("ownership", 1)], profile="tiny")
        await _session(db, cy, NOW - timedelta(days=200), [_score("ownership", 1)])

        db.add_all(
            [
                _usage(ana.org_id, "coach", "0.30", NOW - timedelta(days=1)),
                _usage(ana.org_id, "stt", "0.10", NOW - timedelta(days=1)),  # the voice coach
                _usage(ana.org_id, "interviewer", "5.00", NOW, interview.id),  # an interview
                _usage(ana.org_id, "stt", "1.00", NOW, interview.id),
                _usage(ana.org_id, "coach", "9.00", NOW - timedelta(weeks=60)),  # too old
            ]
        )
        await db.commit()
        return {
            "user": ana.id,
            "org": ana.org_id,
            "session": recruiter.id,
            "pending": pending.id,
        }


def _report(folder: Path, name: str, profile: str, started: str, passed: bool) -> None:
    data = {
        "suite": "coach",
        "profile": profile,
        "started_at": started,
        "git_sha": "abc123",
        "metrics": [
            {
                "key": "coach_invented_facts",
                "name": "Invented facts",
                "value": 0 if passed else 2,
                "threshold": "= 0",
                "passed": passed,
                "detail": f"{SECRET} detail",
                "source": "code",
            },
            {
                "key": "coach_cost_per_session_usd",
                "name": "Cost per session",
                "value": 0.04,
                "threshold": "info",
                "passed": None,
            },
            {"key": "scorer_agreement", "name": "Other suite", "value": 0.9, "passed": True},
        ],
        "coach": [{"steps": [{"candidate": f"{SECRET} said", "coach": f"{SECRET} asked"}]}],
    }
    (folder / name).write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------- AD-5 coach


async def test_ad5_coach_sessions_minutes_and_cost(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AD-5: coach sessions and minutes per week, and cost per coach session from usage events
    with role coach (plus the voice coach's STT and TTS events, which have no session)."""
    await _seed(sessionmaker)
    resp = await admin.get("/admin/part3/coach", params={"weeks": 8})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["sessions"] == 4 and body["minutes"] == 22 and body["users"] == 2
    assert body["by_style"] == {"gentle": 3, "direct": 1}
    assert body["by_channel"] == {"voice": 1, "text": 3}
    assert body["minutes_per_session"]["value"] == pytest.approx(5.5)

    weeks = body["weeks"]
    assert len(weeks) == 8 and weeks[-1]["week_start"].startswith("2030-03-11")
    assert weeks[-1] == {
        "week_start": weeks[-1]["week_start"],
        "sessions": 3,
        "minutes": 18,
        "voice": 1,
        "text": 2,
        "users": 2,
    }
    assert weeks[-2]["sessions"] == 1 and weeks[-2]["minutes"] == 4

    # 0.30 coach + 0.10 voice coach STT; the interview's events and the old one are left out.
    assert body["cost_total_usd"] == pytest.approx(0.40)
    cost = body["cost_per_session"]
    assert cost["measured"] is True and cost["unit"] == "usd"
    assert cost["value"] == pytest.approx(0.10)


async def test_ad5_coach_minutes_against_plan_caps(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AD-5: coach minutes in each paid user's plan period against the plan cap. Coach minutes do
    not use plan minutes; the page shows who would pass the cap if they did."""
    await _seed(sessionmaker)
    body = (await admin.get("/admin/part3/coach")).json()
    assert body["caps"] == {
        "paid_users": 1,
        "coach_minutes": 19,
        "interview_minutes": 90,
        "cap_minutes": 100,
        "over_cap_if_counted": 1,
        "free_user_coach_minutes": 3,
    }
    assert body["cap_share"]["value"] == pytest.approx(0.19)


async def test_ad5_coach_page_empty_is_not_measured(admin: httpx.AsyncClient) -> None:
    """AO-8 via AD-5: no coach session, no paid user and no eval report: "not measured" with a
    reason, never a made-up zero."""
    body = (await admin.get("/admin/part3/coach")).json()
    assert body["sessions"] == 0
    assert body["cost_per_session"]["measured"] is False and body["cost_per_session"]["reason"]
    assert body["cap_share"]["measured"] is False
    assert body["evals"] == {"latest": None, "runs": [], "reason": part3.EVAL_EMPTY}


async def test_ad5_coach_eval_results_from_reports(admin: httpx.AsyncClient, reports: Path) -> None:
    """AD-5, CO-9: the latest coach eval results, a hosted run before a newer fake one, coach
    metrics only, and none of the report's conversation text."""
    _report(reports, "coach-hosted-1.json", "hosted", "2030-03-10T10:00:00+00:00", True)
    _report(reports, "coach-fake-2.json", "fake", "2030-03-12T10:00:00+00:00", False)
    (reports / "broken.json").write_text("{not json", encoding="utf-8")
    (reports / "gap-hosted.json").write_text(
        json.dumps({"suite": "gap", "metrics": [{"key": "gap_spread", "value": 1}]}),
        encoding="utf-8",
    )
    resp = await admin.get("/admin/part3/coach")
    assert SECRET not in resp.text
    evals = resp.json()["evals"]
    assert [r["file"] for r in evals["runs"]] == ["coach-fake-2.json", "coach-hosted-1.json"]
    latest = evals["latest"]
    assert latest["profile"] == "hosted" and latest["dev_data"] is False
    assert latest["passed"] is True
    assert [x["key"] for x in latest["metrics"]] == [
        "coach_invented_facts",
        "coach_cost_per_session_usd",
    ]
    assert evals["runs"][0]["dev_data"] is True and evals["runs"][0]["passed"] is False


def test_ad5_coach_evals_missing_folder(tmp_path: Path) -> None:
    result = coach_evals(tmp_path / "nowhere")
    assert result.latest is None and result.reason


# ---------------------------------------------------------------- AD-5 readiness


async def test_ad5_readiness_by_skill_aggregate(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AD-5, RD-1: readiness by skill across users from Realistic sessions only, without dev
    data or old sessions, labeled a practice estimate (RD-3)."""
    await _seed(sessionmaker)
    resp = await admin.get("/admin/part3/readiness")
    assert resp.status_code == 200, resp.text
    assert SECRET not in resp.text
    body = resp.json()
    assert body["kind"] == "practice_estimate" and "Practice estimate" in body["note"]
    assert body["users"] == 2  # ana and bo; cy's sessions are all left out
    skills = {s["competency"]: s for s in body["skills"]}
    assert set(skills) == {"ownership", "impact", "motivation"}
    assert skills["motivation"]["users_enough_data"] == 0  # one recruiter screen
    assert skills["motivation"]["mean_score"] is None
    assert skills["ownership"] == {
        "competency": "ownership",
        "users": 2,
        "users_enough_data": 1,  # bo has one session
        "users_at_bar": 1,  # ana: (3 + 4) / 2
        "mean_score": 3.5,
        "sessions": 3,
    }
    assert skills["impact"]["users_at_bar"] == 0 and skills["impact"]["mean_score"] == 2.0
    assert body["skills"][0]["competency"] == "ownership"  # most users first


def test_ad5_competency_scores_read_only_numbers() -> None:
    raw = [
        _score("ownership", 3),
        {"competency": "nope", "score": 3},
        {"competency": "impact", "score": 9},
        {"competency": "impact", "score": True},
        "junk",
    ]
    assert [(c.value, s) for c, s in competency_scores(raw)] == [("ownership", 3)]
    assert competency_scores(None) == []


async def test_ad5_part3_is_admin_only(candidate: httpx.AsyncClient) -> None:
    for path in ("/admin/part3/coach", "/admin/part3/readiness"):
        assert (await candidate.get(path)).status_code == 404
    await sign_up(candidate)
    for path in ("/admin/part3/coach", "/admin/part3/readiness"):
        assert (await candidate.get(path)).status_code == 404


# ---------------------------------------------------------------- AD-5 recruiter screen


async def test_ad5_recruiter_screen_brief_and_rubric_on_session_page(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AD-5, RS-2: the session page shows a recruiter screen's brief and the rubric its
    scorecard used. The rubric always; the brief only while the user's consent is on."""
    ids = await _seed(sessionmaker)
    detail = (await admin.get(f"/admin/sessions/{ids['session']}")).json()
    setup = detail["setup"]
    assert setup["brief"]["session"]["interview_type"] == "recruiter_screen"
    assert setup["brief"]["questions"]
    rubric = setup["rubric"]
    expected = load_prompt("scorer", "rubric_recruiter_screen", 1, tier=None).text
    assert rubric == {"ref": RUBRIC_REF, "text": expected, "scored": True}

    # Not scored yet: the current recruiter screen rubric.
    pending = (await admin.get(f"/admin/sessions/{ids['pending']}")).json()["setup"]
    assert pending["rubric"]["ref"].startswith("scorer/rubric_recruiter_screen.v")
    assert pending["rubric"]["scored"] is False

    async with sessionmaker() as db:
        user = await db.get(User, ids["user"])
        assert user is not None
        user.training_consent = False
        await db.commit()
    hidden = (await admin.get(f"/admin/sessions/{ids['session']}")).json()
    assert hidden["content_visible"] is False
    assert hidden["setup"]["brief"] is None
    assert hidden["setup"]["rubric"]["ref"] == RUBRIC_REF


async def test_ad5_recruiter_screen_brief_and_rubric_on_replay(
    app: FastAPI, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AD-5: the replay page of an AI candidate's recruiter screen shows the same setup."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as sim:
        resp = await sim.post("/auth/sim-login", headers={"X-Sim-Token": "s" * 40})
        assert resp.status_code == 204
    async with sessionmaker() as db:
        user = await db.scalar(select(User).where(User.email == SIM))
        assert user is not None
        session = await _session(
            db,
            user,
            NOW,
            [_score("motivation", 3)],
            kind=InterviewType.RECRUITER_SCREEN,
            brief=recruiter_brief(),
            rubric=RUBRIC_REF,
        )
        await db.commit()
        sid = session.id
    replay = (await admin.get(f"/admin/sessions/{sid}/replay")).json()
    assert replay["setup"]["brief"]["session"]["interview_type"] == "recruiter_screen"
    assert replay["setup"]["rubric"]["ref"] == RUBRIC_REF


# ---------------------------------------------------------------- the no-text rule


def _fill(path: str, ids: dict[str, uuid.UUID]) -> str:
    known = {"user_id": ids["user"], "session_id": ids["session"], "org_id": ids["org"]}
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        name = out[start + 1 : end].split(":")[0]
        out = out[:start] + str(known.get(name, uuid.uuid4())) + out[end + 1 :]
    return out


async def test_ad5_no_admin_endpoint_returns_coach_or_story_text(
    app: FastAPI, admin: httpx.AsyncClient, sessionmaker: Maker, reports: Path
) -> None:
    """AD-5: every admin GET route, with the seeded user and session filled in, returns no coach
    turn, take, story or score justification text, even with training consent on."""
    ids = await _seed(sessionmaker)
    _report(reports, "coach-hosted-1.json", "hosted", "2030-03-10T10:00:00+00:00", True)
    paths = sorted(
        {
            _fill(path, ids)
            for path, ops in app.openapi()["paths"].items()
            if path.startswith("/admin/") and not path.startswith("/admin/auth/") and "get" in ops
        }
    )
    assert {"/admin/part3/coach", "/admin/part3/readiness"} <= set(paths)
    ok: set[str] = set()
    for path in paths:
        resp = await admin.get(path)
        assert SECRET not in resp.text, path
        if resp.status_code == 200:
            ok.add(path)
    assert {
        "/admin/part3/coach",
        "/admin/part3/readiness",
        f"/admin/users/{ids['user']}",
        f"/admin/sessions/{ids['session']}",
    } <= ok
