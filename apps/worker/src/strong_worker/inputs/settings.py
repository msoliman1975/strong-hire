"""Settings for job and resume inputs, read from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class InputsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    inputs_storage_dir: Path | None = Field(
        default=None, description="Folder for encrypted resume files. Default ~/.strong-hire."
    )
    inputs_storage_key: SecretStr | None = Field(
        default=None, description="Fernet key (urlsafe base64, 32 bytes). Required in prod."
    )
    inputs_fetch_timeout_s: float = 15.0
    inputs_browser_fallback: bool = Field(
        default=True, description="Render script-heavy pages with Playwright when installed."
    )

    @property
    def resolved_storage_dir(self) -> Path:
        return self.inputs_storage_dir or Path.home() / ".strong-hire" / "uploads"


@lru_cache
def get_inputs_settings() -> InputsSettings:
    return InputsSettings()
