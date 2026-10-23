"""Speech "hosted equivalent" and the server share per session (admin spec D-12, OB-15).

Session cost counts metered providers only: self-hosted speech is written with cost 0 and
cost_known false (OB-2). Two other numbers stay apart from it:

- hosted_equivalent_usd(rows, profile): what the self-hosted speech would have cost from a
  hosted provider, from shadow per-unit prices in config/litellm.<profile>.yaml model_info:
  `shadow_cost_per_second` (stt) and `shadow_cost_per_character` (tts). They are estimates to
  edit. Shown on the Spend page only.
- server_share_per_session(db, month): INFRA_MONTHLY_USD divided by the month's completed
  sessions. Shown on the overview as its own line, never added into session rows.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.config import get_settings
from strong_core.db.models import InterviewSession
from strong_core.gateway.registry import load_models_config
from strong_core.gateway.types import Role
from strong_core.schemas.enums import SessionStatus

log = logging.getLogger(__name__)

SHADOW_KEYS = {Role.STT: "shadow_cost_per_second", Role.TTS: "shadow_cost_per_character"}


@lru_cache(maxsize=16)
def load_shadow_prices(config_dir: Path, profile: str) -> dict[str, float]:
    """Shadow price per unit by alias (seconds for stt, characters for tts). Empty if none."""
    path = config_dir / f"litellm.{profile}.yaml"
    if not path.exists():
        return {}
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        log.warning("could not read shadow prices from %s", path, exc_info=True)
        return {}
    prices: dict[str, float] = {}
    for entry in data.get("model_list") or []:
        info = entry.get("model_info") or {}
        name = entry.get("model_name")
        for key in SHADOW_KEYS.values():
            if name and info.get(key) is not None:
                prices[str(name)] = float(info[key])
    return prices


def shadow_price(role: Role, profile: str, config_dir: Path | None = None) -> float | None:
    """The shadow price per unit for the alias that serves `role` in `profile`, if any."""
    if role not in SHADOW_KEYS:
        return None
    folder = config_dir or get_settings().resolved_config_dir
    try:
        alias = load_models_config(folder, profile).alias_for(role)
    except Exception:
        return None  # no models.<profile>.yaml (fake) or no such role
    return load_shadow_prices(folder, profile).get(alias)


class UsageRow(Protocol):
    """A usage_events row, or anything with the same fields."""

    @property
    def role(self) -> str | None: ...

    @property
    def units(self) -> Decimal: ...

    @property
    def cost_known(self) -> bool: ...


@dataclass(frozen=True)
class Usage:
    role: str | None
    units: Decimal
    cost_known: bool = False


def hosted_equivalent_usd(
    rows: Iterable[UsageRow], profile: str, *, config_dir: Path | None = None
) -> Decimal:
    """D-12: hosted cost of the self-hosted (cost_known false) stt and tts rows."""
    prices: dict[str, float | None] = {}
    total = Decimal(0)
    for row in rows:
        if row.cost_known or row.role not in (Role.STT.value, Role.TTS.value):
            continue
        if row.role not in prices:
            prices[row.role] = shadow_price(Role(row.role), profile, config_dir)
        price = prices[row.role]
        if price is not None:
            total += Decimal(str(row.units)) * Decimal(str(price))
    return total.quantize(Decimal("0.000001"))


def month_bounds(month: date) -> tuple[datetime, datetime]:
    start = datetime(month.year, month.month, 1, tzinfo=UTC)
    end = (
        datetime(month.year + 1, 1, 1, tzinfo=UTC)
        if month.month == 12
        else datetime(month.year, month.month + 1, 1, tzinfo=UTC)
    )
    return start, end


async def completed_sessions_in_month(db: AsyncSession, month: date) -> int:
    start, end = month_bounds(month)
    count = await db.scalar(
        select(func.count())
        .select_from(InterviewSession)
        .where(
            InterviewSession.status == SessionStatus.COMPLETED,
            InterviewSession.ended_at >= start,
            InterviewSession.ended_at < end,
        )
    )
    return int(count or 0)


async def server_share_per_session(
    db: AsyncSession, month: date, *, infra_monthly_usd: float | None = None
) -> float | None:
    """OB-15: INFRA_MONTHLY_USD / completed sessions that ended in `month`. None when the
    monthly cost is not set or no session completed."""
    monthly = (
        infra_monthly_usd if infra_monthly_usd is not None else get_settings().infra_monthly_usd
    )
    if not monthly:
        return None
    sessions = await completed_sessions_in_month(db, month)
    if sessions == 0:
        return None
    return round(monthly / sessions, 4)
