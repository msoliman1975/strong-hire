"""Admin sign-in and sessions: AA-1 (admins in the database, seeding, strongctl), AA-2 (password,
email link, Google), AA-3 (the sh_admin cookie, idle and absolute timeouts), AA-4 (only an
admin session counts) and AA-8 (my sessions, removing an admin)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine
from typer.testing import CliRunner

from strong_api.admin import seed_admins_on_startup
from strong_api.admin.auth import set_admin_cookie
from strong_api.admin.identity import (
    ADMIN_COOKIE,
    AdminAuth,
    seed_admins,
)
from strong_api.auth.google import GoogleIdentity, GoogleSignInError
from strong_api.auth.magic_links import MagicLinks, MemoryUsedTokenStore
from strong_api.auth.passwords import MemoryLoginThrottle, hash_password
from strong_api.auth.settings import AppEnv, AuthSettings
from strong_api.main import create_app
from strong_api.profiles import cli
from strong_core.db.models import AdminSession, AdminUser, AuditLog, Base, User

from .conftest import (
    ADMIN_EMAIL,
    InlineQueue,
    RecordingEmailSender,
    make_admin,
    sign_in,
    sign_in_admin,
    use_test_admin_auth,
)

Maker = async_sessionmaker[AsyncSession]
PASSWORD = "correct horse battery"
HEADERS = {"X-Admin-Request": "1"}


async def _ok() -> None:
    return None


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeGoogle:
    def __init__(self, email: str | None) -> None:
        self.email = email

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        return RedirectResponse(f"https://accounts.google.test/auth?redirect_uri={redirect_uri}")

    async def fetch_identity(self, request: Request) -> GoogleIdentity:
        if self.email is None:
            raise GoogleSignInError("denied")
        return GoogleIdentity(email=self.email)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(sessionmaker: Maker, queue: InlineQueue, clock: Clock) -> FastAPI:
    app = create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    use_test_admin_auth(app)
    app.state.admin_auth.clock = clock
    return app


def _client(app: FastAPI, **headers: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app, **{"user-agent": "pytest-admin"}) as http:
        await sign_in_admin(http, app)
        yield http


def _sender(app: FastAPI) -> RecordingEmailSender:
    return use_test_admin_auth(app)


async def _password_user(app: FastAPI, email: str, *, verified: bool = True) -> None:
    """A candidate account with a password (AC-4)."""
    async with _client(app) as http:
        await sign_in(http, email)
    async with app.state.sessionmaker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user.password_hash = hash_password(PASSWORD)
        user.email_verified_at = datetime.now(UTC) if verified else None
        await db.commit()


async def _disable(maker: Maker, email: str) -> None:
    async with maker() as db:
        row = await db.scalar(select(AdminUser).where(AdminUser.email == email))
        assert row is not None
        row.disabled_at = datetime.now(UTC)
        await db.commit()


async def _sessions(maker: Maker) -> list[AdminSession]:
    async with maker() as db:
        return list(await db.scalars(select(AdminSession)))


# ----------------------------------------------------------------------------------- AA-1


async def test_aa1_seed_fills_an_empty_table_once(sessionmaker: Maker) -> None:
    async with sessionmaker() as db:
        assert await seed_admins(db, [" Boss@Example.com ", "ops@example.com", ""]) == 2
    async with sessionmaker() as db:
        rows = list(await db.scalars(select(AdminUser).order_by(AdminUser.email)))
        assert [(r.email, r.added_by) for r in rows] == [
            ("boss@example.com", "ADMIN_EMAILS"),
            ("ops@example.com", "ADMIN_EMAILS"),
        ]
        # After that, ADMIN_EMAILS is ignored, even when it changes.
        assert await seed_admins(db, ["new@example.com", "boss@example.com"]) == 0
        assert len(list(await db.scalars(select(AdminUser)))) == 2


async def test_aa1_seed_skips_a_table_that_has_only_removed_admins(sessionmaker: Maker) -> None:
    async with sessionmaker() as db:
        db.add(AdminUser(email="gone@example.com", disabled_at=datetime.now(UTC)))
        await db.commit()
        assert await seed_admins(db, ["boss@example.com"]) == 0


async def test_aa1_startup_seeds_from_admin_emails(app: FastAPI, sessionmaker: Maker) -> None:
    app.state.admin_auth_settings = AuthSettings(admin_emails="Boss@Example.com,ops@example.com")
    await seed_admins_on_startup(app)
    await seed_admins_on_startup(app)  # idempotent
    async with sessionmaker() as db:
        emails = set(await db.scalars(select(AdminUser.email)))
    assert emails == {"boss@example.com", "ops@example.com"}


@pytest.fixture
def cli_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cli.db"
    sync = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync)
    sync.dispose()

    def make_engine() -> AsyncEngine:
        return _create_async_engine(f"sqlite+aiosqlite:///{path}")

    monkeypatch.setattr(cli, "make_engine", make_engine)
    return path


def _cli(*args: str) -> Any:
    return CliRunner().invoke(cli.app, ["admin", *args])


def test_aa1_strongctl_admin_add_list_remove(cli_db: Path) -> None:
    assert "No admins" in _cli("list").output
    added = _cli("add", "Boss@Example.com")
    assert added.exit_code == 0 and "Added admin boss@example.com" in added.output
    assert "already an admin" in _cli("add", "boss@example.com").output
    assert "boss@example.com  active  added by strongctl" in _cli("list").output

    # A live session, to check that remove ends it (AA-8).
    sync = create_engine(f"sqlite:///{cli_db}")
    with sync.begin() as conn:
        admin_id = conn.execute(select(AdminUser.id)).scalar_one()
        now = datetime.now(UTC)
        conn.execute(
            AdminSession.__table__.insert(),
            [
                {
                    "id": "a" * 64,
                    "admin_user_id": admin_id,
                    "created_at": now,
                    "last_seen_at": now,
                    "expires_at": now + timedelta(hours=12),
                }
            ],
        )
    removed = _cli("remove", "boss@example.com")
    assert removed.exit_code == 0, removed.output
    assert "1 session(s) ended" in removed.output
    assert "removed" in _cli("list").output
    assert _cli("remove", "boss@example.com").exit_code == 1
    assert _cli("add", "nope").exit_code == 1
    with sync.connect() as conn:
        assert conn.execute(select(AdminSession.revoked_at)).scalar_one() is not None
        actions = list(conn.execute(select(AuditLog.action, AuditLog.actor)))
    sync.dispose()
    assert [a for a, _ in actions] == ["admin.admin_added", "admin.admin_removed"]
    assert all(actor.startswith("strongctl:") for _, actor in actions)
    # Turning a removed admin back on.
    assert "Added admin" in _cli("add", "boss@example.com").output


# ----------------------------------------------------------------------------------- AA-2


async def test_aa2_password_sign_in_for_an_admin(app: FastAPI, sessionmaker: Maker) -> None:
    await make_admin(app)
    await _password_user(app, ADMIN_EMAIL)
    async with _client(app) as http:
        bad = await http.post(
            "/admin/auth/password", json={"email": ADMIN_EMAIL, "password": "wrong password"}
        )
        assert bad.status_code == 401
        assert ADMIN_COOKIE not in http.cookies
        ok = await http.post(
            "/admin/auth/password", json={"email": "Boss@Example.com", "password": PASSWORD}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["email"] == ADMIN_EMAIL
        assert (await http.get("/admin/me")).json()["email"] == ADMIN_EMAIL
        assert (await http.get("/admin/users")).status_code == 200


async def test_aa2_password_is_refused_for_non_admins_removed_admins_and_unconfirmed_email(
    app: FastAPI, sessionmaker: Maker
) -> None:
    await _password_user(app, "user@example.com")
    await make_admin(app, "gone@example.com")
    await _password_user(app, "gone@example.com")
    await _disable(sessionmaker, "gone@example.com")
    # Someone signed up with the admin's email and chose a password, but never confirmed it.
    await make_admin(app, "new-admin@example.com")
    await _password_user(app, "new-admin@example.com", verified=False)
    async with _client(app) as http:
        for email in ("user@example.com", "gone@example.com", "new-admin@example.com"):
            resp = await http.post(
                "/admin/auth/password", json={"email": email, "password": PASSWORD}
            )
            assert resp.status_code == 401, email
            assert resp.json()["detail"] == "The email or password is wrong."
        assert ADMIN_COOKIE not in http.cookies


async def test_aa2_password_lockout(app: FastAPI, sessionmaker: Maker) -> None:
    await make_admin(app)
    await _password_user(app, ADMIN_EMAIL)
    async with _client(app) as http:
        body = {"email": ADMIN_EMAIL, "password": "wrong password"}
        for _ in range(5):
            assert (await http.post("/admin/auth/password", json=body)).status_code == 401
        body["password"] = PASSWORD
        assert (await http.post("/admin/auth/password", json=body)).status_code == 429


async def test_aa2_email_link_only_to_active_admins_with_the_same_reply(
    app: FastAPI, sessionmaker: Maker
) -> None:
    sender = _sender(app)
    await make_admin(app, "gone@example.com")
    await _disable(sessionmaker, "gone@example.com")
    async with _client(app) as http:
        for email in ("stranger@example.com", "gone@example.com"):
            resp = await http.post("/admin/auth/link", json={"email": email})
            assert resp.status_code == 202 and resp.json()["sent"] is True
        assert sender.sent == []
        me = await sign_in_admin(http, app)
    assert me["email"] == ADMIN_EMAIL
    to, link = sender.sent[-1]
    assert to == ADMIN_EMAIL
    assert link.startswith("http://localhost:5181/signin/verify?token=")  # ADMIN_BASE_URL


async def test_aa2_email_link_works_once_and_not_after_removal(
    app: FastAPI, sessionmaker: Maker
) -> None:
    sender = _sender(app)
    await make_admin(app)
    async with _client(app) as http:
        await http.post("/admin/auth/link", json={"email": ADMIN_EMAIL})
        token = parse_qs(urlparse(sender.sent[-1][1]).query)["token"][0]
        assert (
            await http.post("/admin/auth/link/verify", json={"token": token})
        ).status_code == 200
        again = await http.post("/admin/auth/link/verify", json={"token": token})
        assert again.status_code == 400 and again.json()["detail"] == "link_used"
        bad = await http.post("/admin/auth/link/verify", json={"token": "x.y.z"})
        assert bad.json()["detail"] == "link_invalid"

        await http.post("/admin/auth/link", json={"email": ADMIN_EMAIL})
        token = parse_qs(urlparse(sender.sent[-1][1]).query)["token"][0]
        await _disable(sessionmaker, ADMIN_EMAIL)
        late = await http.post("/admin/auth/link/verify", json={"token": token})
        assert late.status_code == 400 and late.json()["detail"] == "link_invalid"


async def test_aa2_candidate_magic_links_do_not_work_for_admin_sign_in(app: FastAPI) -> None:
    """The admin link has its own salt: a candidate sign-in token is not an admin token."""
    await make_admin(app)
    auth: AdminAuth = app.state.admin_auth
    candidate = MagicLinks(auth.settings.session_secret, 900, MemoryUsedTokenStore())
    async with _client(app) as http:
        resp = await http.post(
            "/admin/auth/link/verify", json={"token": candidate.issue(ADMIN_EMAIL)}
        )
        assert resp.status_code == 400


async def test_aa2_google_sign_in_on_the_admin_host(app: FastAPI) -> None:
    await make_admin(app)
    async with _client(app) as http:
        assert (await http.get("/admin/auth/providers")).json()["google"] is False
        assert (await http.get("/admin/auth/google/login")).status_code == 404

        app.state.admin_auth.google = FakeGoogle(ADMIN_EMAIL)
        assert (await http.get("/admin/auth/providers")).json()["google"] is True
        login = await http.get("/admin/auth/google/login")
        assert login.headers["location"] == (
            "https://accounts.google.test/auth?redirect_uri="
            "http://localhost:5181/api/admin/auth/google/callback"
        )
        cb = await http.get("/admin/auth/google/callback")
        assert cb.status_code == 303 and cb.headers["location"] == "http://localhost:5181/"
        assert (await http.get("/admin/me")).json()["email"] == ADMIN_EMAIL


async def test_aa2_google_refuses_non_admins_and_errors(app: FastAPI) -> None:
    async with _client(app) as http:
        app.state.admin_auth.google = FakeGoogle("stranger@example.com")
        cb = await http.get("/admin/auth/google/callback")
        assert cb.headers["location"] == "http://localhost:5181/signin?error=not_admin"
        assert ADMIN_COOKIE not in http.cookies
        app.state.admin_auth.google = FakeGoogle(None)
        cb = await http.get("/admin/auth/google/callback")
        assert cb.headers["location"] == "http://localhost:5181/signin?error=google"


# ----------------------------------------------------------------------------------- AA-3


async def test_aa3_cookie_attributes_and_session_row(app: FastAPI, sessionmaker: Maker) -> None:
    await make_admin(app)
    sender = _sender(app)
    async with _client(app, **{"user-agent": "pytest-agent/1.0"}) as http:
        await http.post("/admin/auth/link", json={"email": ADMIN_EMAIL})
        token = parse_qs(urlparse(sender.sent[-1][1]).query)["token"][0]
        resp = await http.post("/admin/auth/link/verify", json={"token": token})
        cookie = resp.headers["set-cookie"]
        raw = http.cookies[ADMIN_COOKIE]
    parts = [p.strip().lower() for p in cookie.split(";")]
    assert parts[0].startswith(f"{ADMIN_COOKIE}=")
    assert {"httponly", "samesite=strict", "path=/", "max-age=43200"} <= set(parts)
    assert not any(p.startswith("domain") for p in parts)  # host-only
    assert "secure" not in parts  # local: plain http
    assert len(raw) >= 40  # secrets.token_urlsafe(32)

    [row] = await _sessions(sessionmaker)
    assert row.id == hashlib.sha256(raw.encode()).hexdigest()  # only the hash is stored
    assert row.user_agent == "pytest-agent/1.0"
    assert row.ip is not None
    created = row.created_at.replace(tzinfo=UTC)
    assert row.expires_at.replace(tzinfo=UTC) - created == timedelta(hours=12)


def test_aa3_cookie_is_secure_outside_local_and_test() -> None:
    def auth(env: AppEnv) -> AdminAuth:
        settings = AuthSettings(app_env=env, session_secret="s" * 40)
        links = MagicLinks(settings.session_secret, 900, MemoryUsedTokenStore())
        return AdminAuth(settings, RecordingEmailSender(), links, MemoryLoginThrottle())

    for env, secure in (
        (AppEnv.PRODUCTION, True),
        (AppEnv.STAGING, True),
        (AppEnv.LOCAL, False),
        (AppEnv.TEST, False),
    ):
        response = Response()
        set_admin_cookie(response, auth(env), "token")
        parts = [p.strip().lower() for p in response.headers["set-cookie"].split(";")]
        assert ("secure" in parts) is secure, env


async def test_aa3_idle_timeout_two_hours(
    admin: httpx.AsyncClient, clock: Clock, sessionmaker: Maker
) -> None:
    clock.advance(seconds=30)
    assert (await admin.get("/admin/me")).status_code == 200
    [row] = await _sessions(sessionmaker)
    assert row.last_seen_at == row.created_at  # touched at most once a minute
    clock.advance(minutes=1)
    assert (await admin.get("/admin/me")).status_code == 200
    [row] = await _sessions(sessionmaker)
    assert row.last_seen_at.replace(tzinfo=UTC) == clock.now

    clock.advance(hours=1, minutes=59)
    assert (await admin.get("/admin/users")).status_code == 200  # still inside the idle window
    clock.advance(hours=2)
    assert (await admin.get("/admin/users")).status_code == 404
    assert (await admin.get("/admin/me")).status_code == 401


async def test_aa3_absolute_timeout_twelve_hours(admin: httpx.AsyncClient, clock: Clock) -> None:
    for _ in range(11):
        clock.advance(hours=1)
        assert (await admin.get("/admin/me")).status_code == 200
    clock.advance(minutes=59)
    assert (await admin.get("/admin/me")).status_code == 200
    clock.advance(minutes=1)  # 12 h after sign-in, though it was used a minute ago
    assert (await admin.get("/admin/me")).status_code == 401


async def test_aa3_sign_out_revokes_the_session(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    raw = admin.cookies[ADMIN_COOKIE]
    resp = await admin.post("/admin/auth/signout")
    assert resp.status_code == 204
    assert ADMIN_COOKIE not in admin.cookies
    [row] = await _sessions(sessionmaker)
    assert row.revoked_at is not None
    admin.cookies.set(ADMIN_COOKIE, raw)  # an old copy of the cookie does not work either
    assert (await admin.get("/admin/me")).status_code == 401


# ----------------------------------------------------------------------------------- AA-4


async def test_aa4_candidate_session_never_grants_admin(app: FastAPI) -> None:
    """Even for an admin's own email, sh_session opens nothing under /admin."""
    await make_admin(app)
    async with _client(app) as http:
        await sign_in(http, ADMIN_EMAIL)
        assert "sh_session" in http.cookies
        for path in ("/admin/users", "/admin/sessions", "/admin/audit", "/admin/admins"):
            assert (await http.get(path)).status_code == 404, path
        assert (await http.get("/admin/me/sessions")).status_code == 404
        assert (await http.get("/admin/me")).status_code == 401
        # The sign-in routes stay reachable.
        assert (await http.get("/admin/auth/providers")).status_code == 200


