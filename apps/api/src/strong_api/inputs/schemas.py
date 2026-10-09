"""Request and response bodies for the input endpoints. The parsed data itself uses the shared
contracts JobPosting and Resume from strong_core.schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from strong_api.inputs.queue import JobState
from strong_core.library import NAME_MAX_CHARS, clean_name
from strong_core.schemas import GapStatus, JobPosting, Level, Resume

MAX_POSTING_CHARS = 60_000
MAX_RESUME_TEXT_CHARS = 60_000


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JobContext(_Body):
    """Optional context the user adds about the interview (IN-4). Stage has its own column."""

    interviewer_name: str | None = Field(default=None, max_length=200)
    interviewer_role: str | None = Field(default=None, max_length=200)
    recruiter_notes: str | None = Field(default=None, max_length=4000)
    concerns: str | None = Field(default=None, max_length=4000)

    def is_empty(self) -> bool:
        return not any(self.model_dump().values())


class JobTargetCreate(_Body):
    """A posting as pasted text, a URL, or both (IN-1). With both, the text is used and the URL
    helps company matching."""

    text: str | None = Field(default=None, max_length=MAX_POSTING_CHARS)
    url: str | None = Field(default=None, max_length=2000)
    stage: str | None = Field(default=None, max_length=100)
    context: JobContext = Field(default_factory=JobContext)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be an http or https URL")
        return value

    @model_validator(mode="after")
    def _text_or_url(self) -> JobTargetCreate:
        if not (self.text or self.url):
            raise ValueError("Give the posting text, a URL, or both.")
        return self


class JobTargetUpdate(_Body):
    """The user confirms or edits the extracted posting (IN-2) and the context (IN-4)."""

    posting: JobPosting
    stage: str | None = Field(default=None, max_length=100)
    context: JobContext = Field(default_factory=JobContext)


class ResumeUpdate(_Body):
    resume: Resume


class LibraryRename(_Body):
    """R1: a new name for a saved job or CV. Trimmed; 1 to 120 characters."""

    name: str = Field(max_length=NAME_MAX_CHARS * 2)

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        if len(value.strip()) > NAME_MAX_CHARS:
            raise ValueError(f"Use at most {NAME_MAX_CHARS} characters.")
        cleaned = clean_name(value)
        if not cleaned:
            raise ValueError("The name cannot be empty.")
        return cleaned


class JobTargetMatchIn(_Body):
    """R1: a posting the user is about to add. Same fields as JobTargetCreate."""

    text: str | None = Field(default=None, max_length=MAX_POSTING_CHARS)
    url: str | None = Field(default=None, max_length=2000)


class ResumeMatchIn(_Body):
    """R1: the SHA-256 of a CV file (or of the pasted text as UTF-8) before it is uploaded."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class JobOut(BaseModel):
    id: str
    status: JobState
    result: dict[str, Any] | None = None
    error: str | None = None


class JobTargetOut(BaseModel):
    id: uuid.UUID
    name: str | None = Field(
        description="R1: the name in the job library. None when the job description is deleted."
    )
    deleted: bool = Field(
        description="R1: the job description was deleted. Its reports and sessions stay."
    )
    status: Literal["pending", "extracted"]
    source_url: str | None
    posting: JobPosting | None
    level: Level | None
    company_id: uuid.UUID | None
    company_slug: str | None
    generic_mode: bool | None = Field(
        description="True when no curated company matched. None until extraction finishes."
    )
    stage: str | None
    context: JobContext
    created_at: datetime
    archived_at: datetime | None = Field(
        default=None, description="LB-2: set while the job description is archived."
    )


class ResumeOut(BaseModel):
    id: uuid.UUID
    name: str | None = Field(
        description="R1: the name in the CV library. None when the CV is deleted."
    )
    deleted: bool = Field(description="R1: the CV was deleted. Its gap reports stay.")
    status: Literal["pending", "extracted"]
    has_file: bool
    resume: Resume | None
    confirmed_at: datetime | None = Field(
        default=None,
        description=(
            "When the user checked and saved the extracted CV (PUT /resumes/{id}). None: not "
            "confirmed yet. A gap analysis does not wait for it."
        ),
    )
    uploaded_at: datetime


class JobTargetAccepted(BaseModel):
    job_target: JobTargetOut
    job: JobOut | None


class ResumeAccepted(BaseModel):
    resume: ResumeOut
    job: JobOut | None


class JobTargetSummary(BaseModel):
    """One row of the dashboard list (GET /job-targets)."""

    job_target: JobTargetOut
    match_score: int | None = Field(description="From the latest ready gap analysis, else None.")
    gap_status: GapStatus | None = Field(
        description="Status of the latest gap analysis. None when none was started."
    )
    sessions_count: int = Field(ge=0, description="Interview sessions for this job.")
    last_session_at: datetime | None = Field(description="Start of the latest session.")
    in_use: bool = Field(
        default=False,
        description="LB-2: the job has a gap analysis or a session. Archive it; do not delete.",
    )


class JobTargetMatch(BaseModel):
    """R1: the saved job with the same text or link, or None."""

    job_target: JobTargetOut | None


class ResumeMatch(BaseModel):
    """R1: the saved CV with the same file content, or None."""

    resume: ResumeOut | None
