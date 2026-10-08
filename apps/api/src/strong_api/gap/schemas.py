"""Request and response bodies of the gap analysis endpoints (GA-1 to GA-4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import GapAnalysis, GapStatus


class GapAnalysisStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: uuid.UUID | None = Field(
        default=None,
        description="The resume to compare with the job. Leave it out to run again with the "
        "resume of the latest analysis.",
    )
    reuse_ready: bool = Field(
        default=False,
        description="R1: return the latest ready analysis instead of a new run when the job, "
        "the resume and the company profile did not change since it was made. The app sets it "
        "when the user picks a saved job and a saved CV again.",
    )


class GapAnalysisOut(BaseModel):
    """The latest gap analysis of a job target. Poll while status is "running"."""

    id: uuid.UUID
    job_target_id: uuid.UUID
    resume_id: uuid.UUID
    resume_name: str | None = Field(description="R1: the CV's library name. None when deleted.")
    resume_deleted: bool = Field(description="R1: the CV used for this analysis was deleted.")
    job_deleted: bool = Field(description="R1: the job description was deleted.")
    status: GapStatus
    analysis: GapAnalysis | None = Field(description="Set when status is ready.")
    error: str | None = Field(description="A plain reason when status is failed.")
    generic_mode: bool | None = Field(
        description="True when no company profile was used. None until ready."
    )
    profile_version: int | None
    stale: bool = Field(
        description="The job, the resume or the company profile changed after this analysis. "
        "Start it again to update it. Always false when the job or the resume was deleted."
    )
    created_at: datetime
    updated_at: datetime | None
