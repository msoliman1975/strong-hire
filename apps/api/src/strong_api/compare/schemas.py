"""Request and response bodies of the resume comparison endpoints (RC-1 to RC-8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import GapStatus, Severity


class ComparedResume(BaseModel):
    """One compared resume: its rule-based must-have count (RC-2) and, once ready, its score."""

    resume_id: uuid.UUID
    resume_name: str | None = Field(description="None when the resume was deleted.")
    is_main: bool
    deleted: bool
    gap_analysis_id: uuid.UUID
    status: GapStatus = Field(description="The status of the analysis this resume is ranked by.")
    error: str | None = Field(description="A plain reason when status is failed.")
    reused: bool = Field(description="RC-2: an earlier analysis was reused; no model call.")
    match_score: int | None = Field(description="GA-1. None until ready.")
    must_haves_total: int = Field(description="RC-2: the job's must-have skills.")
    must_haves_shown: int = Field(
        description="RC-2: must-haves the resume mentions (IN-12 rule, no model)."
    )
    must_haves_missing: list[str] = Field(description="RC-2: must-haves the resume never shows.")
    high_gaps: int | None = Field(description="High-severity gaps. None until ready.")
    rank: int | None = Field(description="RC-3: 1 is the best fit. None until ready.")
    stale: bool = Field(
        description="RC-8: the job or this resume changed since its analysis was made."
    )


class HintSource(BaseModel):
    """RC-4: the other resume that covers a gap, and its line."""

    resume_id: uuid.UUID
    resume_name: str
    line: str = Field(description="The line of that resume, unchanged.")
    place: Literal["skills", "achievement"] = Field(
        description="Where the line goes: the resume's skills, or an achievement of a role."
    )
    company: str | None = Field(description="For an achievement: the company of its role.")
    can_add: bool = Field(
        description="The line can be copied: a skill the resume lacks, or an achievement at a "
        "company the resume also lists."
    )
    in_resume: bool = Field(
        description="The focus resume already has this line, for example after Add to resume."
    )


class ComparisonGap(BaseModel):
    """One gap of the focus resume (RC-4, RC-5)."""

    key: str = Field(description="Stable id of this hint inside the comparison.")
    summary: str
    severity: Severity
    related_requirement: str | None
    source: HintSource | None = Field(
        description="RC-4: another resume covers this gap. None: no resume does (RC-5)."
    )
    status: Literal["open", "added", "dismissed"]
    listed_in: list[str] = Field(
        description="RC-5: names of the compared resumes (the focus first) that name the "
        "requirement somewhere, by the IN-12 rule. Empty when none does or there is no "
        "requirement."
    )


class ResumeComparisonOut(BaseModel):
    """The latest resume comparison of a role. Poll while status is "running"."""

    id: uuid.UUID
    job_target_id: uuid.UUID
    status: Literal["running", "ready", "failed"] = Field(
        description="running while any analysis runs; failed when every analysis failed."
    )
    resumes: list[ComparedResume] = Field(
        description="Ranked resumes first (rank 1 first), then the others."
    )
    recommended_resume_id: uuid.UUID | None = Field(description="RC-3. None until ready.")
    reason: str | None = Field(description="RC-3: why it fits best, built in code.")
    focus_resume_id: uuid.UUID | None = Field(
        description="The resume whose gaps are listed: the chosen one, else the recommended one."
    )
    gaps: list[ComparisonGap] = Field(description="RC-4, RC-5: gaps of the focus resume.")
    role_resume_id: uuid.UUID | None = Field(
        description="The resume the role uses now (its interviews, else its analysis)."
    )
    chosen_resume_id: uuid.UUID | None = Field(description="RC-6: picked with Use this one.")
    new_runs: int = Field(description="RC-7: analyses this comparison started.")
    out_of_date: bool = Field(description="RC-8: compare again to update it.")
    out_of_date_reason: str | None
    created_at: datetime


class UseResumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: uuid.UUID
