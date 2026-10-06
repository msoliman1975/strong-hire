"""Settings for sign-in, read from environment variables."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SESSION_SECRET = "local-dev-only-session-secret-change-me"  # local default only


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: AppEnv = Field(
        default=AppEnv.LOCAL,
        description="Dev login exists only when this is 'local'. Hosting must set 'production'.",
    )
    session_secret: str = DEV_SESSION_SECRET
    session_max_age_s: int = 14 * 24 * 3600

    web_base_url: str = Field(
        default="http://localhost:5180", description="Where the browser app is served."
    )
    api_public_url: str = Field(
        default="http://localhost:5180/api",
        description="The API as the browser sees it (through the web proxy). Used for links.",
    )

    google_client_id: str | None = None
    google_client_secret: str | None = None

    magic_link_max_age_s: int = 15 * 60
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Strong Hire <no-reply@stronghire.local>"

    @property
    def is_local(self) -> bool:
        return self.app_env == AppEnv.LOCAL

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @model_validator(mode="after")
    def _require_real_secret_outside_local(self) -> AuthSettings:
        if self.app_env in (AppEnv.STAGING, AppEnv.PRODUCTION) and (
            self.session_secret == DEV_SESSION_SECRET or len(self.session_secret) < 32
        ):
            raise ValueError("SESSION_SECRET must be set to 32+ random characters outside local")
        return self


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
