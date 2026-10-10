"""PL-1, PL-2: tiny, local and hosted profiles switch by config only; six roles pass a smoke test.

The live tests call real models and are skipped unless SMOKE_LIVE=1. Run them with
./scripts/models.ps1 smoke [-Profile hosted]. The hosted test also skips when the provider key
named in models.hosted.yaml (requires_env) is not set.
"""

from __future__ import annotations

import io
import os
import wave

import pytest
import yaml
from pydantic import ValidationError

from strong_core.config import Settings, find_repo_root
from strong_core.gateway import Role, build_gateway, load_models_config
from strong_core.gateway.registry import ModelCapabilities, ModelKind, VoiceGender
from strong_core.gateway.smoke import main as smoke_main
from strong_core.gateway.smoke import run_smoke

REPO = find_repo_root()
CONFIG = REPO / "config"
PROFILES = ["tiny", "local", "hosted", "claude"]


def _litellm_aliases(profile: str) -> set[str]:
    data = yaml.safe_load((CONFIG / f"litellm.{profile}.yaml").read_text(encoding="utf-8"))
    return {entry["model_name"] for entry in data["model_list"]}


@pytest.mark.parametrize("profile", PROFILES)
def test_pl1_every_alias_exists_in_litellm(profile: str) -> None:
    cfg = load_models_config(CONFIG, profile, environ={})
    aliases = _litellm_aliases(profile)
    assert set(cfg.models) <= aliases, "models.*.yaml lists an alias LiteLLM does not serve"
    for role in Role:
        assert cfg.alias_for(role) in aliases


@pytest.mark.parametrize("profile", PROFILES)
def test_pl1_capability_registry_is_filled(profile: str) -> None:
    cfg = load_models_config(CONFIG, profile, environ={})
    for alias, caps in cfg.models.items():
        if caps.kind == ModelKind.CHAT:
            assert caps.json_mode or caps.supports_tools, alias
            assert caps.context_window >= 8192, alias
        if caps.kind == ModelKind.TTS:
            assert caps.sample_rate and caps.streaming, alias
            assert "voice" in caps.options, alias
            assert caps.voice_gender is not None, f"{alias}: set voice_gender (IV-10)"


def test_iv10_voice_gender_is_for_tts_only() -> None:
    """IV-10: the TTS voice says how it sounds, so the live page shows a matching face."""
    caps = ModelCapabilities(kind=ModelKind.TTS, voice_gender=VoiceGender.MALE)
    assert caps.voice_gender == "male"
    with pytest.raises(ValidationError, match="voice_gender is for tts models only"):
        ModelCapabilities(kind=ModelKind.CHAT, voice_gender=VoiceGender.FEMALE)


def test_pl1_profiles_cover_the_same_roles_with_the_same_code() -> None:
    configs = [load_models_config(CONFIG, p, environ={}) for p in PROFILES]
    for cfg in configs:
        assert set(cfg.roles) == set(Role), cfg.profile
    # only the proxy config differs between profiles
    assert len({cfg.gateway.base_url for cfg in configs}) == 1


def test_pl2_tiny_uses_one_small_model_for_all_text_roles() -> None:
    """PL-2: the tiny profile serves the four text roles with one small-tier model."""
    tiny = load_models_config(CONFIG, "tiny", environ={})
    text_roles = [Role.EXTRACTOR, Role.PLANNER, Role.INTERVIEWER, Role.SCORER]
    aliases = {tiny.alias_for(role) for role in text_roles}
    assert len(aliases) == 1
    assert tiny.models[aliases.pop()].tier == "small"


def test_pl1_hosted_needs_only_keys_from_env() -> None:
    hosted = load_models_config(CONFIG, "hosted", environ={})
    assert hosted.gateway.requires_env
    assert hosted.gateway.missing_env({}) == list(hosted.gateway.requires_env)
    keys = {name: "x" for name in hosted.gateway.requires_env}
    assert hosted.gateway.missing_env(keys) == []
    litellm = (CONFIG / "litellm.hosted.yaml").read_text(encoding="utf-8")
    for name in hosted.gateway.requires_env:
        assert f"os.environ/{name}" in litellm
        assert f"{name}=" in (REPO / ".env.example").read_text(encoding="utf-8")


