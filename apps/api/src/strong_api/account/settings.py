"""Account settings (AC-1), read from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AccountSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    account_export_ttl_s: int = Field(
        default=24 * 3600, ge=60, description="How long a finished export waits for download."
    )
    account_export_max_mb: int = Field(default=100, ge=1, description="Largest export bundle.")


@lru_cache
def get_account_settings() -> AccountSettings:
    return AccountSettings()
