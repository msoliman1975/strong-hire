"""Read and validate a company profile JSON file (AD-1).

Errors name the bad field with a dotted path, for example
`values_framework.principles[0].name: String should have at least 1 character`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from strong_core.schemas import CompanyProfile


class ProfileFileError(Exception):
    """The file is missing, is not JSON, or does not match the CompanyProfile schema."""

    def __init__(self, path: Path, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        super().__init__(f"{path}: " + "; ".join(problems))


def field_path(loc: tuple[int | str, ...]) -> str:
    """('a', 'b', 0, 'c') -> 'a.b[0].c'. An empty location means the whole profile."""
    out = ""
    if loc and loc[-1] == "[key]":  # pydantic marks a bad dict key this way
        return f"{field_path(loc[:-1])} (key)"
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "(profile)"


def format_validation_error(error: ValidationError) -> list[str]:
    problems = []
    for item in error.errors(include_url=False):
        message = str(item["msg"]).removeprefix("Value error, ")
        if item["type"] == "extra_forbidden":
            message = "unknown field (check the spelling, or remove it)"
        problems.append(f"{field_path(tuple(item['loc']))}: {message}")
    return problems


def parse_profile(data: Any, path: Path | None = None) -> CompanyProfile:
    try:
        return CompanyProfile.model_validate(data)
    except ValidationError as exc:
        raise ProfileFileError(path or Path("<data>"), format_validation_error(exc)) from exc


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
