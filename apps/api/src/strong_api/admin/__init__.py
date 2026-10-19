"""Admin area (R2, docs/admin-spec.md). `install_admin(app)` adds the /admin routes for admins.

Each feature has its own sub-router module with prefix "/admin"; add it to ROUTERS."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from strong_api.admin.alerts import router as alerts_router
from strong_api.admin.content import router as content_router
from strong_api.admin.controls import router as controls_router
from strong_api.admin.ops import router as ops_router
from strong_api.admin.overview import router as overview_router
from strong_api.admin.router import router
from strong_api.admin.sim import router as sim_router
from strong_api.admin.users import router as users_router
from strong_api.auth.settings import AuthSettings, get_auth_settings

ROUTERS: list[APIRouter] = [
    router,
    controls_router,
    alerts_router,
    users_router,
    overview_router,
    ops_router,
    content_router,
    sim_router,
]


def install_admin(app: FastAPI, settings: AuthSettings | None = None) -> None:
    app.state.admin_auth_settings = settings or get_auth_settings()
    for sub in ROUTERS:
        app.include_router(sub)


__all__ = ["install_admin"]
