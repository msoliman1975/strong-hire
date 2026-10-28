"""Admin portal, Part 2 (v2 S25): story library metrics without story text (AD-4).

The clock is fixed at NOW, Wednesday 2030-03-13 12:00 UTC, so the current week starts Monday
2030-03-11. Story text in the fixtures holds SECRET, and no admin response may contain it.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.account.exports import MemoryExportStore
from strong_api.admin import metrics
from strong_api.admin.part2 import delivery_values
from strong_api.main import create_app
from strong_core import runtime_settings as rs
from strong_core.db.models import (
    AuditLog,
    InterviewSession,
    JobTarget,
    Org,
    Scorecard,
    Story,
    User,
)
from strong_core.schemas import AuthProvider, Difficulty, InterviewType, Mode, SessionStatus
from strong_core.schemas.enums import HireSignal, StorySource, StoryStatus

from .accounts_support import sign_up
from .conftest import InlineQueue, sign_in_admin

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
NOW = datetime(2030, 3, 13, 12, 0, tzinfo=UTC)
SECRET = "SECRET-STORY-TEXT"


async def _ok() -> None:
    return None


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    rs.clear_cache()
    yield
    rs.clear_cache()


@pytest.fixture
def app(
    sessionmaker: Maker,
    queue: InlineQueue,
    export_store: MemoryExportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    monkeypatch.setattr(metrics, "now_utc", lambda: NOW)
    app = create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    app.state.export_store = export_store
    return app


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


async def _user(db: AsyncSession, email: str) -> User:
    org = Org(name=email)
    db.add(org)
    await db.flush()
    user = User(org_id=org.id, email=email, auth_provider=AuthProvider.DEV, training_consent=True)
    db.add(user)
    await db.flush()
    return user


async def _debrief(
    db: AsyncSession, user: User, at: datetime, delivery: list[dict[str, float] | None]
) -> InterviewSession:
    """A completed session with a scorecard; one answer per `delivery` item."""
    job = JobTarget(org_id=user.org_id, user_id=user.id, raw_text="Engineer")
    db.add(job)
    await db.flush()
    session = InterviewSession(
        org_id=user.org_id,
        job_target_id=job.id,
        type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=20,
        status=SessionStatus.COMPLETED,
        created_at=at,
    )
    db.add(session)
    await db.flush()
    per_question: list[dict[str, Any]] = [
        {
            "question_ref": f"q{i}",
            "question_text": "Tell me about a hard project.",
            "score": 3,
            "strengths": [],
            "misses": [],
            "story_fix": f"{SECRET} fix",
            "delivery": d,
        }
        for i, d in enumerate(delivery)
    ]
    db.add(
        Scorecard(
            org_id=user.org_id,
            session_id=session.id,
            hire_signal=HireSignal.LEAN_HIRE,
            rationale="Solid.",
            competency_scores_json=[],
            per_question_json=per_question,
            scorer_model="fake",
            rubric_version="scorer/scorecard.v1",
            created_at=at,
        )
    )
    await db.flush()
    return session


def _story(
    user: User,
    at: datetime,
    status: StoryStatus = StoryStatus.DRAFT,
    source: StorySource = StorySource.DEBRIEF_ANSWER,
) -> Story:
    return Story(
        org_id=user.org_id,
        user_id=user.id,
        title=f"{SECRET} title",
        context=f"{SECRET} context",
        stakes=f"{SECRET} stakes",
        action=f"{SECRET} action",
        result=f"{SECRET} result",
        reflection=f"{SECRET} reflection",
        skills=["ownership"],
        status=status,
        source=source,
        source_question_ref=f"{SECRET}-ref",
        notes_json=[{"text": f"{SECRET} note", "at": at.isoformat()}],
        created_at=at,
        updated_at=at,
    )


def _wpm(wpm: float, fpm: float, secs: float) -> dict[str, float]:
    return {"words_per_minute": wpm, "fillers_per_minute": fpm, "duration_seconds": secs}


async def _seed(maker: Maker) -> dict[str, uuid.UUID]:
    """Four users:
    - ana: first debrief 40 days ago, saved a story 10 days after it (counts as saved), proven
    - bo: first debrief 35 days ago, first story 31 days after it (too late)
    - cy: first debrief 50 days ago, no story
    - di: first debrief 5 days ago (not in the cohort yet), two stories saved this week
    """
    async with maker() as db:
        ana = await _user(db, "ana@example.com")
        s_ana = await _debrief(db, ana, NOW - timedelta(days=40), [_wpm(140, 2, 60)])
        db.add(_story(ana, NOW - timedelta(days=30), StoryStatus.PROVEN))
        bo = await _user(db, "bo@example.com")
        await _debrief(db, bo, NOW - timedelta(days=35), [])
        db.add(_story(bo, NOW - timedelta(days=4), source=StorySource.MANUAL))
        cy = await _user(db, "cy@example.com")
        await _debrief(db, cy, NOW - timedelta(days=50), [])
        di = await _user(db, "di@example.com")
        # This week: two answers with delivery metrics, one without.
        await _debrief(db, di, NOW - timedelta(days=1), [_wpm(150, 4, 90), _wpm(130, 2, 30), None])
        db.add(_story(di, NOW - timedelta(days=1)))
        db.add(_story(di, NOW - timedelta(hours=2), source=StorySource.COACH))
        await db.commit()
        return {"user": ana.id, "session": s_ana.id, "org": ana.org_id}


# ---------------------------------------------------------------- AD-4 metrics


async def test_ad4_story_metrics_aggregate(admin: httpx.AsyncClient, sessionmaker: Maker) -> None:
    """AD-4: save rate over the 30-day cohort, stories per user, Draft to Proven rate."""
    await _seed(sessionmaker)
    resp = await admin.get("/admin/part2/stories", params={"weeks": 8})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Cohort: ana, bo, cy (di's first debrief is 5 days old). Only ana saved in time.
    assert body["save_cohort"] == {"users": 3, "saved": 1}
    rate = body["story_save_rate"]
    assert rate["measured"] is True and rate["unit"] == "pct"
    assert rate["value"] == pytest.approx(1 / 3, abs=1e-5)
    assert rate["target"] == 0.4

    counts = body["counts"]
    assert counts["total"] == 4 and counts["draft"] == 3 and counts["proven"] == 1
    assert counts["by_source"] == {"debrief_answer": 2, "manual": 1, "coach": 1}
    assert counts["users_with_stories"] == 3
    assert body["stories_per_user"]["value"] == pytest.approx(4 / 3, abs=1e-5)
    assert body["draft_to_proven_rate"]["value"] == pytest.approx(0.25)

    weeks = body["stories_by_week"]
    assert len(weeks) == 8 and weeks[-1]["week_start"].startswith("2030-03-11")
    assert weeks[-1]["saved"] == 2  # di's two (Tuesday and today)
    assert weeks[-2]["saved"] == 1  # bo's, Saturday 03-09


async def test_ad4_delivery_trends_by_week(admin: httpx.AsyncClient, sessionmaker: Maker) -> None:
    """AD-4: mean delivery metrics (DM-1) per week, from answers that have them."""
    await _seed(sessionmaker)
    body = (await admin.get("/admin/part2/stories", params={"weeks": 8})).json()
    delivery = body["delivery"]
    assert len(delivery) == 8
    this_week = delivery[-1]
    assert this_week["answers"] == 2
    assert this_week["words_per_minute"] == 140.0
    assert this_week["fillers_per_minute"] == 3.0
    assert this_week["duration_seconds"] == 60.0
    # The 8 weeks start Monday 2030-01-21; ana's debrief (2030-02-01) is in the second.
    filled = [w for w in delivery if w["answers"]]
    assert [w["answers"] for w in filled] == [1, 2]
    empty = delivery[0]
    assert empty["answers"] == 0 and empty["words_per_minute"] is None


async def test_ad4_save_rate_not_measured_without_a_cohort(admin: httpx.AsyncClient) -> None:
    """AO-8 via AD-4: no first debrief 30 days old yet means "not measured", with a reason."""
    body = (await admin.get("/admin/part2/stories")).json()
    assert body["story_save_rate"]["measured"] is False
    assert body["story_save_rate"]["reason"]
    assert body["counts"]["total"] == 0
    assert body["draft_to_proven_rate"]["value"] is None


def test_ad4_delivery_values_read_only_numbers() -> None:
    per_question = [
        {"question_text": "x", "delivery": _wpm(120, 1, 45)},
        {"question_text": "y", "delivery": None},
        {"question_text": "z", "delivery": {"words_per_minute": "fast"}},
        "junk",
    ]
    assert delivery_values(per_question) == [(120.0, 1.0, 45.0)]
    assert delivery_values(None) == []


async def test_ad4_story_metrics_are_admin_only(candidate: httpx.AsyncClient) -> None:
    assert (await candidate.get("/admin/part2/stories")).status_code == 404
    await sign_up(candidate)
    assert (await candidate.get("/admin/part2/stories")).status_code == 404


async def test_ad4_user_detail_shows_story_counts_only(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    ids = await _seed(sessionmaker)
    detail = (await admin.get(f"/admin/users/{ids['user']}")).json()
    stories = detail["stories"]
    assert stories["total"] == 1 and stories["proven"] == 1 and stories["draft"] == 0
    assert stories["last_saved_at"].startswith("2030-02-11")
    assert set(stories) == {"total", "draft", "proven", "last_saved_at"}


# ---------------------------------------------------------------- the no-story-text rule


def _fill(path: str, ids: dict[str, uuid.UUID]) -> str:
    """Fill the path parameters of an admin route with the seeded ids where the name says so."""
    known = {"user_id": ids["user"], "session_id": ids["session"], "org_id": ids["org"]}
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        name = out[start + 1 : end].split(":")[0]
        out = out[:start] + str(known.get(name, uuid.uuid4())) + out[end + 1 :]
    return out


async def test_ad4_no_admin_endpoint_returns_story_text(
    app: FastAPI, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AD-4: every admin GET route in the API schema, with the seeded user and session filled in,
    returns no story title, part, note or story fix, even with training consent on."""
    ids = await _seed(sessionmaker)
    paths = sorted(
        {
            _fill(path, ids)
            for path, ops in app.openapi()["paths"].items()
            if path.startswith("/admin/") and not path.startswith("/admin/auth/") and "get" in ops
        }
    )
    assert "/admin/part2/stories" in paths
    assert f"/admin/users/{ids['user']}" in paths
    assert f"/admin/sessions/{ids['session']}" in paths
    ok: set[str] = set()
    for path in paths:
        resp = await admin.get(path)
        assert SECRET not in resp.text, path
        if resp.status_code == 200:
            ok.add(path)
    # The pages that hold the user's data must have answered, or the sweep proves nothing.
    assert {
        "/admin/part2/stories",
        f"/admin/users/{ids['user']}",
        f"/admin/sessions/{ids['session']}",
    } <= ok
    assert len(ok) >= 10, "the sweep should reach real admin pages"


