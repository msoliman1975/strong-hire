"""Admin area (R2). `install_admin(app)` adds the /admin routes for ADMIN_EMAILS users."""

from __future__ import annotations

from fastapi import FastAPI

from strong_api.admin.router import router
from strong_api.auth.settings import AuthSettings, get_auth_settings


def install_admin(app: FastAPI, settings: AuthSettings | None = None) -> None:
    app.state.admin_auth_settings = settings or get_auth_settings()
    app.include_router(router)


__all__ = ["install_admin"]
