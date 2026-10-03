from __future__ import annotations

from pathlib import Path

import pytest

from strong_core.prompts import PromptNotFoundError, list_versions, load_prompt


@pytest.fixture
def prompts(tmp_path: Path) -> Path:
    folder = tmp_path / "extractor"
    folder.mkdir()
    (folder / "job_posting.v1.txt").write_text("Old: $posting", encoding="utf-8")
    (folder / "job_posting.v2.txt").write_text("Extract the job.\n$posting", encoding="utf-8")
    (folder / "job_posting.v10.txt").write_text("Newest: $posting", encoding="utf-8")
    (folder / "job_posting_extra.v1.txt").write_text("other", encoding="utf-8")
    return tmp_path


def test_latest_version_is_numeric_max(prompts: Path) -> None:
    assert list_versions("extractor", "job_posting", prompts) == [1, 2, 10]
    assert load_prompt("extractor", "job_posting", prompts_dir=prompts).version == 10


def test_pinned_version_and_ref(prompts: Path) -> None:
    p = load_prompt("extractor", "job_posting", version=2, prompts_dir=prompts)
    assert p.ref == "extractor/job_posting.v2"
    msg = p.message("system", posting="Senior SWE")
    assert msg.content == "Extract the job.\nSenior SWE"
    assert msg.prompt_ref == "extractor/job_posting.v2"


def test_missing_placeholder_fails_loudly(prompts: Path) -> None:
    with pytest.raises(KeyError):
        load_prompt("extractor", "job_posting", prompts_dir=prompts).render()


def test_missing_prompt(prompts: Path) -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("scorer", "rubric", prompts_dir=prompts)
    with pytest.raises(PromptNotFoundError):
        load_prompt("extractor", "job_posting", version=3, prompts_dir=prompts)
