"""Admin Users and support (AU-1..AU-10, AA-7 server side, AA-11, D-7, D-8)."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from itsdangerous import TimestampSigner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.auth.deps import SUSPENDED_MESSAGE
from strong_api.auth.settings import get_auth_settings
from strong_api.billing.entitlements import get_entitlement
from strong_api.main import create_app
from strong_core.db.models import (
    AuditLog,
    GapAnalysis,
    InterviewSession,
    JobTarget,
    MinuteGrant,
    Resume,
    Subscription,
    User,
)
from strong_core.schemas import GapStatus, SessionChannel, SessionStatus, SubscriptionStatus

from .accounts_support import CUSTOMER_ID, FakeStripe, add_session, load_event, post_event
from .conftest import AuthHarness, InlineQueue, RecordingEmailSender, sign_in
from .test_billing import billing_settings, subscribe

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
DEV = "dev@example.com"
W = {"X-Admin-Request": "1"}
REASON = "support ticket 42"


async def _ok() -> None:
    return None


class FakeRooms:
    def __init__(self) -> None:
        self.removed: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def remove_candidate(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        self.removed.append((session_id, user_id))
        return True


@pytest.fixture
def app(
    sessionmaker: Maker, queue: InlineQueue, export_store: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    get_auth_settings.cache_clear()
    app = create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    app.state.export_store = export_store
    app.state.billing_settings = billing_settings()
    app.state.stripe = FakeStripe()
    app.state.voice_rooms = FakeRooms()
    app.state.email_sender = RecordingEmailSender()
    yield app
    get_auth_settings.cache_clear()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, ADMIN)
        yield http


async def _new_client(app: FastAPI, email: str) -> httpx.AsyncClient:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    await sign_in(http, email)
    return http


async def _user(maker: Maker, email: str = DEV) -> User:
    async with maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user


async def _grant(admin: httpx.AsyncClient, user_id: Any, **body: Any) -> httpx.Response:
    return await admin.post(
        f"/admin/users/{user_id}/grants", json={"reason": REASON, **body}, headers=W
    )


# ---------------------------------------------------------------- AU-1


async def test_au1_search_filter_and_pages(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    other = await _new_client(app, "zoe@example.com")
    await other.aclose()
    async with sessionmaker() as db:
        zoe = await db.scalar(select(User).where(User.email == "zoe@example.com"))
        assert zoe is not None
        zoe.full_name = "Zoe Quinn"
        zoe.suspended_at = datetime.now(UTC)
        zoe.created_at = datetime(2026, 1, 5, tzinfo=UTC)
        zoe.last_sign_in_at = datetime(2026, 1, 6, tzinfo=UTC)
        await db.commit()
        zoe_id = zoe.id

    page = (await admin.get("/admin/users")).json()
    assert page["total"] == 3 and page["page"] == 1
    assert {u["email"] for u in page["users"]} == {DEV, ADMIN, "zoe@example.com"}

    async def emails(**params: Any) -> list[str]:
        resp = await admin.get("/admin/users", params=params)
        assert resp.status_code == 200, resp.text
        return sorted(u["email"] for u in resp.json()["users"])

    assert await emails(q="QUINN") == ["zoe@example.com"]  # name, any case
    assert await emails(q="dev@") == [DEV]  # email
    assert await emails(q=str(zoe_id)) == ["zoe@example.com"]  # id
    assert await emails(status="suspended") == ["zoe@example.com"]
    assert await emails(status="active") == [ADMIN, DEV]
    assert await emails(signed_up_to="2026-01-31") == ["zoe@example.com"]
    assert await emails(signed_up_from="2026-02-01") == [ADMIN, DEV]
    assert await emails(last_sign_in_from="2026-01-06", last_sign_in_to="2026-01-06") == [
        "zoe@example.com"
    ]
    assert await emails(plan="paid") == []
    paged = (await admin.get("/admin/users", params={"page_size": 2, "page": 2})).json()
    assert paged["total"] == 3 and len(paged["users"]) == 1

    # A comp plan makes a user "paid" for the plan filter, like a subscription.
    dev = await _user(sessionmaker)
    until = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    resp = await _grant(admin, dev.id, kind="comp_plan", amount=200, expires_at=until)
    assert resp.status_code == 201, resp.text
    assert await emails(plan="paid") == [DEV]
    assert await emails(plan="free") == [ADMIN, "zoe@example.com"]
    row = next(u for u in (await admin.get("/admin/users", params={"q": "dev@"})).json()["users"])
    assert row["plan"] == "paid" and row["minutes_cap"] == 200 and row["comp_until"]


# ---------------------------------------------------------------- AU-2, D-8


async def test_au2_user_detail_has_every_section_and_metadata_only(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker)
    async with sessionmaker() as db:
        resume = Resume(
            org_id=dev.org_id, user_id=dev.id, parsed_json={"summary": "SECRET CV"}, name="CV"
        )
        job = JobTarget(
            org_id=dev.org_id,
            user_id=dev.id,
            raw_text="SECRET POSTING",
            parsed_json={"company_name": "Stripe", "title": "Backend engineer", "x": "SECRET"},
        )
        db.add_all([resume, job])
        await db.flush()
        db.add(
            GapAnalysis(
                org_id=dev.org_id,
                job_target_id=job.id,
                resume_id=resume.id,
                status=GapStatus.FAILED,
                error="SECRET ERROR",
                match_score=77,
                breakdown_json={"findings": "SECRET FINDINGS"},
            )
        )
        db.add(
            Subscription(
                org_id=dev.org_id,
                user_id=dev.id,
                stripe_customer_id=CUSTOMER_ID,
                status=SubscriptionStatus.CANCELED,
            )
        )
        db.add(
            AuditLog(
                org_id=dev.org_id,
                actor=DEV,
                action="account.export_requested",
                entity=f"user:{dev.id}",
                details_json={},
            )
        )
        await db.commit()
        await add_session(db, dev.org_id, dev.id)

    resp = await admin.get(f"/admin/users/{dev.id}")
    assert resp.status_code == 200, resp.text
    assert "SECRET" not in resp.text  # D-8: no resume, posting or gap content
    detail = resp.json()
    assert detail["user"]["email"] == DEV and detail["user"]["auth_provider"] == "dev"
    assert detail["org"]["id"] == str(dev.org_id)
    assert detail["profile"]["has_password"] is False
    sub = detail["subscription"]
    assert sub["stripe_customer_id"] == CUSTOMER_ID and sub["stripe_mode"] == "test"
    assert (
        sub["stripe_customer_url"] == f"https://dashboard.stripe.com/test/customers/{CUSTOMER_ID}"
    )
    assert detail["entitlement"]["plan"] == "free"
    assert detail["entitlement"]["free_interviews_left"] == 1  # 2 free, 1 used
    assert len(detail["sessions"]) == 1
    targets = {t["company"]: t for t in detail["job_targets"]}
    assert targets["Stripe"]["title"] == "Backend engineer"
    assert detail["resume_count"] == 1 and detail["resumes"][0]["status"] == "to_confirm"
    assert detail["gap_analysis_count"] == 1
    gap = detail["gap_analyses"][0]
    assert gap["status"] == "failed" and gap["has_error"] is True
    # AU-10: the user's own privacy actions show; the admin does not run them.
    assert [a["action"] for a in detail["privacy_actions"]] == ["account.export_requested"]
    assert any(a["action"] == "user.signup" for a in detail["audit"])
    assert detail["cost_to_date_usd"] == 0.0

    assert (await admin.get(f"/admin/users/{uuid.uuid4()}")).status_code == 404
    assert (await client.get(f"/admin/users/{dev.id}")).status_code == 404  # AA-4


FORBIDDEN_FIELDS = {
    "parsed",
    "parsed_json",
    "file",
    "file_ref",
    "resume_text",
    "raw_text",
    "content_hash",
    "extracted",
    "breakdown",
    "breakdown_json",
    "findings",
    "match_score",
    "gap_score",
    "brief",
    "brief_json",
    "session_plan",
    "session_plan_json",
}
FORBIDDEN_SCHEMAS = {"Resume", "GapAnalysis", "InterviewerBrief", "PlannedSession", "JobPosting"}


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield ref.rsplit("/", 1)[-1]
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def test_aa11_no_admin_response_schema_holds_resume_or_gap_content(app: FastAPI) -> None:
    """AA-11, D-8: walk every schema reachable from an /admin route; none may carry resume
    text, files or extracted fields, or gap findings, scores or briefs."""
    spec = app.openapi()
    components = spec["components"]["schemas"]
    seen: set[str] = set()
    todo = [
        name
        for path, item in spec["paths"].items()
        if path.startswith("/admin")
        for name in _refs(item)
    ]
    assert todo, "no admin schemas found"
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(_refs(components[name]))
    assert "AdminUserDetail" in seen and "AdminResumeMeta" in seen
    assert not seen & FORBIDDEN_SCHEMAS
    for name in seen:
        props = set(components[name].get("properties", {}))
        assert not props & FORBIDDEN_FIELDS, f"{name} has {props & FORBIDDEN_FIELDS}"


# ---------------------------------------------------------------- AU-3..AU-5 and AA-5/AA-6


async def test_au3_minute_grants_add_to_the_paid_cap_and_expire_or_revoke(
    client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev_state = (await client.get("/auth/me")).json()["user"]
    await subscribe(client, dev_state)
    dev = await _user(sessionmaker)
    async with sessionmaker() as db:
        sub = await db.scalar(select(Subscription).where(Subscription.org_id == dev.org_id))
        assert sub is not None
        sub.minutes_used = 290
        await db.commit()
    assert (await client.get("/billing/usage")).json()["minutes_left"] == 10

    # AA-5, AA-6: header and reason are required, and an audit row is written.
    body = {"kind": "minutes", "amount": 60, "reason": REASON}
    url = f"/admin/users/{dev.id}/grants"
    assert (await admin.post(url, json=body)).status_code == 403
    assert (await admin.post(url, json={**body, "reason": ""}, headers=W)).status_code == 422
    assert (await admin.post(url, json={**body, "amount": 0}, headers=W)).status_code == 422
    grant = (await admin.post(url, json=body, headers=W)).json()
    assert grant["active"] is True and grant["granted_by"] == ADMIN
    usage = (await client.get("/billing/usage")).json()
    assert usage["minutes_left"] == 70 and usage["minutes_cap"] == 360

    # A negative grant removes minutes.
    neg = (await _grant(admin, dev.id, kind="minutes", amount=-20)).json()
    assert (await client.get("/billing/usage")).json()["minutes_left"] == 50

    # AU-3 revoke: the row stays with revoked_at/by; a second revoke is 409; reason required.
    revoke = f"/admin/users/{dev.id}/grants/{neg['id']}"
    assert (await admin.request("DELETE", revoke, json={}, headers=W)).status_code == 422
    resp = await admin.request("DELETE", revoke, json={"reason": REASON}, headers=W)
    assert resp.status_code == 200 and resp.json()["revoked_by"] == ADMIN
    assert (
        await admin.request("DELETE", revoke, json={"reason": REASON}, headers=W)
    ).status_code == 409
    assert (await client.get("/billing/usage")).json()["minutes_left"] == 70

    # Expiry: a grant past its expires_at no longer counts.
    async with sessionmaker() as db:
        row = await db.get(MinuteGrant, uuid.UUID(grant["id"]))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    assert (await client.get("/billing/usage")).json()["minutes_left"] == 10

    async with sessionmaker() as db:
        actions = [
            a.action for a in await db.scalars(select(AuditLog).where(AuditLog.actor == ADMIN))
        ]
    assert actions.count("user.grant_added.minutes") == 2
    assert actions.count("user.grant_revoked.minutes") == 1
    detail = (await admin.get(f"/admin/users/{dev.id}")).json()
    assert [g["active"] for g in detail["grants"]] == [False, False]


async def test_au3_minute_grants_do_not_apply_on_the_free_plan(
    client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker)
    assert (await _grant(admin, dev.id, kind="minutes", amount=60)).status_code == 201
    usage = (await client.get("/billing/usage")).json()
    assert usage["plan"] == "free" and usage["minutes_left"] == 0


async def test_au4_free_interview_grants_raise_the_allowance(
    client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker)
    async with sessionmaker() as db:
        await add_session(db, dev.org_id, dev.id)
        await add_session(db, dev.org_id, dev.id)
    usage = (await client.get("/billing/usage")).json()
    assert usage["free_interviews_left"] == 0 and usage["block_code"] == "upgrade_required"
    grant = (await _grant(admin, dev.id, kind="free_interviews", amount=2)).json()
    usage = (await client.get("/billing/usage")).json()
    assert usage["free_interviews_total"] == 4 and usage["free_interviews_left"] == 2
    assert usage["can_start_session"] is True
    assert (await _grant(admin, dev.id, kind="free_interviews", amount=0)).status_code == 422
    resp = await admin.request(
        "DELETE", f"/admin/users/{dev.id}/grants/{grant['id']}", json={"reason": REASON}, headers=W
    )
    assert resp.status_code == 200
    assert (await client.get("/billing/usage")).json()["free_interviews_left"] == 0


async def test_au5_comp_plan_is_paid_access_until_its_end_date(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker)
    # A comp needs an end date in the future.
    assert (await _grant(admin, dev.id, kind="comp_plan", amount=120)).status_code == 422
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert (
        await _grant(admin, dev.id, kind="comp_plan", amount=120, expires_at=past)
    ).status_code == 422
    until = datetime.now(UTC) + timedelta(days=14)
    resp = await _grant(admin, dev.id, kind="comp_plan", amount=120, expires_at=until.isoformat())
    assert resp.status_code == 201, resp.text
    usage = (await client.get("/billing/usage")).json()
    assert usage["plan"] == "paid" and usage["full_interviews_allowed"] is True
    assert usage["minutes_cap"] == 120 and usage["minutes_left"] == 120
    assert usage["period_end"] is not None

    # Minutes billed to sessions started since the comp count against its cap.
    async with sessionmaker() as db:
        session = await add_session(db, dev.org_id, dev.id, minutes=0)
        session.minutes_billed = 45
        await db.commit()
    assert (await client.get("/billing/usage")).json()["minutes_left"] == 75

    # Minute grants add on top of a comp.
    await _grant(admin, dev.id, kind="minutes", amount=30)
    assert (await client.get("/billing/usage")).json()["minutes_left"] == 105

    # Expired: back to the free plan.
    async with sessionmaker() as db:
        later = datetime.now(UTC) + timedelta(days=15)
        ent = await get_entitlement(db, dev.org_id, app.state.billing_settings, now=later)
        assert ent.plan == "free" and ent.minutes_left == 0


# ---------------------------------------------------------------- AU-6 refunds (D-7)


async def test_au6_charge_refunded_is_recorded_once_and_shown_on_the_user(
    client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev_state = (await client.get("/auth/me")).json()["user"]
    await subscribe(client, dev_state)
    event = load_event("charge_refunded")
    first = await post_event(client, event)
    assert first.json() == {"received": True, "duplicate": False}
    again = await post_event(client, event)
    assert again.json()["duplicate"] is True
    detail = (await admin.get(f"/admin/users/{dev_state['id']}")).json()
    assert detail["refunds"] == [
        {
            "at": detail["refunds"][0]["at"],
            "charge_id": "ch_TEST789",
            "amount_refunded": 2900,
            "currency": "usd",
            "livemode": False,
        }
    ]
    async with sessionmaker() as db:
        rows = list(
            await db.scalars(select(AuditLog).where(AuditLog.action == "billing.charge_refunded"))
        )
    assert len(rows) == 1 and rows[0].actor == "stripe"


# ---------------------------------------------------------------- AU-7 suspend


async def test_au7_suspend_blocks_requests_and_sign_in_and_ends_open_sessions(
    app: FastAPI,
    client: httpx.AsyncClient,
    admin: httpx.AsyncClient,
    sessionmaker: Maker,
    queue: InlineQueue,
) -> None:
    queue.run_jobs = False  # scoring is not under test here
    dev = await _user(sessionmaker)
    async with sessionmaker() as db:
        live = await add_session(db, dev.org_id, dev.id, status=SessionStatus.IN_PROGRESS)
        live.ended_at = None
        waiting = await add_session(
            db, dev.org_id, dev.id, started=False, status=SessionStatus.CREATED
        )
        done = await add_session(db, dev.org_id, dev.id)
        await db.commit()
    assert live.channel == SessionChannel.VOICE

    url = f"/admin/users/{dev.id}/suspend"
    assert (await admin.post(url, json={"reason": REASON})).status_code == 403  # AA-5
    resp = await admin.post(url, json={"reason": REASON}, headers=W)
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["details"]["sessions_ended"]) == {str(live.id), str(waiting.id)}
    assert (await admin.post(url, json={"reason": REASON}, headers=W)).status_code == 409

    async with sessionmaker() as db:
        statuses = {
            s.id: s.status
            for s in await db.scalars(
                select(InterviewSession).where(InterviewSession.org_id == dev.org_id)
            )
        }
    assert statuses[live.id] == SessionStatus.SCORING  # billed and scored, as on a normal end
    assert statuses[waiting.id] == SessionStatus.FAILED  # never started
    assert statuses[done.id] == SessionStatus.COMPLETED
    assert app.state.voice_rooms.removed == [(live.id, dev.id)]

    # The candidate's requests get 403 with the neutral message, then they are signed out.
    resp = await client.get("/billing/usage")
    assert resp.status_code == 403 and resp.json()["detail"] == SUSPENDED_MESSAGE
    assert (await client.get("/auth/me")).json()["status"] == "signed_out"
    # Sign-in is refused with the same message.
    resp = await client.post("/auth/dev-login", json={"email": DEV})
    assert resp.status_code == 403 and resp.json()["detail"] == SUSPENDED_MESSAGE

    detail = (await admin.get(f"/admin/users/{dev.id}")).json()
    assert detail["user"]["status"] == "suspended" and detail["suspended_reason"] == REASON

    unsuspend = f"/admin/users/{dev.id}/unsuspend"
    assert (await admin.post(unsuspend, json={"reason": REASON}, headers=W)).status_code == 200
    assert (await admin.post(unsuspend, json={"reason": REASON}, headers=W)).status_code == 409
    await sign_in(client, DEV)
    assert (await client.get("/billing/usage")).status_code == 200


async def test_au7_admins_cannot_be_suspended(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    boss = await _user(sessionmaker, ADMIN)
    resp = await admin.post(f"/admin/users/{boss.id}/suspend", json={"reason": REASON}, headers=W)
    assert resp.status_code == 409


def test_au7_password_and_link_sign_in_of_a_suspended_user_are_refused(auth: AuthHarness) -> None:
    """The auth harness has an in-memory login throttle, so no Redis is needed."""
    body = {
        "email": "pat@example.com",
        "password": "a long enough passphrase",
        "age_confirmed": True,
        "terms_accepted": True,
    }
    assert auth.client.post("/auth/password/signup", json=body).status_code == 200
    auth.client.post("/auth/logout")

    async def suspend(db: AsyncSession) -> None:
        user = await db.scalar(select(User).where(User.email == "pat@example.com"))
        assert user is not None
        user.suspended_at = datetime.now(UTC)
        await db.commit()

    auth.query(suspend)
    login = {"email": "pat@example.com", "password": "a long enough passphrase"}
    resp = auth.client.post("/auth/password/login", json=login)
    assert resp.status_code == 403 and resp.json()["detail"] == SUSPENDED_MESSAGE
    wrong = auth.client.post("/auth/password/login", json={**login, "password": "nope nope 1"})
    assert wrong.status_code == 401  # a wrong password still gets the usual answer

    auth.client.post("/auth/magic-link", json={"email": "pat@example.com"})
    link = auth.email.sent[-1][1]
    resp = auth.client.get(link.replace("http://web.test/api", ""), follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "http://web.test/signin?error=account_unavailable"
    assert auth.client.get("/auth/me").json()["status"] == "signed_out"


# ---------------------------------------------------------------- AU-8 force sign-out


def _legacy_cookie(user_id: uuid.UUID) -> str:
    """A session cookie as signed before AU-8: it has no epoch."""
    data = base64.b64encode(json.dumps({"uid": str(user_id)}).encode())
    return TimestampSigner(get_auth_settings().session_secret).sign(data).decode()


async def test_au8_force_sign_out_rejects_old_cookies_and_legacy_cookies_count_as_epoch_0(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies={"sh_session": _legacy_cookie(dev.id)}
    ) as legacy:
        assert (await legacy.get("/auth/me")).json()["status"] == "signed_in"  # no mass sign-out

        resp = await admin.post(
            f"/admin/users/{dev.id}/signout", json={"reason": REASON}, headers=W
        )
        assert resp.status_code == 200 and resp.json()["details"]["session_epoch"] == 1
        assert (await client.get("/auth/me")).json()["status"] == "signed_out"
        assert (await legacy.get("/auth/me")).json()["status"] == "signed_out"
    # Signing in again works and carries the new epoch.
    await sign_in(client, DEV)
    assert (await client.get("/auth/me")).json()["status"] == "signed_in"
    async with sessionmaker() as db:
        row = await db.scalar(select(AuditLog).where(AuditLog.action == "user.signed_out"))
        assert row is not None and row.details_json is not None
        assert row.details_json["before"] == {"session_epoch": 0}


# ---------------------------------------------------------------- AU-9 resend link


async def test_au9_resend_sign_in_link_is_emailed_rate_limited_and_audited(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    dev = await _user(sessionmaker)
    url = f"/admin/users/{dev.id}/resend-link"
    for _ in range(3):
        resp = await admin.post(url, json={"reason": REASON}, headers=W)
        assert resp.status_code == 202, resp.text
        assert "token" not in resp.text  # the admin never sees the link
    assert (await admin.post(url, json={"reason": REASON}, headers=W)).status_code == 429
    sent = app.state.email_sender.sent
    assert len(sent) == 3 and all(to == DEV for to, _ in sent)
    assert "/auth/magic-link/callback?token=" in sent[0][1]
    async with sessionmaker() as db:
        rows = list(
            await db.scalars(select(AuditLog).where(AuditLog.action == "user.sign_in_link_sent"))
        )
    assert len(rows) == 3 and rows[0].actor == ADMIN
