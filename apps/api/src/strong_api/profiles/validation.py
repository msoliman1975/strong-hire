"""Read and validate a company profile JSON file (AD-1).

The parser and its error type are in strong_core.profiles, because the lookups that read stored
profiles use them too. Errors name the bad field with a dotted path, for example
`values_framework.principles[0].name: String should have at least 1 character`.

`strongctl profiles validate` and the admin import (AT-3) both use `parse_profile_text`, so a
file passes or fails the same way in both.
"""

from __future__ import annotations

import json
from pathlib import Path

from strong_core.profiles import ProfileFileError, parse_profile
from strong_core.schemas import CompanyProfile, Confidence

__all__ = [
    "ProfileFileError",
    "load_profile_file",
    "parse_profile",
    "parse_profile_text",
    "profile_summary",
]


def parse_profile_text(text: str, path: Path | None = None) -> CompanyProfile:
    """Validate the text of a profile file. Raises ProfileFileError with readable problems."""
    where = path or Path("<upload>")
    try:
        data = json.loads(text.removeprefix("﻿"))
    except json.JSONDecodeError as exc:
        raise ProfileFileError(
            where, [f"not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"]
        ) from exc
    return parse_profile(data, where)


def load_profile_file(path: Path) -> CompanyProfile:
    """Load and validate one profile file. Raises ProfileFileError with readable problems."""
    if not path.is_file():
        raise ProfileFileError(path, ["file not found"])
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProfileFileError(path, [f"not UTF-8 text: {exc.reason}"]) from exc
    return parse_profile_text(text, path)


def profile_summary(profile: CompanyProfile) -> list[str]:
    """A few lines that describe a valid profile (strongctl validate, the admin import)."""
    low = [f.value for f, c in profile.field_confidence.items() if c is Confidence.LOW]
    return [
        f"Company: {profile.company_name} ({profile.company_slug})",
        f"Values framework: {profile.values_framework.name}, "
        f"{len(profile.values_framework.principles)} principles, values share "
        f"{profile.values_share:g}",
        f"Loops: {len(profile.loop_structure)}, question patterns: "
        f"{len(profile.question_patterns)}, levels: {len(profile.bar_by_level)}",
        f"Scoring weights: {len(profile.scoring_weights)} competencies, sources: "
        f"{len(profile.sources)}",
        "Low-confidence fields: " + (", ".join(low) if low else "none"),
    ]
