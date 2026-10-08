"""Response body of GET /reports (R1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import HireSignal, InterviewType, Mode

ReportType = Literal["gap_report", "interview_debrief"]
ReportStatus = Literal["ready", "scoring", "failed"]


class ReportItem(BaseModel):
    """One row of the Reports page. Open a gap report with GET /gap-analyses/{id} and a debrief
    with GET /sessions/{id}/debrief."""

    model_config = ConfigDict(extra="forbid")

    type: ReportType
    id: uuid.UUID = Field(description="The gap analysis id, or the session id of a debrief.")
    job_target_id: uuid.UUID
    job_name: str | None = Field(description="None when the job description was deleted.")
    job_deleted: bool
    resume_id: uuid.UUID | None = Field(description="Gap reports only.")
    resume_name: str | None = Field(description="Gap reports only. None when the CV was deleted.")
    resume_deleted: bool = Field(description="Gap reports only: the CV was deleted.")
    status: ReportStatus = Field(
        description="Gap reports are always ready. A debrief is scoring, ready or failed."
    )
    at: datetime = Field(description="When the report was made; the list is newest first.")
    match_score: int | None = Field(description="Gap reports only.")
    hire_signal: HireSignal | None = Field(description="Debriefs only, when ready.")
    interview_type: InterviewType | None = Field(description="Debriefs only.")
    mode: Mode | None = Field(description="Debriefs only.")
    duration_min: int | None = Field(description="Debriefs only.")
