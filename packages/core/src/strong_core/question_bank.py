"""General question bank loader (QB-1, QB-5).

General questions live in questions/general.json, validated by `GeneralQuestionBank`. Company
questions are the `sample_questions` of each Published company profile and are read with the
profile lookups in `strong_core.profiles`.

    bank = load_general_bank()               # cached for the process
    bank = load_general_bank(path=some_file) # not cached, for tests and checks
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from strong_core.config import get_settings
from strong_core.schemas import GeneralQuestionBank

GENERAL_FILE = "general.json"


class QuestionBankError(Exception):
    """questions/general.json is missing, is not JSON, or does not match the schema."""


def load_general_bank(path: Path | None = None) -> GeneralQuestionBank:
    if path is None:
        return _cached_bank(get_settings().resolved_questions_dir / GENERAL_FILE)
    return _read(path)


@lru_cache
def _cached_bank(path: Path) -> GeneralQuestionBank:
    return _read(path)


def _read(path: Path) -> GeneralQuestionBank:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuestionBankError(f"{path}: cannot read the file ({exc})") from exc
    try:
        return GeneralQuestionBank.model_validate_json(text)
    except ValidationError as exc:
        raise QuestionBankError(f"{path}: {exc}") from exc
