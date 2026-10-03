"""Runtime settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProfile(StrEnum):
    """Which config/models.<profile>.yaml the gateway uses. `fake` needs no model at all."""

    FAKE = "fake"
    LOCAL = "local"
    HOSTED = "hosted"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) to the folder that holds config/ and prompts/."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "config").is_dir() and (candidate / "prompts").is_dir():
            return candidate
    return Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = Field(default="dev", description="dev, test or prod")
    database_url: str = "postgresql+psycopg://strong:strong@localhost:55432/strong"
    redis_url: str = "redis://localhost:56379/0"

    model_profile: ModelProfile = ModelProfile.FAKE
    model_gateway_url: str | None = Field(
        default=None, description="Overrides gateway.base_url from the models config file."
    )
    model_gateway_api_key: str | None = None

    repo_root: Path = Field(default_factory=find_repo_root)
    config_dir: Path | None = None
    prompts_dir: Path | None = None
    fake_fixtures_dir: Path | None = None

    @property
    def resolved_config_dir(self) -> Path:
        return self.config_dir or self.repo_root / "config"

    @property
    def resolved_prompts_dir(self) -> Path:
        return self.prompts_dir or self.repo_root / "prompts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
