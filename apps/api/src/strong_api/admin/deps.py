"""Who may use the admin routes. Every admin sub-router depends on `Admin` (read) or
`AdminWrite` (strong_api.admin.actions) so the access rule lives in one place."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from strong_api.auth.deps import optional_user
from strong_api.auth.settings import AuthSettings
from strong_core.db.models import User


def admin_settings(request: Request) -> AuthSettings:
    settings: AuthSettings = request.app.state.admin_auth_settings
    return settings


async def require_admin(
    user: Annotated[User | None, Depends(optional_user)],
    settings: Annotated[AuthSettings, Depends(admin_settings)],
) -> User:
    """The signed-in admin. 404 for everyone else, so the area does not show it exists."""
    if user is None or not settings.is_admin(user.email):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return user


Admin = Annotated[User, Depends(require_admin)]
