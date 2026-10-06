"""Read and validate a company profile JSON file (AD-1).

The parser and its error type are in strong_core.profiles, because the lookups that read stored
profiles use them too. Errors name the bad field with a dotted path, for example
`values_framework.principles[0].name: String should have at least 1 character`.
"""

from __future__ import annotations

import json
from pathlib import Path

from strong_core.profiles import ProfileFileError, parse_profile
from strong_core.schemas import CompanyProfile

__all__ = ["ProfileFileError", "load_profile_file", "parse_profile"]


def load_profile_file(path: Path) -> CompanyProfile:
    """Load and validate one profile file. Raises ProfileFileError with readable problems."""
    if not path.is_file():
        raise ProfileFileError(path, ["file not found"])
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ProfileFileError(
            path, [f"not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"]
        ) from exc
    except UnicodeDecodeError as exc:
        raise ProfileFileError(path, [f"not UTF-8 text: {exc.reason}"]) from exc
    return parse_profile(data, path)
