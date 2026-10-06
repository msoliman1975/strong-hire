"""Request and response bodies for the input endpoints. The parsed data itself uses the shared
contracts JobPosting and Resume from strong_core.schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from strong_api.inputs.queue import JobState
from strong_core.schemas import JobPosting, Level, Resume

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


class JobOut(BaseModel):
    id: str
    status: JobState
    result: dict[str, Any] | None = None
    error: str | None = None


class JobTargetOut(BaseModel):
    id: uuid.UUID
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


class ResumeOut(BaseModel):
    id: uuid.UUID
    status: Literal["pending", "extracted"]
    has_file: bool
    resume: Resume | None
    uploaded_at: datetime


class JobTargetAccepted(BaseModel):
    job_target: JobTargetOut
    job: JobOut | None


class ResumeAccepted(BaseModel):
    resume: ResumeOut
    job: JobOut | None
