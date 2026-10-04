"""Voice agent settings, read from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    livekit_url: str = "ws://localhost:7880"
    livekit_public_url: str | None = Field(
        default=None, description="LiveKit URL for browsers. Defaults to livekit_url."
    )
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "secret"

    voice_health_port: int = 8081
    voice_worker_port: int = Field(default=8082, description="LiveKit worker's own HTTP port.")
    devpage_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "devpage",
        description="Folder of the bare browser test page, served at / in dev only.",
    )

    latency_dir: Path = Path("var/latency")
    latency_label: str = Field(
        default="", description="Name of the CSV in latency_dir. Defaults to MODEL_PROFILE."
    )

    # Turn taking. Lower values answer sooner but cut in on slow speakers.
    vad_min_silence_s: float = 0.35
    endpointing_min_delay_s: float = 0.2
    endpointing_max_delay_s: float = 2.5
    interruption_min_duration_s: float = 0.4


@lru_cache
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()
