"""Role-to-model mapping and the capability registry, loaded from config/models.<profile>.yaml."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from strong_core.gateway.types import CHAT_ROLES, Role


class ModelKind(StrEnum):
    CHAT = "chat"
    STT = "stt"
    TTS = "tts"


class VoiceGender(StrEnum):
    """How a TTS voice sounds. The live page shows an interviewer face that matches it (IV-10)."""

    FEMALE = "female"
    MALE = "male"


class CapabilityTier(StrEnum):
    """How strong a chat model is. The prompt loader picks prompt variants by tier (PL-5)."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class ModelCapabilities(BaseModel):
    """What a model can do. Code checks these, never model names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ModelKind = ModelKind.CHAT
    supports_tools: bool = False
    json_mode: bool = False
    context_window: int = Field(default=8192, ge=512)
    tier: CapabilityTier | None = Field(
        default=None,
        description="Chat only: capability tier. Prompts with a variant for this tier use it; "
        "no tier means the default prompt variant.",
    )
    streaming: bool = Field(
        default=False, description="TTS only: the server streams audio chunks as it renders."
    )
    sample_rate: int | None = Field(
        default=None, ge=8000, description="TTS only: sample rate of the raw PCM output, in Hz."
    )
    options: dict[str, str] = Field(
        default_factory=dict, description="Per-model request options, such as a TTS voice."
    )
    voice_gender: VoiceGender | None = Field(
        default=None,
        description="TTS only: whether the voice in options sounds female or male, so the "
        "interviewer avatar matches it.",
    )

    @model_validator(mode="after")
    def _tier_only_for_chat(self) -> ModelCapabilities:
        if self.tier is not None and self.kind != ModelKind.CHAT:
            raise ValueError(f"tier is for chat models only, not {self.kind.value}")
        if self.voice_gender is not None and self.kind != ModelKind.TTS:
            raise ValueError(f"voice_gender is for tts models only, not {self.kind.value}")
        return self


class GatewayEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = Field(description="OpenAI-compatible base URL, normally the LiteLLM proxy.")
    api_key_env: str | None = Field(
        default=None, description="Environment variable that holds the gateway API key."
    )
    timeout_s: float = Field(default=60.0, gt=0)
    requires_env: tuple[str, ...] = Field(
        default=(),
        description="Environment variables the providers behind the gateway need, such as API "
        "keys. Live smoke tests skip when one is missing.",
    )

    def missing_env(self, environ: Mapping[str, str] | None = None) -> list[str]:
        env = os.environ if environ is None else environ
        return [name for name in self.requires_env if not env.get(name)]


class ModelsConfig(BaseModel):
    """Contents of config/models.<profile>.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str
    gateway: GatewayEndpoint
    roles: dict[Role, str] = Field(description="Role to model alias (a LiteLLM model_name).")
    models: dict[str, ModelCapabilities] = Field(description="Capability registry, by alias.")

    @model_validator(mode="after")
    def _check(self) -> ModelsConfig:
        missing = set(Role) - set(self.roles)
        if missing:
            raise ValueError(f"roles missing from config: {sorted(r.value for r in missing)}")
        for role, alias in self.roles.items():
            caps = self.models.get(alias)
            if caps is None:
                raise ValueError(f"role {role.value} maps to {alias!r}, which is not in models")
            expected = (
                ModelKind.CHAT
                if role in CHAT_ROLES
                else ModelKind.STT
                if role == Role.STT
                else ModelKind.TTS
            )
            if caps.kind != expected:
                raise ValueError(f"role {role.value} needs a {expected.value} model, got {alias!r}")
        return self

    def alias_for(self, role: Role) -> str:
        return self.roles[role]

    def capabilities(self, role: Role) -> ModelCapabilities:
        return self.models[self.roles[role]]


ROLE_OVERRIDE_PREFIX = "MODEL_ROLE_"


def load_models_config(
    config_dir: Path, profile: str, environ: Mapping[str, str] | None = None
) -> ModelsConfig:
    """Read config/models.<profile>.yaml.

    MODEL_ROLE_<ROLE>=<alias> points one role at another alias from the same file without editing
    it, for example MODEL_ROLE_INTERVIEWER=local-lmstudio.
    """
    path = config_dir / f"models.{profile}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No model config for MODEL_PROFILE={profile!r}: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    env = os.environ if environ is None else environ
    roles = data.setdefault("roles", {})
    for role in Role:
        override = env.get(f"{ROLE_OVERRIDE_PREFIX}{role.value.upper()}")
        if override:
            roles[role.value] = override
    return ModelsConfig.model_validate(data)


def fake_models_config() -> ModelsConfig:
    """The built-in config for MODEL_PROFILE=fake. No network, no model."""
    models = {
        f"fake-{role.value}": ModelCapabilities(
            kind=ModelKind.CHAT if role in CHAT_ROLES else ModelKind(role.value),
            supports_tools=role in CHAT_ROLES,
            json_mode=role in CHAT_ROLES,
            context_window=32768,
            streaming=role == Role.TTS,
            sample_rate=16000 if role == Role.TTS else None,
        )
        for role in Role
    }
    return ModelsConfig(
        profile="fake",
        gateway=GatewayEndpoint(base_url="http://fake.invalid"),
        roles={role: f"fake-{role.value}" for role in Role},
        models=models,
    )
