from __future__ import annotations

from pathlib import Path

import pytest

from strong_core.config import find_repo_root
from strong_core.gateway import CapabilityTier, ModelGateway, Role, load_models_config
from strong_core.gateway import client as gateway_client
from strong_core.prompts import (
    _FILE,
    PromptFileNameError,
    PromptNotFoundError,
    active_tier,
    list_versions,
    load_prompt,
)


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


# --- PL-5: prompt variants by capability tier ------------------------------------------------


@pytest.fixture
def tiered(tmp_path: Path) -> Path:
    folder = tmp_path / "scorer"
    folder.mkdir()
    (folder / "rubric.v1.txt").write_text("Default v1", encoding="utf-8")
    (folder / "rubric.v2.txt").write_text("Default v2", encoding="utf-8")
    (folder / "rubric.small.v1.txt").write_text("Small v1", encoding="utf-8")
    (folder / "rubric.small.v3.txt").write_text("Small v3", encoding="utf-8")
    (folder / "notes.v1.txt").write_text("Notes", encoding="utf-8")
    return tmp_path


def test_pl5_default_variant_only(tiered: Path) -> None:
    p = load_prompt("scorer", "notes", prompts_dir=tiered, tier=CapabilityTier.SMALL)
    assert (p.text, p.tier, p.ref) == ("Notes", None, "scorer/notes.v1")


def test_pl5_tier_variant_is_chosen_at_its_highest_version(tiered: Path) -> None:
    p = load_prompt("scorer", "rubric", prompts_dir=tiered, tier=CapabilityTier.SMALL)
    assert (p.text, p.tier, p.version) == ("Small v3", CapabilityTier.SMALL, 3)
    pinned = load_prompt("scorer", "rubric", 1, prompts_dir=tiered, tier=CapabilityTier.SMALL)
    assert pinned.text == "Small v1"
    with pytest.raises(PromptNotFoundError):
        load_prompt("scorer", "rubric", 2, prompts_dir=tiered, tier=CapabilityTier.SMALL)


def test_pl5_other_tier_falls_back_to_default(tiered: Path) -> None:
    for tier in (CapabilityTier.MEDIUM, CapabilityTier.LARGE, None):
        p = load_prompt("scorer", "rubric", prompts_dir=tiered, tier=tier)
        assert (p.text, p.tier, p.ref) == ("Default v2", None, "scorer/rubric.v2")


def test_pl5_list_versions_per_variant(tiered: Path) -> None:
    assert list_versions("scorer", "rubric", tiered) == [1, 2]
    assert list_versions("scorer", "rubric", tiered, tier=CapabilityTier.SMALL) == [1, 3]
    assert list_versions("scorer", "rubric", tiered, tier=CapabilityTier.LARGE) == []


def test_pl6_prompt_ref_names_the_tier(tiered: Path) -> None:
    p = load_prompt("scorer", "rubric", prompts_dir=tiered, tier=CapabilityTier.SMALL)
    assert p.ref == "scorer/rubric.small.v3"
    assert p.message("system").prompt_ref == "scorer/rubric.small.v3"


@pytest.mark.parametrize(
    "bad",
    [
        "rubric.tiny.v1.txt",
        "rubric.small.txt",
        "rubric.v0.txt",
        "rubric.v1.md",
        "rubric.Large.v1.txt",
    ],
)
def test_pl5_bad_file_names_are_rejected(tiered: Path, bad: str) -> None:
    (tiered / "scorer" / bad).write_text("x", encoding="utf-8")
    with pytest.raises(PromptFileNameError):
        load_prompt("scorer", "rubric", prompts_dir=tiered, tier=CapabilityTier.SMALL)


def test_pl5_tier_comes_from_the_capability_registry(
    tiered: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scorer role maps to a medium-tier model in models.local.yaml, a small one here."""
    config = load_models_config(find_repo_root() / "config", "local", environ={})
    roles = {**config.roles, Role.SCORER: config.alias_for(Role.EXTRACTOR)}
    small = config.model_copy(update={"roles": roles})
    assert small.capabilities(Role.SCORER).tier == CapabilityTier.SMALL
    monkeypatch.setattr(gateway_client, "_gateway", ModelGateway(small))
    assert active_tier(Role.SCORER) == CapabilityTier.SMALL
    assert active_tier("evals") is None  # not a gateway role
    assert load_prompt(Role.SCORER, "rubric", prompts_dir=tiered).ref == "scorer/rubric.small.v3"

    monkeypatch.setattr(gateway_client, "_gateway", ModelGateway(config))
    assert active_tier(Role.SCORER) == CapabilityTier.MEDIUM
    assert load_prompt(Role.SCORER, "rubric", prompts_dir=tiered).ref == "scorer/rubric.v2"


def test_pl5_fake_profile_uses_default_variants(tiered: Path) -> None:
    """MODEL_PROFILE=fake has no tiers, so fixture hashes and refs stay the same."""
    assert active_tier(Role.SCORER) is None
    assert load_prompt(Role.SCORER, "rubric", prompts_dir=tiered).ref == "scorer/rubric.v2"


def test_pl5_every_repo_prompt_file_follows_the_naming_rule() -> None:
    root = find_repo_root() / "prompts"
    files = [p for p in root.glob("*/*") if p.is_file() and p.name != ".gitkeep"]
    assert files
    bad = [p.name for p in files if not _FILE.match(p.name)]
    assert not bad
