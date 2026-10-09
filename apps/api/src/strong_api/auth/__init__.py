"""Sign-in for the API (P3). `install_auth(app)` adds the session cookie and the /auth routes.

Other routers get the signed-in user with `CurrentUser` (or `Depends(require_user)`).
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from strong_api.auth.deps import CurrentUser, get_db, optional_user, require_user
from strong_api.auth.email import EmailSender, make_email_sender
from strong_api.auth.google import AuthlibGoogleClient, GoogleClient
from strong_api.auth.magic_links import MagicLinks, RedisUsedTokenStore
from strong_api.auth.router import build_router
from strong_api.auth.settings import AppEnv, AuthSettings, get_auth_settings
from strong_api.auth.sim import build_sim_router
from strong_core.config import get_settings

SESSION_COOKIE = "sh_session"


def install_auth(
    app: FastAPI,
    settings: AuthSettings | None = None,
    *,
    magic_links: MagicLinks | None = None,
    email_sender: EmailSender | None = None,
    google: GoogleClient | None = None,
) -> None:
    settings = settings or get_auth_settings()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie=SESSION_COOKIE,
        max_age=settings.session_max_age_s,
        same_site="lax",
        https_only=not settings.is_local and settings.app_env != AppEnv.TEST,
    )
    if magic_links is None:
        magic_links = MagicLinks(
            settings.session_secret,
            settings.magic_link_max_age_s,
            RedisUsedTokenStore(get_settings().redis_url),
        )
    if google is None and settings.google_enabled:
        google = AuthlibGoogleClient(settings)
    app.include_router(
        build_router(settings, magic_links, email_sender or make_email_sender(settings), google)
    )
    app.include_router(build_sim_router(settings))  # 404 unless SIM_ENABLED (P13)


__all__ = [
    "AuthSettings",
    "CurrentUser",
    "get_db",
    "install_auth",
    "optional_user",
    "require_user",
]
