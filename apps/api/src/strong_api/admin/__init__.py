"""Admin area (R2, docs/admin-spec.md). `install_admin(app)` adds the /admin routes for admins.

Each feature has its own sub-router module with prefix "/admin"; add it to ROUTERS.
Admins sign in on the admin host with their own server-side session (strong_api.admin.auth,
AA-1 to AA-4); `seed_admins_on_startup` fills `admin_users` from ADMIN_EMAILS the first time."""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

from strong_api.admin.admins import router as admins_router
from strong_api.admin.alerts import router as alerts_router
from strong_api.admin.auth import router as auth_router
from strong_api.admin.auto_profiles import router as auto_profiles_router
from strong_api.admin.content import router as content_router
from strong_api.admin.controls import router as controls_router
from strong_api.admin.identity import ADMIN_LINK_SALT, AdminAuth, seed_admins
from strong_api.admin.ops import router as ops_router
from strong_api.admin.overview import router as overview_router
from strong_api.admin.part1 import router as part1_router
from strong_api.admin.router import router
from strong_api.admin.sim import router as sim_router
from strong_api.admin.users import router as users_router
from strong_api.admin.waitlist import router as waitlist_router
from strong_api.auth.email import EmailSender, make_email_sender
from strong_api.auth.google import AuthlibGoogleClient, GoogleClient
from strong_api.auth.magic_links import MagicLinks, RedisUsedTokenStore
from strong_api.auth.passwords import LoginThrottle, RedisLoginThrottle
from strong_api.auth.settings import AuthSettings, get_auth_settings
from strong_core.config import get_settings

log = logging.getLogger(__name__)

ROUTERS: list[APIRouter] = [
    auth_router,
    admins_router,
    router,
    controls_router,
    alerts_router,
    users_router,
    overview_router,
    ops_router,
    content_router,
    sim_router,
    waitlist_router,
    part1_router,
    auto_profiles_router,
]


def install_admin(
    app: FastAPI,
    settings: AuthSettings | None = None,
    *,
    email_sender: EmailSender | None = None,
    google: GoogleClient | None = None,
    links: MagicLinks | None = None,
    throttle: LoginThrottle | None = None,
) -> None:
    settings = settings or get_auth_settings()
    redis_url = get_settings().redis_url
    if google is None and settings.google_enabled:
        google = AuthlibGoogleClient(settings)
    app.state.admin_auth_settings = settings
    app.state.admin_auth = AdminAuth(
        settings=settings,
        email_sender=email_sender or make_email_sender(settings),
        links=links
        or MagicLinks(
            settings.session_secret,
            settings.magic_link_max_age_s,
            RedisUsedTokenStore(redis_url),
            salt=ADMIN_LINK_SALT,
        ),
        throttle=throttle or RedisLoginThrottle(redis_url),
        google=google,
    )
    for sub in ROUTERS:
        app.include_router(sub)


async def seed_admins_on_startup(app: FastAPI) -> None:
    """AA-1: on start, seed an empty `admin_users` from ADMIN_EMAILS. A database that is not
    up yet only logs; /health reports it."""
    settings: AuthSettings = app.state.admin_auth_settings
    try:
        async with app.state.sessionmaker() as db:
            added = await seed_admins(db, settings.admins)
    except Exception:
        log.exception("Could not seed admin_users from ADMIN_EMAILS")
        return
    if added:
        log.info("Seeded %d admin(s) from ADMIN_EMAILS", added)


__all__ = ["install_admin", "seed_admins_on_startup"]