# ---------------------------------------------------------------- export and delete


async def test_ad4_export_and_delete_include_stories(
    candidate: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """AD-4 support: the user's export holds their stories, delete removes them, and both are in
    the audit log the admin sees (AU-10), without the story text."""
    user = await sign_up(candidate)
    user_id, org_id = uuid.UUID(user["id"]), uuid.UUID(user["org_id"])
    async with sessionmaker() as db:
        row = await db.get(User, user_id)
        assert row is not None
        db.add(_story(row, NOW - timedelta(days=1)))
        await db.commit()

    export = (await candidate.post("/account/export")).json()
    assert export["status"] == "ready"
    resp = await candidate.get(f"/account/export/{export['id']}/download")
    data = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("data.json"))
    assert [s["title"] for s in data["tables"]["stories"]] == [f"{SECRET} title"]

    detail = (await admin.get(f"/admin/users/{user_id}")).json()
    assert detail["stories"]["total"] == 1
    assert "account.export_requested" in {a["action"] for a in detail["privacy_actions"]}
    assert SECRET not in json.dumps(detail)

    assert (await candidate.delete("/account")).status_code == 202
    async with sessionmaker() as db:
        assert list(await db.scalars(select(Story).where(Story.org_id == org_id))) == []
        deleted = list(
            await db.scalars(select(AuditLog).where(AuditLog.action == "account.deleted"))
        )
    assert len(deleted) == 1
    assert deleted[0].details_json["rows"]["stories"] == 1
