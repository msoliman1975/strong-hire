"""Admin portal, Part 1 (v2 S16): the tone and difficulty mix and plan page usage (AD-3), the
auto-profile review queue (AP-3), and the audited v2_enabled switch (FL-1).

The clock is fixed at NOW, Wednesday 2030-01-16 12:00 UTC, so the current week starts Monday
2030-01-14 and the week before Monday 2030-01-07.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.admin import metrics
from strong_api.admin.part1 import week_start
from strong_api.main import create_app
from strong_core import runtime_settings as rs
from strong_core.db.models import (
    AuditLog,
    CompanyAutoProfile,
    InterviewSession,
    JobTarget,
    Org,
    User,
)
from strong_core.schemas import (
    AuthProvider,
    Difficulty,
    InterviewType,
    Mode,
    SessionStatus,
)
from strong_core.schemas.enums import AutoProfileStatus, Tone

from .conftest import InlineQueue, sign_in_admin

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
WRITE = {"X-Admin-Request": "1"}
NOW = datetime(2030, 1, 16, 12, 0, tzinfo=UTC)


async def _ok() -> None:
    return None


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    rs.clear_cache()
    yield
    rs.clear_cache()


@pytest.fixture
def app(sessionmaker: Maker, queue: InlineQueue, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(metrics, "now_utc", lambda: NOW)
    return create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in_admin(http, app, ADMIN)
        yield http


@pytest.fixture
async def stranger(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _audit(maker: Maker, action: str) -> list[AuditLog]:
    async with maker() as db:
        return list((await db.scalars(select(AuditLog).where(AuditLog.action == action))).all())


# ---------------------------------------------------------------- AD-3 tone and difficulty mix


async def _seed_sessions(maker: Maker, rows: list[tuple[datetime, Tone, Difficulty]]) -> None:
    async with maker() as db:
        org = Org(name="mix")
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email="mix@example.com", auth_provider=AuthProvider.DEV)
        db.add(user)
        await db.flush()
        job = JobTarget(org_id=org.id, user_id=user.id, raw_text="Engineer")
        db.add(job)
        await db.flush()
        for created, tone, difficulty in rows:
            db.add(
                InterviewSession(
                    org_id=org.id,
                    job_target_id=job.id,
                    type=InterviewType.BEHAVIORAL,
                    difficulty=difficulty,
                    tone=tone,
                    mode=Mode.REALISTIC,
                    duration_min=20,
                    status=SessionStatus.COMPLETED,
                    created_at=created,
                )
            )
        await db.commit()


def test_ad3_week_starts_on_monday_utc() -> None:
    assert week_start(NOW) == datetime(2030, 1, 14, tzinfo=UTC)
    assert week_start(datetime(2030, 1, 14, 0, 0, tzinfo=UTC)) == datetime(2030, 1, 14, tzinfo=UTC)
    assert week_start(datetime(2030, 1, 13, 23, 59, tzinfo=UTC)) == datetime(2030, 1, 7, tzinfo=UTC)


async def test_ad3_tone_and_difficulty_mix_by_week(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    T, D = Tone, Difficulty  # noqa: N806
    await _seed_sessions(
        sessionmaker,
        [
            # this week (from Monday 01-14)
            (datetime(2030, 1, 14, 0, 0, tzinfo=UTC), T.WARM, D.FRIENDLY),
            (datetime(2030, 1, 15, 9, 0, tzinfo=UTC), T.DIRECT, D.TOUGH),
            (datetime(2030, 1, 16, 11, 0, tzinfo=UTC), T.DIRECT, D.REALISTIC),
            # last week
            (datetime(2030, 1, 13, 23, 59, tzinfo=UTC), T.AS_COMPANY, D.REALISTIC),
            (datetime(2030, 1, 8, 10, 0, tzinfo=UTC), T.NEUTRAL, D.REALISTIC),
            # before the two weeks asked for
            (datetime(2030, 1, 6, 10, 0, tzinfo=UTC), T.WARM, D.TOUGH),
        ],
    )
    resp = await admin.get("/admin/part1/usage", params={"weeks": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [w["week_start"][:10] for w in body["weeks"]] == ["2030-01-07", "2030-01-14"]
    last, this = body["weeks"]
    assert this["sessions"] == 3
    assert this["tone"] == {"as_company": 0, "warm": 1, "neutral": 0, "direct": 2}
    assert this["difficulty"] == {"friendly": 1, "realistic": 1, "tough": 1}
    assert last["sessions"] == 2
    assert last["tone"] == {"as_company": 1, "warm": 0, "neutral": 1, "direct": 0}
    assert last["difficulty"] == {"friendly": 0, "realistic": 2, "tough": 0}
    assert body["tone"] == {"as_company": 1, "warm": 1, "neutral": 1, "direct": 2}
    assert body["difficulty"] == {"friendly": 1, "realistic": 3, "tough": 1}


async def test_ad3_empty_weeks_are_listed_with_zeros(admin: httpx.AsyncClient) -> None:
    body = (await admin.get("/admin/part1/usage")).json()
    assert len(body["weeks"]) == 8
    assert body["weeks"][-1]["week_start"][:10] == "2030-01-14"
    assert all(w["sessions"] == 0 for w in body["weeks"])
    assert body["weeks"][0]["tone"]["as_company"] == 0


async def test_ad3_plan_page_usage_is_shown_not_measured_with_reason(
    admin: httpx.AsyncClient,
) -> None:
    body = (await admin.get("/admin/part1/usage")).json()
    for key in ("plan_page_views", "plan_sessions"):
        assert body[key]["measured"] is False
        assert body[key]["value"] is None
        assert "plan page" in body[key]["reason"]


async def test_ad3_usage_is_admin_only(stranger: httpx.AsyncClient) -> None:
    assert (await stranger.get("/admin/part1/usage")).status_code == 404


# ---------------------------------------------------------------- AP-3 auto-profile queue


SUMMARY_JSON: dict[str, Any] = {
    "summary": "Acme builds rockets and hires engineers who like hard problems.",
    "values_mentioned": ["Ship it", "Own it"],
    "interview_process_notes": ["Two technical rounds"],
    "sources": ["https://acme.example/about", "https://acme.example/careers"],
}


async def _profile(
    maker: Maker,
    name: str = "Acme",
    st: AutoProfileStatus = AutoProfileStatus.PENDING,
    created: datetime | None = None,
) -> uuid.UUID:
    async with maker() as db:
        row = CompanyAutoProfile(
            company_name=name,
            normalized_name=name.lower(),
            source_host=f"{name.lower()}.example",
            summary=SUMMARY_JSON["summary"],
            summary_json=dict(SUMMARY_JSON),
            sources_json=list(SUMMARY_JSON["sources"]),
            status=st,
            model_profile="fake",
            model_id="extractor-fake",
            prompt_version="extractor/auto_profile.v1",
        )
        if created is not None:
            row.created_at = created
        db.add(row)
        await db.commit()
        return row.id


async def _row(maker: Maker, profile_id: uuid.UUID) -> CompanyAutoProfile:
    async with maker() as db:
        row = await db.get(CompanyAutoProfile, profile_id)
        assert row is not None
        return row


async def test_ap3_queue_lists_pending_with_summary_and_sources(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    older = await _profile(sessionmaker, "Acme", created=datetime(2030, 1, 1, tzinfo=UTC))
    newer = await _profile(sessionmaker, "Globex", created=datetime(2030, 1, 2, tzinfo=UTC))
    await _profile(sessionmaker, "Initech", AutoProfileStatus.APPROVED)
    await _profile(sessionmaker, "Umbrella", AutoProfileStatus.RETIRED)

    body = (await admin.get("/admin/auto-profiles")).json()
    assert body["counts"] == {"pending": 2, "approved": 1, "retired": 1}
    assert [p["id"] for p in body["profiles"]] == [str(older), str(newer)]
    first = body["profiles"][0]
    assert first["summary"] == SUMMARY_JSON["summary"]
    assert first["sources"] == SUMMARY_JSON["sources"]
    assert first["values_mentioned"] == ["Ship it", "Own it"]
    assert first["interview_process_notes"] == ["Two technical rounds"]
    assert first["source_host"] == "acme.example"

    approved = (await admin.get("/admin/auto-profiles", params={"status": "approved"})).json()
    assert [p["company_name"] for p in approved["profiles"]] == ["Initech"]
    every = (await admin.get("/admin/auto-profiles", params={"status": "all"})).json()
    assert len(every["profiles"]) == 4
    one = (await admin.get(f"/admin/auto-profiles/{older}")).json()
    assert one["company_name"] == "Acme"
    assert (await admin.get(f"/admin/auto-profiles/{uuid.uuid4()}")).status_code == 404


async def test_ap3_approve_is_audited(admin: httpx.AsyncClient, sessionmaker: Maker) -> None:
    pid = await _profile(sessionmaker)
    url = f"/admin/auto-profiles/{pid}/approve"
    assert (await admin.post(url, json={"reason": "reads fine"})).status_code == 403  # AA-5
    assert (await admin.post(url, json={}, headers=WRITE)).status_code == 422  # AA-6: reason
    resp = await admin.post(url, json={"reason": "reads fine"}, headers=WRITE)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["reviewed_by"] == ADMIN
    row = await _row(sessionmaker, pid)
    assert row.status == AutoProfileStatus.APPROVED
    assert row.reviewed_at is not None
    (audit,) = await _audit(sessionmaker, "auto_profile.approve")
    assert audit.actor == ADMIN
    assert audit.entity == f"company_auto_profile:{pid}"
    assert audit.details_json is not None
    assert audit.details_json["reason"] == "reads fine"
    assert audit.details_json["before"]["status"] == "pending"
    assert audit.details_json["after"]["status"] == "approved"
    # Only a pending profile can be approved.
    again = await admin.post(url, json={"reason": "again"}, headers=WRITE)
    assert again.status_code == 409


async def test_ap3_edit_summary_is_audited_and_keeps_status(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    pid = await _profile(sessionmaker)
    url = f"/admin/auto-profiles/{pid}/summary"
    new = "Acme builds reusable rockets."
    resp = await admin.put(url, json={"reason": "tighter", "summary": f"  {new} "}, headers=WRITE)
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == new
    assert resp.json()["status"] == "pending"
    row = await _row(sessionmaker, pid)
    assert row.summary == new
    assert row.summary_json["summary"] == new
    assert row.summary_json["sources"] == SUMMARY_JSON["sources"]
    (audit,) = await _audit(sessionmaker, "auto_profile.edit")
    assert audit.details_json is not None
    assert audit.details_json["before"]["summary"] == SUMMARY_JSON["summary"]
    assert audit.details_json["after"]["summary"] == new
    empty = await admin.put(url, json={"reason": "blank", "summary": ""}, headers=WRITE)
    assert empty.status_code == 422


async def test_ap3_retire_is_audited_and_final(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    pid = await _profile(sessionmaker, st=AutoProfileStatus.APPROVED)
    resp = await admin.post(
        f"/admin/auto-profiles/{pid}/retire", json={"reason": "wrong company"}, headers=WRITE
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "retired"
    (audit,) = await _audit(sessionmaker, "auto_profile.retire")
    assert audit.details_json is not None
    assert audit.details_json["before"]["status"] == "approved"
    assert audit.details_json["after"]["status"] == "retired"
    for path, body in (
        ("retire", {"reason": "again"}),
        ("approve", {"reason": "undo"}),
    ):
        assert (
            await admin.post(f"/admin/auto-profiles/{pid}/{path}", json=body, headers=WRITE)
        ).status_code == 409
    edit = await admin.put(
        f"/admin/auto-profiles/{pid}/summary",
        json={"reason": "fix", "summary": "New text"},
        headers=WRITE,
    )
    assert edit.status_code == 409


async def test_ap3_queue_is_admin_only(stranger: httpx.AsyncClient, sessionmaker: Maker) -> None:
    pid = await _profile(sessionmaker)
    assert (await stranger.get("/admin/auto-profiles")).status_code == 404
    resp = await stranger.post(
        f"/admin/auto-profiles/{pid}/approve", json={"reason": "sneaky"}, headers=WRITE
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------- FL-1 the v2 switch, audited


async def test_fl1_v2_enabled_switch_is_audited_and_reaches_status(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    body = (await admin.get("/admin/ops/settings")).json()
    assert body["values"]["v2_enabled"] is False
    assert body["defaults"]["v2_enabled"] is False
    resp = await admin.put(
        "/admin/ops/settings/v2_enabled",
        json={"value": True, "reason": "launch v2.0"},
        headers=WRITE,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"]["v2_enabled"] is True
    meta = {m["key"]: m for m in resp.json()["meta"]}
    assert meta["v2_enabled"]["updated_by"] == ADMIN
    (audit,) = await _audit(sessionmaker, "ops.setting_changed")
    assert audit.entity == "runtime_setting:v2_enabled"
    assert audit.details_json is not None
    assert audit.details_json["reason"] == "launch v2.0"
    assert audit.details_json["before"] == {"v2_enabled": False}
    assert audit.details_json["after"] == {"v2_enabled": True}
    status_body = (await admin.get("/status")).json()
    assert status_body["v2_enabled"] is True
