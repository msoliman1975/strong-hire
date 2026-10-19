"""Who may use the admin routes (AA-4). Every admin sub-router depends on `Admin` (read) or
`AdminWrite` (strong_api.admin.actions) so the access rule lives in one place.

Only a live admin session (the `sh_admin` cookie, strong_api.admin.identity) counts. The
candidate session (`sh_session`) never grants admin access, even for an admin's email.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from strong_api.admin.identity import ADMIN_COOKIE, AdminAuth, AdminPrincipal, resolve_session
from strong_api.auth.deps import DbSession
from strong_api.auth.settings import AuthSettings


def admin_settings(request: Request) -> AuthSettings:
    settings: AuthSettings = request.app.state.admin_auth_settings
    return settings


def admin_auth(request: Request) -> AdminAuth:
    auth: AdminAuth = request.app.state.admin_auth
    return auth


async def optional_admin(request: Request, db: DbSession) -> AdminPrincipal | None:
    """The admin of this request's `sh_admin` cookie, or None."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return None
    return await resolve_session(db, token, admin_auth(request).clock())


async def require_admin(
    admin: Annotated[AdminPrincipal | None, Depends(optional_admin)],
) -> AdminPrincipal:
    """The signed-in admin. 404 for everyone else, so the area does not show it exists."""
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return admin


Admin = Annotated[AdminPrincipal, Depends(require_admin)]
OptionalAdmin = Annotated[AdminPrincipal | None, Depends(optional_admin)]