async def test_aa4_forged_or_removed_admin_cookie_is_refused(
    admin: httpx.AsyncClient, app: FastAPI, sessionmaker: Maker
) -> None:
    async with _client(app) as http:
        http.cookies.set(ADMIN_COOKIE, "not-a-real-token")
        assert (await http.get("/admin/users")).status_code == 404
    assert (await admin.get("/admin/users")).status_code == 200
    await _disable(sessionmaker, ADMIN_EMAIL)  # removed without revoking: still refused
    assert (await admin.get("/admin/users")).status_code == 404


# ----------------------------------------------------------------------------------- AA-8


async def test_aa8_list_and_revoke_my_sessions(
    admin: httpx.AsyncClient, app: FastAPI, sessionmaker: Maker
) -> None:
    async with _client(app, **{"user-agent": "laptop"}) as other:
        await sign_in_admin(other, app, make=False)
        mine = (await admin.get("/admin/me/sessions")).json()
        assert len(mine) == 2
        current = [s for s in mine if s["current"]]
        assert len(current) == 1 and current[0]["user_agent"] == "pytest-admin"
        [laptop] = [s for s in mine if not s["current"]]
        assert laptop["user_agent"] == "laptop"

        path = f"/admin/me/sessions/{laptop['id']}"
        assert (await admin.delete(path)).status_code == 403  # AA-5 header
        assert (await admin.delete(path, headers=HEADERS)).status_code == 204
        assert (await other.get("/admin/me")).status_code == 401
        assert (await admin.delete(path, headers=HEADERS)).status_code == 404
        assert len((await admin.get("/admin/me/sessions")).json()) == 1

    # Another admin's session cannot be revoked through my list.
    async with _client(app) as ops:
        await sign_in_admin(ops, app, "ops@example.com")
        [theirs] = (await ops.get("/admin/me/sessions")).json()
        resp = await admin.delete(f"/admin/me/sessions/{theirs['id']}", headers=HEADERS)
        assert resp.status_code == 404
        assert (await ops.get("/admin/me")).status_code == 200

    async with sessionmaker() as db:
        log = await db.scalar(select(AuditLog).where(AuditLog.action == "admin.session_revoked"))
    assert log is not None and log.actor == ADMIN_EMAIL


