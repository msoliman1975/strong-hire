"""Settings for voice sessions (P7), read from environment variables."""

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
