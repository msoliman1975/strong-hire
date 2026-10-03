"""Google OAuth (OpenID Connect) through Authlib."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from authlib.integrations.starlette_client import OAuth, OAuthError
from starlette.requests import Request
from starlette.responses import Response

from strong_api.auth.settings import AuthSettings

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"


class GoogleSignInError(Exception):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    email: str


class GoogleClient(Protocol):
    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response: ...

    async def fetch_identity(self, request: Request) -> GoogleIdentity: ...


class AuthlibGoogleClient:
    def __init__(self, settings: AuthSettings) -> None:
        self._oauth = OAuth()
        self._oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url=GOOGLE_METADATA_URL,
            client_kwargs={"scope": "openid email profile"},
        )

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        response: Response = await self._oauth.google.authorize_redirect(request, redirect_uri)
        return response

    async def fetch_identity(self, request: Request) -> GoogleIdentity:
        try:
            token = await self._oauth.google.authorize_access_token(request)
        except OAuthError as exc:
            raise GoogleSignInError(str(exc)) from exc
        info = token.get("userinfo") or {}
        email = info.get("email")
        if not isinstance(email, str) or not info.get("email_verified"):
            raise GoogleSignInError("Google did not return a verified email")
        return GoogleIdentity(email=email)
