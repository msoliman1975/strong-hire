"""Token prices per gateway alias, read from config/litellm.<profile>.yaml (model_info).

LiteLLM counts spend from `input_cost_per_token` and `output_cost_per_token`. The app reads the
same numbers to put a cost on each interviewer call (admin traces). An alias without prices,
or a profile without a LiteLLM file (fake), has no cost: the functions return None.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from strong_core.config import get_settings
from strong_core.gateway.types import TokenUsage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenPrice:
    input_per_token: float
    output_per_token: float


@lru_cache(maxsize=16)
def load_token_prices(config_dir: Path, profile: str) -> dict[str, TokenPrice]:
    """Prices by alias from litellm.<profile>.yaml. Empty when the file or prices are missing."""
    path = config_dir / f"litellm.{profile}.yaml"
    if not path.exists():
        return {}
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        log.warning("could not read prices from %s", path, exc_info=True)
        return {}
    prices: dict[str, TokenPrice] = {}
    for entry in data.get("model_list") or []:
        info = entry.get("model_info") or {}
        name = entry.get("model_name")
        if not name or "input_cost_per_token" not in info:
            continue
        prices[str(name)] = TokenPrice(
            float(info.get("input_cost_per_token") or 0.0),
            float(info.get("output_cost_per_token") or 0.0),
        )
    return prices


@dataclass(frozen=True)
class UnitPrice:
    """Speech prices from model_info (OB-2, D-12). None: the provider is not metered."""

    per_second: float | None = None  # stt: input_cost_per_second
    per_character: float | None = None  # tts: input_cost_per_character


@lru_cache(maxsize=16)
def load_unit_prices(config_dir: Path, profile: str) -> dict[str, UnitPrice]:
    """Speech prices by alias from litellm.<profile>.yaml. Empty when there are none."""
    path = config_dir / f"litellm.{profile}.yaml"
    if not path.exists():
        return {}
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        log.warning("could not read prices from %s", path, exc_info=True)
        return {}
    prices: dict[str, UnitPrice] = {}
    for entry in data.get("model_list") or []:
        info = entry.get("model_info") or {}
        name = entry.get("model_name")
        second = info.get("input_cost_per_second")
        char = info.get("input_cost_per_character")
        if not name or (second is None and char is None):
            continue
        prices[str(name)] = UnitPrice(
            float(second) if second is not None else None,
            float(char) if char is not None else None,
        )
    return prices


def speech_cost_usd(
    profile: str,
    alias: str,
    *,
    seconds: float | None = None,
    characters: int | None = None,
    config_dir: Path | None = None,
) -> float | None:
    """The dollar cost of one speech call (seconds for stt, characters for tts), or None when
    the alias has no per-unit price or the amount is unknown."""
    folder = config_dir or get_settings().resolved_config_dir
    price = load_unit_prices(folder, profile).get(alias)
    if price is None:
        return None
    if seconds is not None and price.per_second is not None:
        return seconds * price.per_second
    if characters is not None and price.per_character is not None:
        return characters * price.per_character
    return None


def cost_usd(
    profile: str, alias: str, usage: TokenUsage, config_dir: Path | None = None
) -> float | None:
    """The dollar cost of one call, or None when the alias has no price."""
    folder = config_dir or get_settings().resolved_config_dir
    price = load_token_prices(folder, profile).get(alias)
    if price is None:
        return None
    return usage.input_tokens * price.input_per_token + usage.output_tokens * price.output_per_token
