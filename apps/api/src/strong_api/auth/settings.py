"""Settings for sign-in, read from environment variables."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
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

    # Staging only: comma-separated emails that see the model spend meter (strong_api.devtools).
    model_spend_viewers: str = ""

    # Comma-separated emails that may open the admin area (strong_api.admin, R2). Case does not
    # matter. Everyone else gets 404 from the admin routes.
    admin_emails: str = ""

    # The AI candidate (P13). POST /auth/sim-login exists only when sim_enabled is true, and it
    # signs in only sim_email, in that user's own org. Sim sessions skip the plan check and may
    # use the text channel.
    sim_enabled: bool = False
    sim_token: SecretStr | None = None
    sim_email: str = "sim@getstronghire.com"

    @property
    def is_local(self) -> bool:
        return self.app_env == AppEnv.LOCAL

    @property
    def spend_viewers(self) -> set[str]:
        return {e.strip().lower() for e in self.model_spend_viewers.split(",") if e.strip()}

    @property
    def admins(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    def is_admin(self, email: str | None) -> bool:
        return bool(email) and str(email).strip().lower() in self.admins

    @property
    def sim_active(self) -> bool:
        """True only when the flag is on and a real token is set."""
        token = self.sim_token.get_secret_value() if self.sim_token else ""
        return self.sim_enabled and len(token) >= 32

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
