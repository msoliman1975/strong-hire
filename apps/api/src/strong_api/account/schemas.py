"""Request and response bodies for the account endpoints (AC-1, AC-2, AC-3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from strong_core.schemas import Level


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_consent: bool


class ConsentOut(BaseModel):
    training_consent: bool


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class ProfileIn(BaseModel):
    """AC-3: the profile asked for at the first sign-in. No payment details."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=120)
    years_experience: int = Field(ge=0, le=50)
    target_level: Level
    current_title: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=100)
    time_zone: str | None = Field(default=None, max_length=64)
    linkedin_url: str | None = Field(default=None, max_length=300)

    @field_validator("full_name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("current_title", "country", "time_zone", "linkedin_url", mode="before")
    @classmethod
    def _optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("linkedin_url")
    @classmethod
    def _linkedin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.lower().startswith(("https://", "http://")):
            value = f"https://{value}"
        host = value.split("://", 1)[1].split("/", 1)[0].lower()
        if host != "linkedin.com" and not host.endswith(".linkedin.com"):
            raise ValueError("Use a linkedin.com address.")
        return value


class ProfileOut(BaseModel):
    """AC-3. complete is false until the user saves the profile once."""

    full_name: str | None
    years_experience: int | None
    target_level: Level | None
    current_title: str | None
    country: str | None
    time_zone: str | None
    linkedin_url: str | None
    complete: bool


ExportStatus = Literal["preparing", "ready", "downloaded", "expired", "failed"]


class ExportOut(BaseModel):
    """AC-1 data export. The bundle is a zip: data.json plus the original resume files."""

    id: str
    status: ExportStatus
    requested_at: datetime
    download_url: str | None = Field(description="Set while status is ready. Works once.")
    error: str | None = None


class AccountDeletedOut(BaseModel):
    """AC-1 account delete. Rows are gone now; resume files go within the deadline."""

    status: Literal["deleted"]
    rows_deleted: int
    files_pending: int
    files_deleted_within_hours: int
    backups_expire_within_days: int
