"""R1: library names, content hashes and link matching (strong_core.library)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from types import ModuleType

from strong_core.config import get_settings
from strong_core.library import (
    NAME_MAX_CHARS,
    clean_name,
    default_job_name,
    default_resume_name,
    normalize_url,
    posting_text_hash,
)

MIGRATION = (
    get_settings().repo_root
    / "packages/core/migrations/versions/20261008_0007_library_names_soft_delete.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0007", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_posting_hash_ignores_case_and_white_space() -> None:
    assert posting_text_hash("Senior  Engineer\n\nat Stripe ") == posting_text_hash(
        "senior engineer at STRIPE"
    )
    assert posting_text_hash("Senior engineer") != posting_text_hash("Staff engineer")
    assert posting_text_hash(None) is None and posting_text_hash("  \n") is None


def test_urls_written_differently_compare_equal() -> None:
    a = normalize_url("https://www.Jobs.example.com/stripe/42/#apply")
    assert a == normalize_url("HTTPS://jobs.example.com/stripe/42")
    assert normalize_url("https://jobs.example.com/a?id=1") != normalize_url(
        "https://jobs.example.com/a?id=2"
    )
    assert normalize_url(None) is None and normalize_url(" ") is None


def test_default_job_names() -> None:
    day = date(2026, 10, 7)
    parsed = {"title": "Backend Engineer", "company_name": "Stripe"}
    assert default_job_name(parsed, None, day) == "Backend Engineer at Stripe"
    assert default_job_name({"title": "Backend Engineer"}, None, day) == "Backend Engineer"
    assert default_job_name(None, "https://www.boards.example/x", day) == "boards.example"
    assert default_job_name(None, None, day) == "Job description 2026-10-07"
    long = default_job_name({"title": "x" * 200, "company_name": "Stripe"}, None, day)
    assert len(long) == NAME_MAX_CHARS


def test_default_resume_names() -> None:
    when = datetime(2026, 10, 7, 23, 0, tzinfo=UTC)
    assert default_resume_name("Ana Lopez - CV.pdf", when) == "Ana Lopez - CV"
    assert default_resume_name("cv.final.docx", when) == "cv.final"
    assert default_resume_name(None, when) == "CV 2026-10-07"


def test_clean_name() -> None:
    assert clean_name("  My   CV  ") == "My CV"
    assert clean_name("   ") == ""


def test_migration_backfill_uses_the_same_rules() -> None:
    """Migration 0007 keeps its own copy of the rules; it must agree with strong_core.library."""
    m = _migration()
    text = "Backend Engineer\n\n at  Stripe"
    assert m._text_hash(text) == posting_text_hash(text)
    assert m._text_hash(None) is None
    when = datetime(2026, 10, 7, tzinfo=UTC)
    cases = [
        ({"title": "Backend Engineer", "company_name": "Stripe"}, None),
        ({"company_name": "Stripe"}, None),
        (None, "https://www.boards.example/x"),
        (None, None),
    ]
    for parsed, url in cases:
        assert m._job_name(parsed, url, when) == default_job_name(parsed, url, when)
