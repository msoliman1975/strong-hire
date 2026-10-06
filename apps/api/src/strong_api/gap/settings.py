"""Gap analysis limits (GA-4: free, with fair-use rate limits per user)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gap_rate_limit_per_hour: int = Field(default=10, ge=1, description="Runs per user per hour.")
    gap_rate_limit_per_day: int = Field(default=40, ge=1, description="Runs per user per day.")
    gap_running_timeout_s: int = Field(
        default=15 * 60, ge=60, description="A run older than this shows as failed."
    )


@lru_cache
def get_gap_settings() -> GapSettings:
    return GapSettings()
