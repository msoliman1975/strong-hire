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


def cost_usd(
    profile: str, alias: str, usage: TokenUsage, config_dir: Path | None = None
) -> float | None:
    """The dollar cost of one call, or None when the alias has no price."""
    folder = config_dir or get_settings().resolved_config_dir
    price = load_token_prices(folder, profile).get(alias)
    if price is None:
        return None
    return usage.input_tokens * price.input_per_token + usage.output_tokens * price.output_per_token
