"""Extraction accuracy per field on evals/fixtures/inputs.

The fake-model tests check the fixtures and the scoring. The last test is opt-in: it runs the
fixtures against real models and prints the per-field report.

    $env:MODEL_PROFILE = "local"; $env:STRONG_EVAL_INPUTS = "1"
    uv run pytest apps/worker/tests/test_extraction_accuracy.py -s
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway, get_gateway
from strong_core.gateway.fake import messages_hash
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import JobPosting, Resume
from strong_worker.inputs.accuracy import (
    fixtures_dir,
    list_f1,
    load_cases,
    run_inputs_eval,
    score_job_posting,
    score_resume,
    text_score,
)
from strong_worker.inputs.extract import build_job_posting_messages, build_resume_messages
from strong_worker.inputs.sanitize import sanitize_untrusted
from strong_worker.inputs.testing import RecordingBackend


def test_fixtures_cover_every_role_family_and_validate() -> None:
    postings = load_cases(fixtures_dir() / "postings")
    resumes = load_cases(fixtures_dir() / "resumes")
    assert len(postings) == 10
    assert len(resumes) == 6
    families = Counter(
        JobPosting.model_validate_json(expected).role_family.value for _, _, expected in postings
    )
    assert families == {"swe": 2, "data_ml": 2, "pm": 2, "design": 2, "tpm": 2}
    for _, _, expected in resumes:
        Resume.model_validate_json(expected)


def test_scoring() -> None:
    assert text_score("Stripe", "Stripe, Inc.") == 1.0
    assert text_score(None, None) == 1.0
    assert text_score("Payments", None) == 0.0
    assert text_score("Payments", "Growth") == 0.0
    assert list_f1(["Python", "SQL"], ["python", "sql"]) == 1.0
    assert list_f1(["Python", "SQL"], ["Python"]) == pytest.approx(2 / 3)
    assert list_f1([], []) == 1.0
    assert list_f1(["Go"], []) == 0.0


def test_scoring_a_perfect_and_a_wrong_extraction() -> None:
    _, _, expected_json = load_cases(fixtures_dir() / "postings")[0]
    expected = JobPosting.model_validate_json(expected_json)
    assert set(score_job_posting(expected, expected).values()) == {1.0}
    wrong = expected.model_copy(update={"company_name": "Other", "level": None})
    scores = score_job_posting(expected, wrong)
    assert scores["company_name"] == 0.0
    assert scores["title"] == 1.0

    _, _, resume_json = load_cases(fixtures_dir() / "resumes")[0]
    resume = Resume.model_validate_json(resume_json)
    assert set(score_resume(resume, resume).values()) == {1.0}
    assert score_resume(resume, Resume())["role_companies"] == 0.0


async def test_report_with_recorded_outputs(tmp_path: Path) -> None:
    """Record each expected output as the fake model's exact reply; every field scores 1.0."""
    folder = tmp_path / "extractor"
    folder.mkdir()
    for kind, build in (
        ("postings", build_job_posting_messages),
        ("resumes", build_resume_messages),
    ):
        for _, text, expected in load_cases(fixtures_dir() / kind):
            key = messages_hash(build(sanitize_untrusted(text).text))
            (folder / f"{key}.json").write_text(expected, encoding="utf-8")
    gateway = ModelGateway(fake_models_config(), fake=RecordingBackend(tmp_path))

    report = await run_inputs_eval(gateway)

    assert report.profile == "fake"
    assert len(report.cases) == 16
    assert not [c for c in report.cases if c.get("error")]
    assert set(report.postings.values()) == {1.0}
    assert set(report.resumes.values()) == {1.0}
    assert "must_have_skills" in report.format()
    json.dumps(report.to_dict())


@pytest.mark.skipif(
    os.environ.get("STRONG_EVAL_INPUTS") != "1",
    reason="opt-in: set STRONG_EVAL_INPUTS=1 and MODEL_PROFILE=local (or hosted)",
)
async def test_extraction_accuracy_on_real_models() -> None:
    assert get_settings().model_profile.value != "fake", "set MODEL_PROFILE to local or hosted"
    report = await run_inputs_eval(get_gateway())
    print("\n" + report.format())
    out = os.environ.get("STRONG_EVAL_REPORT")
    if out:
        await asyncio.to_thread(
            Path(out).write_text, json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )
    assert len(report.cases) == 16