def test_pl1_role_override_points_a_role_at_lm_studio() -> None:
    env = {"MODEL_ROLE_INTERVIEWER": "local-lmstudio"}
    cfg = load_models_config(CONFIG, "local", environ=env)
    assert cfg.alias_for(Role.INTERVIEWER) == "local-lmstudio"
    assert cfg.alias_for(Role.SCORER) == "local-mid"
    lmstudio = yaml.safe_load((CONFIG / "litellm.local.yaml").read_text(encoding="utf-8"))
    entry = next(e for e in lmstudio["model_list"] if e["model_name"] == "local-lmstudio")
    assert entry["litellm_params"]["api_base"] == "http://host.docker.internal:1234/v1"


def test_pl1_role_override_rejects_unknown_alias() -> None:
    with pytest.raises(ValueError, match="not in models"):
        load_models_config(CONFIG, "local", environ={"MODEL_ROLE_PLANNER": "nope"})


async def test_pl1_smoke_passes_on_fake_profile() -> None:
    results = await run_smoke(build_gateway(Settings(model_profile="fake")))
    assert {r.role for r in results} == set(Role)
    assert all(r.ok for r in results), results


def test_pl1_smoke_cli_skips_hosted_without_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hosted = load_models_config(CONFIG, "hosted", environ={})
    for name in hosted.gateway.requires_env:
        monkeypatch.delenv(name, raising=False)
    assert smoke_main(["--profile", "hosted"]) == 2
    assert "SKIP profile=hosted" in capsys.readouterr().out


async def test_fake_synthesize_stream_is_pcm_at_registry_rate() -> None:
    gw = build_gateway(Settings(model_profile="fake"))
    chunks = [c async for c in gw.synthesize_stream("Hello there.")]
    rate = gw.capabilities(Role.TTS).sample_rate
    assert rate and len(chunks) >= 1
    assert sum(len(c) for c in chunks) == len("Hello there.") * rate // 100 * 2
    wav = await gw.synthesize("Hello there.")
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getnchannels() == 1


@pytest.mark.parametrize("profile", PROFILES)
async def test_pl1_live_smoke(profile: str) -> None:
    """All six roles against real models. Needs the models and voice services running."""
    if os.environ.get("SMOKE_LIVE") != "1":
        pytest.skip("set SMOKE_LIVE=1 (./scripts/models.ps1 smoke) to call real models")
    gw = build_gateway(Settings(model_profile=profile))
    missing = gw.config.gateway.missing_env()
    if missing:
        pytest.skip(f"profile {profile} needs {', '.join(missing)}")
    results = await run_smoke(gw)
    failed = [r for r in results if not r.ok]
    assert not failed, failed


def test_pl1_output_mode_follows_the_capability_registry() -> None:
    from pydantic_ai import NativeOutput, ToolOutput

    from strong_core.gateway import ModelGateway
    from strong_core.gateway.smoke import SmokeAnswer

    gw = ModelGateway(load_models_config(CONFIG, "local", environ={}))
    assert isinstance(gw._output_spec(Role.EXTRACTOR, SmokeAnswer), NativeOutput)
    assert isinstance(gw._output_spec(Role.PLANNER, SmokeAnswer), ToolOutput)


@pytest.mark.parametrize("profile", PROFILES)
def test_pl5_every_chat_model_has_a_capability_tier(profile: str) -> None:
    cfg = load_models_config(CONFIG, profile, environ={})
    for alias, caps in cfg.models.items():
        if caps.kind == ModelKind.CHAT:
            assert caps.tier is not None, alias
        else:
            assert caps.tier is None, alias


def test_pl5_tier_is_for_chat_models_only() -> None:
    from pydantic import ValidationError

    from strong_core.gateway import CapabilityTier, ModelCapabilities

    assert ModelCapabilities(tier=CapabilityTier.SMALL).tier == CapabilityTier.SMALL
    with pytest.raises(ValidationError):
        ModelCapabilities(kind=ModelKind.STT, tier=CapabilityTier.SMALL)
