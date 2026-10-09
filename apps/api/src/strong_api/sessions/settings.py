"""Settings for voice and text sessions (P7), read from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceSessionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    livekit_public_url: str = Field(
        default="ws://localhost:7880", description="LiveKit URL as the browser reaches it."
    )
    livekit_api_key: str = "devkey"
    livekit_api_secret: SecretStr = SecretStr("secret")
    token_ttl_minutes: int = Field(default=90, ge=5, description="Join token lifetime.")
    strong_internal_token: SecretStr = Field(
        default=SecretStr("dev-internal-token"),
        description="Shared secret for /internal endpoints (voice agent). Set it in production.",
    )


@lru_cache
def get_voice_session_settings() -> VoiceSessionSettings:
    return VoiceSessionSettings()


class TextSessionSettings(BaseSettings):
    """Time limits for the text channel (PL-7)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    text_turn_timeout_s: float = Field(
        default=45.0, gt=0, description="The most one text turn (or the greeting) may take."
    )
    text_db_timeout_s: float = Field(
        default=10.0, gt=0, description="The most one turn save or trace insert may wait."
    )


@lru_cache
def get_text_session_settings() -> TextSessionSettings:
    return TextSessionSettings()
