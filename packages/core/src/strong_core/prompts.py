"""Prompt loader. Templates live in prompts/<role>/ as text files and are never inline strings.

File names:
    <name>.v<N>.txt          the default variant, for example scorer/rubric.v1.txt
    <name>.<tier>.v<N>.txt   a variant for one capability tier (small, medium, large),
                             for example scorer/rubric.small.v1.txt

    prompt = load_prompt("extractor", "job_posting")          # active tier, latest version
    prompt = load_prompt("extractor", "job_posting", version=1)
    msg = prompt.message("system", posting_text=raw)           # Message with prompt_ref set

Variant selection (PL-5): the tier comes from the capability registry entry of the model that
serves the role in the active MODEL_PROFILE (`get_gateway().capabilities(role).tier`), never
from a model name. If the role folder has a file for that tier, the tier variant is used.
Otherwise the default variant is used. Each variant has its own version numbers; the loader
takes the highest version of the chosen variant, or the pinned `version` if one is given.

Templates use $name placeholders (string.Template), which is plain text with no vendor syntax.
The prompt ref travels with the Message so the gateway can report which prompt versions produced
an output (PL-6): "extractor/job_posting.v2" for a default variant and
"scorer/rubric.small.v1" for a tier variant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Literal

from strong_core.config import get_settings
from strong_core.gateway.client import get_gateway
from strong_core.gateway.registry import CapabilityTier
from strong_core.gateway.types import Message, Role

_TIERS = "|".join(re.escape(t.value) for t in CapabilityTier)
_FILE = re.compile(
    rf"^(?P<name>[a-z0-9_]+)(?:\.(?P<tier>{_TIERS}))?\.v(?P<version>[1-9][0-9]*)\.txt$"
)


class PromptNotFoundError(LookupError):
    pass


class PromptFileNameError(ValueError):
    """A file in a prompt folder does not follow <name>[.<tier>].v<N>.txt."""


@dataclass(frozen=True)
class PromptTemplate:
    role: str
    name: str
    version: int
    text: str
    tier: CapabilityTier | None = None

    @property
    def ref(self) -> str:
        variant = f".{self.tier.value}" if self.tier else ""
        return f"{self.role}/{self.name}{variant}.v{self.version}"

    def render(self, **values: object) -> str:
        """Fill $placeholders. A missing value raises KeyError, so typos fail loudly."""
        return Template(self.text).substitute({k: str(v) for k, v in values.items()})

    def message(
        self, role: Literal["system", "user", "assistant"] = "system", **values: object
    ) -> Message:
        return Message(role=role, content=self.render(**values), prompt_ref=self.ref)


def _variants(folder: Path, name: str) -> dict[CapabilityTier | None, list[int]]:
    """Versions per variant (None is the default variant) for every <name>.* file in folder.

    A file that starts with "<name>." but does not match the naming rule raises
    PromptFileNameError, so a typo such as rubric.tiny.v1.txt fails loudly.
    """
    found: dict[CapabilityTier | None, list[int]] = {}
    for path in folder.glob(f"{name}.*"):
        match = _FILE.match(path.name)
        if not match or match["name"] != name:
            raise PromptFileNameError(
                f"Bad prompt file name {path}: use <name>.v<N>.txt or <name>.<tier>.v<N>.txt "
                f"with tier one of {[t.value for t in CapabilityTier]}"
            )
        tier = CapabilityTier(match["tier"]) if match["tier"] else None
        found.setdefault(tier, []).append(int(match["version"]))
    return {tier: sorted(versions) for tier, versions in found.items()}


def list_versions(
    role: str | Role,
    name: str,
    prompts_dir: Path | None = None,
    *,
    tier: CapabilityTier | None = None,
) -> list[int]:
    """Versions of one variant. tier=None lists the default variant."""
    folder = (prompts_dir or get_settings().resolved_prompts_dir) / str(role)
    return _variants(folder, name).get(tier, [])


def active_tier(role: str | Role) -> CapabilityTier | None:
    """Tier of the model that serves `role` in the active MODEL_PROFILE.

    Folders that are not gateway roles (evals, smoke) have no tier.
    """
    try:
        gateway_role = Role(str(role))
    except ValueError:
        return None
    return get_gateway().capabilities(gateway_role).tier


_ACTIVE: Literal["active"] = "active"


def load_prompt(
    role: str | Role,
    name: str,
    version: int | None = None,
    *,
    prompts_dir: Path | None = None,
    tier: CapabilityTier | Literal["active"] | None = _ACTIVE,
) -> PromptTemplate:
    """Load a prompt for `role`.

    tier="active" (the default) reads the tier from the capability registry. Pass a tier to
    choose one, or None to force the default variant.
    """
    root = prompts_dir or get_settings().resolved_prompts_dir
    role_name = str(role)
    wanted = active_tier(role_name) if tier == _ACTIVE else tier
    variants = _variants(root / role_name, name)
    chosen_tier = wanted if wanted is not None and wanted in variants else None
    versions = variants.get(chosen_tier, [])
    if not versions:
        raise PromptNotFoundError(f"No prompt {role_name}/{name}.v<N>.txt in {root}")
    chosen = versions[-1] if version is None else version
    variant = f"{name}.{chosen_tier.value}" if chosen_tier else name
    if chosen not in versions:
        raise PromptNotFoundError(f"{role_name}/{variant}.v{chosen} not found; have {versions}")
    text = (root / role_name / f"{variant}.v{chosen}.txt").read_text(encoding="utf-8")
    return PromptTemplate(role_name, name, chosen, text, chosen_tier)
