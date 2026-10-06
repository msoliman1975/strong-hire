"""Sign-in routes: Google OAuth, email magic links, and a dev login that exists only locally.

Flow: any sign-in method ends in `_finish_sign_in`. A known email is signed in. An unknown email
becomes a pending sign-up, and the web app asks for the 18+ confirmation, the terms and the
training-data consent (AC-2, default off) before POST /auth/signup creates the user.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote, urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from strong_api.auth.deps import (
    SESSION_PENDING_KEY,
    SESSION_USER_KEY,
    DbSession,
    optional_user,
)
from strong_api.auth.email import EmailSender
from strong_api.auth.google import GoogleClient, GoogleSignInError
from strong_api.auth.magic_links import InvalidMagicLinkError, MagicLinks
from strong_api.auth.settings import AuthSettings
from strong_api.auth.users import create_user, find_user, normalize_email
from strong_core.db.models import User
from strong_core.schemas import AuthProvider

_DEV_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")

OptionalUser = Annotated[User | None, Depends(optional_user)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthUser(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    auth_provider: AuthProvider
    training_consent: bool
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> AuthUser:
        return cls(
            id=user.id,
            org_id=user.org_id,
            email=user.email,
            auth_provider=user.auth_provider,
            training_consent=user.training_consent,
            created_at=user.created_at,
        )


class AuthState(BaseModel):
    status: Literal["signed_out", "needs_signup", "signed_in"]
    email: str | None = Field(default=None, description="Set for needs_signup and signed_in.")
    user: AuthUser | None = None


class AuthProviders(BaseModel):
    google: bool
    email: bool
    dev: bool


class MagicLinkRequest(_Body):
    email: EmailStr


class MagicLinkSent(BaseModel):
    sent: bool
    dev_link: str | None = Field(
        default=None, description="Only when APP_ENV=local, so no email server is needed."
    )


class DevLoginRequest(_Body):
    email: str = Field(default="dev@example.com", max_length=320)


class SignupRequest(_Body):
    age_confirmed: bool = Field(description="The user confirmed they are 18 or older.")
    terms_accepted: bool
    training_consent: bool = Field(default=False, description="AC-2: off unless the user opts in.")


def _state(request: Request, user: User | None) -> AuthState:
    if user is not None:
        return AuthState(status="signed_in", email=user.email, user=AuthUser.of(user))
    pending = request.session.get(SESSION_PENDING_KEY)
    if isinstance(pending, dict) and isinstance(pending.get("email"), str):
        return AuthState(status="needs_signup", email=pending["email"])
    return AuthState(status="signed_out")


async def _finish_sign_in(
    request: Request, db: DbSession, email: str, provider: AuthProvider
) -> AuthState:
    email = normalize_email(email)
    user = await find_user(db, email)
    # Start a fresh session on every sign-in so an old cookie cannot carry over.
    request.session.clear()
    if user is not None:
        request.session[SESSION_USER_KEY] = str(user.id)
    else:
        request.session[SESSION_PENDING_KEY] = {"email": email, "provider": provider.value}
    return _state(request, user)


def build_router(
    settings: AuthSettings,
    magic_links: MagicLinks,
    email_sender: EmailSender,
    google: GoogleClient | None,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    def web_redirect(path: str, **query: str) -> RedirectResponse:
        url = settings.web_base_url.rstrip("/") + path
        if query:
            url += "?" + urlencode(query)
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)

    def after_sign_in(state: AuthState) -> RedirectResponse:
        return web_redirect("/" if state.status == "signed_in" else "/signup")

    @router.get("/providers")
    async def providers() -> AuthProviders:
        return AuthProviders(google=google is not None, email=True, dev=settings.is_local)

    @router.get("/me")
    async def me(request: Request, user: OptionalUser) -> AuthState:
        return _state(request, user)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request) -> Response:
        request.session.clear()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
    async def send_magic_link(body: MagicLinkRequest) -> MagicLinkSent:
        email = normalize_email(str(body.email))
        token = magic_links.issue(email)
        link = (
            f"{settings.api_public_url.rstrip('/')}/auth/magic-link/callback?token={quote(token)}"
        )
        await email_sender.send_magic_link(email, link)
        # The reply is the same for known and unknown emails, so it does not reveal accounts.
        return MagicLinkSent(sent=True, dev_link=link if settings.is_local else None)

    @router.get("/magic-link/callback")
    async def magic_link_callback(request: Request, db: DbSession, token: str) -> Response:
        try:
            email = await magic_links.redeem(token)
        except InvalidMagicLinkError as exc:
            return web_redirect("/signin", error=f"link_{exc}")
        return after_sign_in(await _finish_sign_in(request, db, email, AuthProvider.EMAIL))

    @router.get("/google/login")
    async def google_login(request: Request) -> Response:
        if google is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")
        redirect_uri = f"{settings.api_public_url.rstrip('/')}/auth/google/callback"
        return await google.authorize_redirect(request, redirect_uri)

    @router.get("/google/callback")
    async def google_callback(request: Request, db: DbSession) -> Response:
        if google is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")
        try:
            identity = await google.fetch_identity(request)
        except GoogleSignInError:
            return web_redirect("/signin", error="google")
        return after_sign_in(
            await _finish_sign_in(request, db, identity.email, AuthProvider.GOOGLE)
        )

    @router.post("/signup")
    async def signup(request: Request, db: DbSession, body: SignupRequest) -> AuthState:
        if request.session.get(SESSION_USER_KEY):
            raise HTTPException(status.HTTP_409_CONFLICT, "Already signed in")
        pending = request.session.get(SESSION_PENDING_KEY)
        if not isinstance(pending, dict) or not isinstance(pending.get("email"), str):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
        if not body.age_confirmed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You must be 18 or older")
        if not body.terms_accepted:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Accept the terms first")
        user = await find_user(db, pending["email"])
        if user is None:
            user = await create_user(
                db,
                email=pending["email"],
                provider=AuthProvider(pending["provider"]),
                age_confirmed=body.age_confirmed,
                terms_accepted=body.terms_accepted,
                training_consent=body.training_consent,
            )
        request.session.clear()
        request.session[SESSION_USER_KEY] = str(user.id)
        return _state(request, user)

    if settings.is_local:

        @router.post("/dev-login")
        async def dev_login(request: Request, db: DbSession, body: DevLoginRequest) -> AuthState:
            """Local only (APP_ENV=local). Signs in any email with no check."""
            if not _DEV_EMAIL.match(body.email):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Not an email address")
            return await _finish_sign_in(request, db, body.email, AuthProvider.DEV)

    return router
