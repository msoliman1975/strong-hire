"""Admin sign-in and sessions on the admin host (AA-2, AA-3, AA-8).

    GET    /admin/auth/providers         which sign-in methods are on
    POST   /admin/auth/password          email and password (the admin's AC-4 user account)
    POST   /admin/auth/link              email a sign-in link, to active admins only
    POST   /admin/auth/link/verify       the admin app posts the token from that link
    GET    /admin/auth/google/login      Google OAuth, with the callback on the admin host
    GET    /admin/auth/google/callback
    POST   /admin/auth/signout           revoke this session and clear the cookie
    GET    /admin/me                     the signed-in admin; 401 when there is none
    GET    /admin/me/sessions            my live sessions
    DELETE /admin/me/sessions/{id}       revoke one of them

Every method checks `admin_users` (AA-1); a removed admin cannot sign in. Sign-in creates an
`admin_sessions` row and sets the `sh_admin` cookie: host-only, HttpOnly, SameSite=Strict, path
/, and Secure outside local and test. These routes and /admin/me answer without an admin
session, so the admin app can sign in; everything else under /admin stays 404 (AA-4).

The email link points at the admin app (`ADMIN_BASE_URL/signin/verify?token=...`), which posts
the token here. A link opened by a mail scanner therefore does not use it up, and the cookie is
set by a same-site request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from strong_api.admin.actions import AdminWrite, audit_action
from strong_api.admin.deps import Admin, OptionalAdmin, admin_auth
from strong_api.admin.identity import (
    ABSOLUTE_TIMEOUT,
    ADMIN_COOKIE,
    AdminAuth,
    AdminPrincipal,
    as_utc,
    create_session,
    find_active_admin,
    hash_token,
    live_sessions,
    revoke_session,
    session_ends_at,
)
from strong_api.auth.deps import DbSession
from strong_api.auth.google import GoogleSignInError
from strong_api.auth.magic_links import InvalidMagicLinkError
from strong_api.auth.passwords import MAX_LENGTH, verify_password
from strong_api.auth.users import find_user, normalize_email
from strong_core.db.models import AdminUser as AdminUserRow

router = APIRouter(prefix="/admin", tags=["admin-auth"])

AdminAuthDep = Annotated[AdminAuth, Depends(admin_auth)]

WRONG_PASSWORD = "The email or password is wrong."


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminProviders(BaseModel):
    google: bool
    email: bool = True
    password: bool = True


class AdminPasswordIn(_Body):
    email: EmailStr
    password: str = Field(max_length=MAX_LENGTH)


class AdminLinkIn(_Body):
    email: EmailStr


class AdminLinkSent(BaseModel):
    sent: bool = Field(description="Always true, so the reply does not say who is an admin.")
    dev_link: str | None = Field(
        default=None, description="Only when APP_ENV=local and a link was sent."
    )


class AdminLinkVerifyIn(_Body):
    token: str = Field(max_length=2000)


class AdminMe(BaseModel):
    id: str
    email: str
    session_expires_at: datetime = Field(
        description="When this session ends unless it is used again (idle 2 h, absolute 12 h)."
    )


class AdminSignInSession(BaseModel):
    """AA-8: one of my admin sessions."""

    id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime = Field(description="The absolute end, 12 h after sign-in.")
    ends_at: datetime = Field(description="When it ends unless it is used again.")
    ip: str | None
    user_agent: str | None
    current: bool = Field(description="The session of this request.")


def _me(admin: AdminPrincipal) -> AdminMe:
    return AdminMe(id=str(admin.id), email=admin.email, session_expires_at=admin.session_expires_at)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def set_admin_cookie(response: Response, auth: AdminAuth, token: str) -> None:
    """AA-3: host-only (no Domain), HttpOnly, SameSite=Strict, Secure outside local/test."""
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=int(ABSOLUTE_TIMEOUT.total_seconds()),
        path="/",
        secure=auth.secure_cookie,
        httponly=True,
        samesite="strict",
    )


def clear_admin_cookie(response: Response, auth: AdminAuth) -> None:
    response.delete_cookie(
        ADMIN_COOKIE, path="/", secure=auth.secure_cookie, httponly=True, samesite="strict"
    )


async def _start(
    request: Request, response: Response, db: DbSession, auth: AdminAuth, admin: AdminUserRow
) -> AdminMe:
    now = auth.clock()
    old = request.cookies.get(ADMIN_COOKIE)
    if old:  # a new sign-in replaces this browser's old session
        await revoke_session(db, hash_token(old), now)
    token, row = await create_session(
        db, admin, now, ip=_client_ip(request), user_agent=request.headers.get("user-agent")
    )
    set_admin_cookie(response, auth, token)
    principal = AdminPrincipal(
        id=admin.id, email=admin.email, session_id=row.id, session_expires_at=session_ends_at(row)
    )
    return _me(principal)


def _admin_url(auth: AdminAuth, path: str, **query: str) -> str:
    url = auth.settings.admin_base_url.rstrip("/") + path
    return url + ("?" + urlencode(query) if query else "")


@router.get("/auth/providers")
async def admin_providers(auth: AdminAuthDep) -> AdminProviders:
    return AdminProviders(google=auth.google is not None)


@router.post("/auth/password")
async def admin_password_sign_in(
    body: AdminPasswordIn, request: Request, response: Response, db: DbSession, auth: AdminAuthDep
) -> AdminMe:
    """AA-2: the admin's user account password (AC-4). The account's email must be confirmed,
    so a password set by someone who never proved the inbox cannot open the admin app."""
    email = normalize_email(str(body.email))
    key = f"admin:{email}"
    if await auth.throttle.blocked(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong passwords. Wait 15 minutes."
        )
    admin = await find_active_admin(db, email)
    user = await find_user(db, email) if admin is not None else None
    hashed = user.password_hash if user is not None else None
    ok = verify_password(hashed, body.password)  # runs even without a hash, for even timing
    if admin is None or user is None or user.email_verified_at is None or not ok:
        await auth.throttle.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, WRONG_PASSWORD)
    await auth.throttle.reset(key)
    return await _start(request, response, db, auth, admin)


@router.post("/auth/link", status_code=status.HTTP_202_ACCEPTED)
async def admin_send_link(body: AdminLinkIn, db: DbSession, auth: AdminAuthDep) -> AdminLinkSent:
    """AA-2: a sign-in link goes only to an active admin. The reply is the same either way."""
    email = normalize_email(str(body.email))
    if await find_active_admin(db, email) is None:
        return AdminLinkSent(sent=True)
    link = _admin_url(auth, "/signin/verify") + f"?token={quote(auth.links.issue(email))}"
    await auth.email_sender.send_magic_link(email, link)
    return AdminLinkSent(sent=True, dev_link=link if auth.settings.is_local else None)


@router.post("/auth/link/verify")
async def admin_verify_link(
    body: AdminLinkVerifyIn,
    request: Request,
    response: Response,
    db: DbSession,
    auth: AdminAuthDep,
) -> AdminMe:
    try:
        email = await auth.links.redeem(body.token)
    except InvalidMagicLinkError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"link_{exc}") from exc
    admin = await find_active_admin(db, email)
    if admin is None:  # removed after the link was sent
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "link_invalid")
    return await _start(request, response, db, auth, admin)


@router.get("/auth/google/login")
async def admin_google_login(request: Request, auth: AdminAuthDep) -> Response:
    if auth.google is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")
    redirect_uri = _admin_url(auth, "/api/admin/auth/google/callback")
    return await auth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def admin_google_callback(request: Request, db: DbSession, auth: AdminAuthDep) -> Response:
    if auth.google is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")
    try:
        identity = await auth.google.fetch_identity(request)
    except GoogleSignInError:
        return RedirectResponse(_admin_url(auth, "/signin", error="google"), status_code=303)
    admin = await find_active_admin(db, identity.email)
    if admin is None:
        return RedirectResponse(_admin_url(auth, "/signin", error="not_admin"), status_code=303)
    redirect = RedirectResponse(_admin_url(auth, "/"), status_code=303)
    await _start(request, redirect, db, auth, admin)
    return redirect


@router.post("/auth/signout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_sign_out(request: Request, db: DbSession, auth: AdminAuthDep) -> Response:
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        await revoke_session(db, hash_token(token), auth.clock())
        await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_admin_cookie(response, auth)
    return response


@router.get("/me", responses={401: {"description": "No admin session"}})
async def admin_me(admin: OptionalAdmin) -> AdminMe:
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    return _me(admin)


@router.get("/me/sessions")
async def my_sessions(admin: Admin, db: DbSession, auth: AdminAuthDep) -> list[AdminSignInSession]:
    """AA-8: my live sessions, newest first."""
    rows = await live_sessions(db, admin.id, auth.clock())
    return [
        AdminSignInSession(
            id=r.id,
            created_at=as_utc(r.created_at),
            last_seen_at=as_utc(r.last_seen_at),
            expires_at=as_utc(r.expires_at),
            ends_at=session_ends_at(r),
            ip=r.ip,
            user_agent=r.user_agent,
            current=r.id == admin.session_id,
        )
        for r in rows
    ]


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: str, admin: AdminWrite, db: DbSession, auth: AdminAuthDep
) -> Response:
    """AA-8: revoke one of my sessions (the current one too: that signs me out)."""
    mine = {r.id for r in await live_sessions(db, admin.id, auth.clock())}
    if session_id not in mine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session")
    await revoke_session(db, session_id, auth.clock())
    audit_action(
        db,
        admin,
        "admin.session_revoked",
        f"admin_session:{session_id[:12]}",
        reason="Revoked my own session",
        details={"current": session_id == admin.session_id},
    )
    await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if session_id == admin.session_id:
        clear_admin_cookie(response, auth)
    return response