async def test_aa8_revoking_the_current_session_signs_me_out(admin: httpx.AsyncClient) -> None:
    [me] = (await admin.get("/admin/me/sessions")).json()
    resp = await admin.delete(f"/admin/me/sessions/{me['id']}", headers=HEADERS)
    assert resp.status_code == 204
    assert (await admin.get("/admin/me")).status_code == 401


async def test_aa8_settings_admins_add_and_remove(
    admin: httpx.AsyncClient, app: FastAPI, sessionmaker: Maker
) -> None:
    body = {"email": "Ops@Example.com", "reason": "new on-call admin"}
    assert (await admin.post("/admin/admins", json=body)).status_code == 403  # AA-5
    added = await admin.post("/admin/admins", json=body, headers=HEADERS)
    assert added.status_code == 201, added.text
    ops = added.json()
    assert ops["email"] == "ops@example.com" and ops["added_by"] == ADMIN_EMAIL
    dup = await admin.post("/admin/admins", json=body, headers=HEADERS)
    assert dup.status_code == 409
    assert (
        await admin.post("/admin/admins", json={"email": "x@example.com"}, headers=HEADERS)
    ).status_code == 422

    async with _client(app) as other:
        await sign_in_admin(other, app, "ops@example.com", make=False)
        listed = {a["email"]: a for a in (await admin.get("/admin/admins")).json()}
        assert listed["ops@example.com"]["live_sessions"] == 1

        me = listed[ADMIN_EMAIL]
        self_remove = await admin.request(
            "DELETE", f"/admin/admins/{me['id']}", json={"reason": "oops"}, headers=HEADERS
        )
        assert self_remove.status_code == 409

        removed = await admin.request(
            "DELETE",
            f"/admin/admins/{ops['id']}",
            json={"reason": "left the team"},
            headers=HEADERS,
        )
        assert removed.status_code == 200 and removed.json()["disabled_at"] is not None
        assert (await other.get("/admin/me")).status_code == 401  # their sessions ended
        links_to_ops = sum(1 for to, _ in _sender(app).sent if to == "ops@example.com")
        resent = await other.post("/admin/auth/link", json={"email": "ops@example.com"})
        assert resent.status_code == 202  # same reply, but no link for a removed admin
        assert sum(1 for to, _ in _sender(app).sent if to == "ops@example.com") == links_to_ops

    missing = await admin.request(
        "DELETE", f"/admin/admins/{uuid.uuid4()}", json={"reason": "nobody"}, headers=HEADERS
    )
    assert missing.status_code == 404
    listed_after = (await admin.get("/admin/admins")).json()
    assert [a["email"] for a in listed_after] == [ADMIN_EMAIL, "ops@example.com"]

    async with sessionmaker() as db:
        logs = list(await db.scalars(select(AuditLog).where(AuditLog.action.like("admin.admin_%"))))
    by_action = {log.action: log for log in logs}
    assert by_action["admin.admin_added"].details_json["reason"] == "new on-call admin"
    removed_log = by_action["admin.admin_removed"].details_json
    assert removed_log["reason"] == "left the team" and removed_log["sessions_revoked"] == 1


async def test_aa8_admins_routes_are_404_for_non_admins(client: httpx.AsyncClient) -> None:
    assert (await client.get("/admin/admins")).status_code == 404
    body = {"email": "me@example.com", "reason": "let me in"}
    assert (await client.post("/admin/admins", json=body, headers=HEADERS)).status_code == 404


async def test_aa3_signing_in_again_replaces_the_old_session(
    admin: httpx.AsyncClient, app: FastAPI, sessionmaker: Maker
) -> None:
    await sign_in_admin(admin, app, make=False)
    rows = await _sessions(sessionmaker)
    assert len(rows) == 2
    assert sorted(r.revoked_at is None for r in rows) == [False, True]
    assert len((await admin.get("/admin/me/sessions")).json()) == 1
