"""Model cost on the sim side (candidate and judge), from token counts and per-alias prices.

The interviewer and scorer run on the main server; their cost shows in that server's LiteLLM
spend, not here. estimate() gives a rough number before a run, for the confirmation prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from strong_core.config import find_repo_root
from strong_core.gateway import Completion
from strong_core.sim import estimate_session

PRICES = find_repo_root() / "evals" / "config" / "prices.yaml"


def load_prices(path: Path = PRICES) -> dict[str, tuple[float, float]]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {k: (float(v[0]), float(v[1])) for k, v in data["llm_per_mtok"].items()}


class CostLimitError(RuntimeError):
    pass


@dataclass
class CostMeter:
    prices: dict[str, tuple[float, float]]
    limit_usd: float = float("inf")
    by_alias: dict[str, dict[str, float]] = field(default_factory=dict)

    def add(self, done: Completion[Any]) -> None:
        row = self.by_alias.setdefault(
            done.model, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0}
        )
        price_in, price_out = self.prices.get(done.model, (0.0, 0.0))
        row["calls"] += 1
        row["input_tokens"] += done.usage.input_tokens
        row["output_tokens"] += done.usage.output_tokens
        row["usd"] += (
            done.usage.input_tokens * price_in + done.usage.output_tokens * price_out
        ) / 1e6
        if self.total_usd > self.limit_usd:
            raise CostLimitError(
                f"sim-side model cost ${self.total_usd:.2f} passed the limit ${self.limit_usd:.2f}"
            )

    @property
    def total_usd(self) -> float:
        return sum(r["usd"] for r in self.by_alias.values())

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {k: dict(v) for k, v in self.by_alias.items()}


def estimate(durations: list[int], prices: dict[str, tuple[float, float]]) -> dict[str, float]:
    """The estimate for a list of sessions (strong_core.sim.estimate_session, summed)."""
    parts = [estimate_session(minutes, prices) for minutes in durations]
    candidate = sum(p.candidate_usd for p in parts)
    judge = sum(p.judge_usd for p in parts)
    server = sum(p.main_server_usd for p in parts)
    return {
        "candidate_usd": candidate,
        "judge_usd": judge,
        "main_server_usd": server,
        "total_usd": candidate + judge + server,
    }
