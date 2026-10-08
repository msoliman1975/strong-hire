"""Saved job descriptions and CVs (R1): default names, content hashes and URL matching.

The API, the worker and migration 0007 use these rules, so a pasted posting or an uploaded file
that the user saved before is found again instead of being read a second time.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import PurePath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

NAME_MAX_CHARS = 120
_SPACE = re.compile(r"\s+")


def normalize_posting_text(text: str) -> str:
    """Lower case, with each run of white space made one space. Formatting does not count."""
    return _SPACE.sub(" ", text).strip().casefold()


def posting_text_hash(text: str | None) -> str | None:
    """SHA-256 of the normalized posting text, or None when there is no text."""
    if not text or not text.strip():
        return None
    return hashlib.sha256(normalize_posting_text(text).encode("utf-8")).hexdigest()


def content_hash(data: bytes) -> str:
    """SHA-256 of a CV file, or of the pasted CV text as UTF-8."""
    return hashlib.sha256(data).hexdigest()


def normalize_url(url: str | None) -> str | None:
    """The same job link written in a different way compares equal: the scheme and host are
    lower case, a "www." prefix, the fragment and a trailing slash are dropped."""
    if not url or not url.strip():
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def clean_name(name: str) -> str:
    """Trim and limit a name. The caller rejects an empty result."""
    return _SPACE.sub(" ", name).strip()[:NAME_MAX_CHARS].strip()


def _day(value: datetime | date | None) -> str:
    if value is None:
        value = datetime.now()
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()


def default_job_name(
    parsed: dict[str, Any] | None, source_url: str | None, created: datetime | date | None
) -> str:
    """ "<title> at <company>" from the posting, else the link's host, else a dated name."""
    parsed = parsed or {}
    title = str(parsed.get("title") or "").strip()
    company = str(parsed.get("company_name") or "").strip()
    if title and company:
        return clean_name(f"{title} at {company}")
    if title or company:
        return clean_name(title or company)
    host = (urlsplit(source_url).hostname or "").lower().removeprefix("www.") if source_url else ""
    if host:
        return clean_name(host)
    return f"Job description {_day(created)}"


def default_resume_name(filename: str | None, uploaded: datetime | date | None) -> str:
    """The original file name without its extension, else "CV <date>"."""
    if filename:
        stem = clean_name(PurePath(filename).stem)
        if stem:
            return stem
    return f"CV {_day(uploaded)}"
