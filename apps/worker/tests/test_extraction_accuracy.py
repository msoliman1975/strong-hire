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
    achievement_attribution,
    fixtures_dir,
    list_f1,
    load_cases,
    load_files,
    reading_order,
    run_inputs_eval,
    score_job_posting,
    score_resume,
    text_coverage,
    text_score,
)
from strong_worker.inputs.extract import build_job_posting_messages, build_resume_messages
from strong_worker.inputs.sanitize import sanitize_untrusted
from strong_worker.inputs.testing import RecordingBackend


def test_fixtures_cover_every_role_family_and_validate() -> None:
    postings = load_cases(fixtures_dir() / "postings")
    resumes = load_cases(fixtures_dir() / "resumes")
    assert len(postings) == 10
    assert len(resumes) == 15
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


def test_file_cases_are_read_like_the_worker_reads_them() -> None:
    """PDF and DOCX fixtures go through document_text, the worker's reader."""
    kinds = Counter(case.kind for case in load_files(fixtures_dir() / "resumes"))
    assert kinds == {"text": 6, "pdf": 6, "docx": 3}


def test_attribution_counts_an_achievement_only_under_its_role() -> None:
    """The pooled score does not see an achievement filed under the wrong role; the
    per-role score does."""
    _, _, resume_json = load_cases(fixtures_dir() / "resumes")[0]
    expected = Resume.model_validate_json(resume_json)
    first, second = expected.roles[0], expected.roles[1]
    misfiled = expected.model_copy(
        update={
            "roles": [
                first.model_copy(update={"achievements": first.achievements[:1]}),
                second.model_copy(
                    update={"achievements": first.achievements[1:] + second.achievements}
                ),
            ]
        }
    )
    scores = score_resume(expected, misfiled)
    assert scores["achievements"] == 1.0
    assert scores["achievement_attribution"] < 0.75
    assert achievement_attribution(expected, expected) == 1.0


def test_attribution_tells_two_roles_at_one_company_apart() -> None:
    expected = Resume.model_validate_json(
        (fixtures_dir() / "resumes" / "same-company-two-roles.json").read_text(encoding="utf-8")
    )
    staff, senior = expected.roles[0], expected.roles[1]
    swapped = expected.model_copy(
        update={
            "roles": [
                staff.model_copy(update={"achievements": senior.achievements}),
                senior.model_copy(update={"achievements": staff.achievements}),
                *expected.roles[2:],
            ]
        }
    )
    assert score_resume(expected, swapped)["achievements"] == 1.0
    assert achievement_attribution(expected, swapped) < 0.5


def test_reading_order_and_coverage_see_a_misordered_text() -> None:
    expected = Resume.model_validate_json(
        (fixtures_dir() / "resumes" / "backend-senior.json").read_text(encoding="utf-8")
    )
    newline = chr(10)
    good = newline.join(x for r in expected.roles for x in (r.title, *r.achievements))
    assert reading_order(expected, good) == 1.0
    first, second = expected.roles
    bad = newline.join([first.title, second.title, *first.achievements, *second.achievements])
    assert reading_order(expected, bad) < 1.0
    assert text_coverage(expected, good) < 1.0  # no skills or schools in this text
    assert text_coverage(expected, "") == 0.0


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
    assert len(report.cases) == 25
    assert not [c for c in report.cases if c.get("error")]
    assert set(report.postings.values()) == {1.0}
    assert set(report.resumes.values()) == {1.0}
    assert set(report.resume_files.values()) == {1.0}
    assert "achievement_attribution" in report.resumes
    assert "reading_order" in report.format(per_case=True)
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
    assert len(report.cases) == 25
