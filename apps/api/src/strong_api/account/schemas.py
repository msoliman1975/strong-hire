"""Request and response bodies for the account endpoints (AC-1, AC-2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_consent: bool


class ConsentOut(BaseModel):
    training_consent: bool


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
