"""Sign-in routes: email and password, email magic links, Google OAuth, and a dev login that
exists only locally.

Link and OAuth flow: `_finish_sign_in`. A known email is signed in. An unknown email becomes a
pending sign-up, and the web app asks for the 18+ confirmation, the terms and the training-data
consent (AC-2, default off) before POST /auth/signup creates the user.

Password flow (AC-4): POST /auth/password/signup takes the confirmations with the password,
creates an unverified user and emails a confirmation link. Password sign-in works once the link
is opened. A link or Google sign-in also proves the email; for an unverified user it removes the
password, because nobody proved that the person who chose it owns the email.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
from strong_api.auth.passwords import (
    MAX_LENGTH,
    LoginThrottle,
    fingerprint,
    hash_password,
    needs_rehash,
    password_problem,
    verify_password,
)
from strong_api.auth.settings import AuthSettings
from strong_api.auth.users import create_user, find_user, normalize_email
from strong_core.db.models import AuditLog, User
from strong_core.schemas import AuthProvider

_DEV_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")

SignInApp = Literal["web", "admin"]
"""Which app started a link or Google sign-in (D-1). The callback runs on that app's host, so the
host-only session cookie is set there, and the browser returns to that app."""

_SESSION_APP_KEY = "sign_in_app"

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
    is_admin: bool = Field(
        default=False, description="True for ADMIN_EMAILS users: the web app shows Admin."
    )
    full_name: str | None = Field(default=None, description="AC-3 profile name.")
    profile_complete: bool = Field(
        default=False, description="AC-3: false until the user saves the first sign-in profile."
    )

    @classmethod
    def of(cls, user: User, *, is_admin: bool = False) -> AuthUser:
        return cls(
            id=user.id,
            org_id=user.org_id,
            email=user.email,
            auth_provider=user.auth_provider,
            training_consent=user.training_consent,
            created_at=user.created_at,
            is_admin=is_admin,
            full_name=user.full_name,
            profile_complete=user.profile_completed_at is not None,
        )


class AuthState(BaseModel):
    status: Literal["signed_out", "needs_signup", "signed_in"]
    email: str | None = Field(default=None, description="Set for needs_signup and signed_in.")
    user: AuthUser | None = None


class AuthProviders(BaseModel):
    google: bool
    email: bool
    password: bool = Field(default=True, description="AC-4 email and password sign-in")
    dev: bool


class MagicLinkRequest(_Body):
    email: EmailStr


class MagicLinkSent(BaseModel):
    sent: bool
    dev_link: str | None = Field(
        default=None, description="Only when APP_ENV=local, so no email server is needed."
    )


class PasswordSignupRequest(_Body):
    email: EmailStr
    password: str = Field(max_length=MAX_LENGTH)
    full_name: str | None = Field(default=None, max_length=120)
    age_confirmed: bool = Field(description="The user confirmed they are 18 or older.")
    terms_accepted: bool
    training_consent: bool = Field(default=False, description="AC-2: off unless the user opts in.")


class PasswordLoginRequest(_Body):
    email: EmailStr
    password: str = Field(max_length=MAX_LENGTH)


class EmailOnlyRequest(_Body):
    email: EmailStr


class PasswordResetRequest(_Body):
    token: str = Field(max_length=2000)
    password: str = Field(max_length=MAX_LENGTH)


class EmailSent(BaseModel):
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


_RESET_ERRORS = {
    "expired": "That reset link has expired. Ask for a new one.",
    "used": "That reset link was already used. Ask for a new one.",
    "invalid": "That reset link is not valid. Ask for a new one.",
}


def _state(request: Request, user: User | None, settings: AuthSettings) -> AuthState:
    if user is not None:
        user_out = AuthUser.of(user, is_admin=settings.is_admin(user.email))
        return AuthState(status="signed_in", email=user.email, user=user_out)
    pending = request.session.get(SESSION_PENDING_KEY)
    if isinstance(pending, dict) and isinstance(pending.get("email"), str):
        return AuthState(status="needs_signup", email=pending["email"])
    return AuthState(status="signed_out")


async def _sign_in_user(request: Request, db: DbSession, user: User) -> None:
    # Start a fresh session on every sign-in so an old cookie cannot carry over.
    request.session.clear()
    request.session[SESSION_USER_KEY] = str(user.id)
    user.last_sign_in_at = datetime.now(UTC)
    await db.commit()


async def _finish_sign_in(
    request: Request, db: DbSession, email: str, provider: AuthProvider, settings: AuthSettings
) -> AuthState:
    email = normalize_email(email)
    user = await find_user(db, email)
    if user is not None:
        if user.email_verified_at is None:
            # The link or Google proves the email. A password set before that is not trusted.
            user.email_verified_at = datetime.now(UTC)
            user.password_hash = None
        await _sign_in_user(request, db, user)
    else:
        request.session.clear()
        request.session[SESSION_PENDING_KEY] = {"email": email, "provider": provider.value}
    return _state(request, user, settings)


def build_router(
    settings: AuthSettings,
    magic_links: MagicLinks,
    email_sender: EmailSender,
    google: GoogleClient | None,
    *,
    confirm_links: MagicLinks,
    reset_links: MagicLinks,
    throttle: LoginThrottle,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    def api_link(path: str, token: str) -> str:
        return f"{settings.api_public_url.rstrip('/')}{path}?token={quote(token)}"

    def web_link(path: str, **query: str) -> str:
        url = settings.web_base_url.rstrip("/") + path
        return url + ("?" + urlencode(query) if query else "")

    async def send_confirmation(user: User) -> str:
        token = confirm_links.issue(user.email, ph=fingerprint(user.password_hash))
        link = api_link("/auth/password/confirm", token)
        await email_sender.send_email_confirmation(user.email, link)
        return link

    def app_api(app: SignInApp) -> str:
        """The API as the browser sees it on the host of `app`."""
        if app == "admin":
            return settings.admin_base_url.rstrip("/") + "/api"
        return settings.api_public_url.rstrip("/")

    def web_redirect(path: str, app: SignInApp = "web", **query: str) -> RedirectResponse:
        base = settings.admin_base_url if app == "admin" else settings.web_base_url
        url = base.rstrip("/") + path
        if query:
            url += "?" + urlencode(query)
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)

    def after_sign_in(state: AuthState, app: SignInApp = "web") -> RedirectResponse:
        # The admin app has no sign-up: it shows "not found" to anyone who is not an admin.
        if app == "admin":
            return web_redirect("/", app)
        return web_redirect("/" if state.status == "signed_in" else "/signup")

    @router.get("/providers")
    async def providers() -> AuthProviders:
        return AuthProviders(google=google is not None, email=True, dev=settings.is_local)

    @router.get("/me")
    async def me(request: Request, user: OptionalUser) -> AuthState:
        return _state(request, user, settings)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request) -> Response:
        request.session.clear()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
    async def send_magic_link(body: MagicLinkRequest, app: SignInApp = "web") -> MagicLinkSent:
        email = normalize_email(str(body.email))
        token = magic_links.issue(email)
        link = f"{app_api(app)}/auth/magic-link/callback?token={quote(token)}"
        if app == "admin":
            link += "&app=admin"
        await email_sender.send_magic_link(email, link)
        # The reply is the same for known and unknown emails, so it does not reveal accounts.
        return MagicLinkSent(sent=True, dev_link=link if settings.is_local else None)

    @router.get("/magic-link/callback")
    async def magic_link_callback(
        request: Request, db: DbSession, token: str, app: SignInApp = "web"
    ) -> Response:
        try:
            email = await magic_links.redeem(token)
        except InvalidMagicLinkError as exc:
            return web_redirect("/signin", app, error=f"link_{exc}")
        return after_sign_in(
            await _finish_sign_in(request, db, email, AuthProvider.EMAIL, settings), app
        )

    @router.get("/google/login")
    async def google_login(request: Request, app: SignInApp = "web") -> Response:
        if google is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")
        request.session[_SESSION_APP_KEY] = app
        redirect_uri = f"{app_api(app)}/auth/google/callback"
        return await google.authorize_redirect(request, redirect_uri)

    @router.get("/google/callback")
    async def google_callback(request: Request, db: DbSession) -> Response:
        if google is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")
        app: SignInApp = "admin" if request.session.get(_SESSION_APP_KEY) == "admin" else "web"
        try:
            identity = await google.fetch_identity(request)
        except GoogleSignInError:
            return web_redirect("/signin", app, error="google")
        return after_sign_in(
            await _finish_sign_in(request, db, identity.email, AuthProvider.GOOGLE, settings), app
        )

    # ------------------------------------------------------------ email and password (AC-4)

    @router.post("/password/signup", status_code=status.HTTP_202_ACCEPTED)
    async def password_signup(db: DbSession, body: PasswordSignupRequest) -> EmailSent:
        """AC-4: create an account with a password. The reply is the same for a new email and
        a taken one, so it does not reveal accounts; the owner of a taken email gets a note."""
        if not body.age_confirmed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You must be 18 or older")
        if not body.terms_accepted:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Accept the terms first")
        email = normalize_email(str(body.email))
        problem = password_problem(body.password, email)
        if problem:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
        full_name = (body.full_name or "").strip() or None
        user = await find_user(db, email)
        if user is not None and user.email_verified_at is not None:
            await email_sender.send_account_exists(email, web_link("/signin"))
            return EmailSent(sent=True)
        if user is None:
            user = await create_user(
                db,
                email=email,
                provider=AuthProvider.PASSWORD,
                age_confirmed=body.age_confirmed,
                terms_accepted=body.terms_accepted,
                training_consent=body.training_consent,
                email_verified=False,
                password_hash=hash_password(body.password),
                full_name=full_name,
            )
        else:
            # Not confirmed yet: the latest sign-up wins, and older links stop working.
            user.password_hash = hash_password(body.password)
            user.full_name = full_name or user.full_name
            user.training_consent = body.training_consent
            await db.commit()
        link = await send_confirmation(user)
        return EmailSent(sent=True, dev_link=link if settings.is_local else None)

    @router.post("/password/resend", status_code=status.HTTP_202_ACCEPTED)
    async def resend_confirmation(db: DbSession, body: EmailOnlyRequest) -> EmailSent:
        user = await find_user(db, str(body.email))
        if user is None or user.email_verified_at is not None or not user.password_hash:
            return EmailSent(sent=True)
        link = await send_confirmation(user)
        return EmailSent(sent=True, dev_link=link if settings.is_local else None)

    @router.get("/password/confirm")
    async def confirm_email(request: Request, db: DbSession, token: str) -> Response:
        try:
            data = confirm_links.peek(token)
        except InvalidMagicLinkError as exc:
            return web_redirect("/signin", error=f"link_{exc}")
        user = await find_user(db, data["email"])
        if user is None or data.get("ph") != fingerprint(user.password_hash):
            return web_redirect("/signin", error="link_invalid")
        try:
            await confirm_links.redeem_data(token)
        except InvalidMagicLinkError as exc:
            if str(exc) == "used" and user.email_verified_at is not None:
                # Opened twice: the account is confirmed, so send them to sign in.
                return web_redirect("/signin", confirmed="1")
            return web_redirect("/signin", error=f"link_{exc}")
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
        await _sign_in_user(request, db, user)
        return web_redirect("/")

    @router.post("/password/login")
    async def password_login(
        request: Request, db: DbSession, body: PasswordLoginRequest
    ) -> AuthState:
        email = normalize_email(str(body.email))
        if await throttle.blocked(email):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many wrong passwords. Wait 15 minutes, or reset your password.",
            )
        user = await find_user(db, email)
        hashed = user.password_hash if user is not None else None
        if user is None or not verify_password(hashed, body.password):
            await throttle.fail(email)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The email or password is wrong.")
        await throttle.reset(email)
        if user.email_verified_at is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Confirm your email first. Open the link we sent you, or ask for a new one.",
            )
        if hashed and needs_rehash(hashed):
            user.password_hash = hash_password(body.password)
        await _sign_in_user(request, db, user)
        return _state(request, user, settings)

    @router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
    async def forgot_password(db: DbSession, body: EmailOnlyRequest) -> EmailSent:
        """AC-5: email a reset link. Same reply whether or not the email has an account."""
        user = await find_user(db, str(body.email))
        if user is None:
            return EmailSent(sent=True)
        token = reset_links.issue(user.email, ph=fingerprint(user.password_hash))
        link = web_link("/reset-password", token=token)
        await email_sender.send_password_reset(user.email, link)
        return EmailSent(sent=True, dev_link=link if settings.is_local else None)

    @router.post("/password/reset")
    async def reset_password(
        request: Request, db: DbSession, body: PasswordResetRequest
    ) -> AuthState:
        """AC-5: set a new password from a reset link, and sign in."""
        try:
            data = reset_links.peek(body.token)
        except InvalidMagicLinkError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _RESET_ERRORS[str(exc)]) from exc
        user = await find_user(db, data["email"])
        if user is None or data.get("ph") != fingerprint(user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _RESET_ERRORS["invalid"])
        problem = password_problem(body.password, user.email)
        if problem:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
        try:
            await reset_links.redeem_data(body.token)
        except InvalidMagicLinkError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _RESET_ERRORS[str(exc)]) from exc
        user.password_hash = hash_password(body.password)
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)  # the link came to this inbox
        db.add(
            AuditLog(
                org_id=user.org_id,
                actor=user.email,
                action="user.password_reset",
                entity=f"user:{user.id}",
                details_json={},
            )
        )
        await throttle.reset(user.email)
        await _sign_in_user(request, db, user)
        return _state(request, user, settings)

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
        user.last_sign_in_at = datetime.now(UTC)
        await db.commit()
        request.session.clear()
        request.session[SESSION_USER_KEY] = str(user.id)
        return _state(request, user, settings)

    if settings.is_local:

        @router.post("/dev-login")
        async def dev_login(request: Request, db: DbSession, body: DevLoginRequest) -> AuthState:
            """Local only (APP_ENV=local). Signs in any email with no check."""
            if not _DEV_EMAIL.match(body.email):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Not an email address")
            return await _finish_sign_in(request, db, body.email, AuthProvider.DEV, settings)

    return router
