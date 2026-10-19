"""Settings for the sim, read from environment variables (SIM_*)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SimSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIM_", env_file=".env", extra="ignore")

    base_url: str = Field(
        default="https://getstronghire.com/api", description="The API as a browser sees it."
    )
    token: SecretStr = Field(default=SecretStr(""), description="SIM_TOKEN on the main server.")
    out_dir: Path = Field(default=Path("runs"), description="Where run folders are written.")
    upload_target: str = Field(
        default="",
        description="rsync target for each finished session, for example "
        "simup@188.245.31.58:. Empty means keep files local only.",
    )
    upload_key: Path | None = Field(default=None, description="SSH key for the upload user.")
    cost_limit_usd: float = Field(default=5.0, gt=0, description="Stop the run above this.")
    http_timeout_s: float = 60.0
    wait_timeout_s: float = Field(default=600.0, description="Longest wait for a job or debrief.")
    max_turns: int = Field(default=120, description="Safety stop for one text session.")
    candidate_min_interval_s: float = Field(
        default=0.0,
        description="Least time between candidate calls. 13 keeps a 5-per-minute free tier.",
    )
    voice_silence_s: float = Field(
        default=6.0, description="How long a '[silence]' turn stays quiet in a voice session."
    )

    # strong-sim serve: admin-started runs on the main server (SM-2..SM-5, SM-14).
    poll_s: float = Field(default=2.0, gt=0, description="How often serve looks for work.")
    progress_every_s: float = Field(default=10.0, gt=0, description="SM-4: progress updates.")
    wait_recheck_s: float = Field(default=60.0, gt=0, description="SM-3: a waiting run checks.")
    wait_limit_s: float = Field(default=1800.0, ge=0, description="SM-3: then the run fails.")
    keep_gb: float = Field(default=10.0, gt=0, description="SM-14: runs folder size limit.")
    keep_days: int = Field(default=90, ge=1, description="SM-14: runs not marked Keep.")
    retention_every_s: float = Field(default=3600.0, gt=0)


@lru_cache
def get_sim_settings() -> SimSettings:
    return SimSettings()
