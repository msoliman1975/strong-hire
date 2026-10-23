"""Ops controls that change without a redeploy (admin spec OC-1..OC-5, SM-15, custom
spec CU-11).

Values live in the runtime_settings table (key, value_json). Every key has a type and a
default here; a missing row means the default. Reads go through a 10 s in-process cache, so a
change reaches every api, worker and voice process within about 10 s.

    from strong_core import runtime_settings as rs

    if await rs.get(db, rs.SettingKey.SIGNUPS_PAUSED):
        ...
    current = await rs.get_all(db)          # a RuntimeSettings with every key
    await rs.set(db, "site_banner", {...}, actor="admin@example.com")   # caller commits

`set` validates the value, writes the row and clears this process's cache. The caller writes
the audit log row (AA-6) in the same transaction and commits.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import RuntimeSetting

log = logging.getLogger(__name__)

CACHE_TTL_S = 10.0
DEFAULT_DAILY_SPEND_CAP_USD = 25.0  # D-6
DEFAULT_SIM_MAX_LIVE_SESSIONS = 3  # D-17


class SettingKey(StrEnum):
    SIGNUPS_PAUSED = "signups_paused"  # OC-1
    SESSIONS_PAUSED_VOICE = "sessions_paused_voice"  # OC-2
    SESSIONS_PAUSED_TEXT = "sessions_paused_text"  # OC-2
    DAILY_SPEND_CAP_USD = "daily_spend_cap_usd"  # OC-3
    SITE_BANNER = "site_banner"  # OC-4
    JOBS_PAUSED = "jobs_paused"  # OC-5
    SIM_PAUSED = "sim_paused"  # SM-15
    SIM_MAX_LIVE_SESSIONS = "sim_max_live_sessions"  # SM-3, SM-15
    CUSTOM_INTERVIEW_ACCESS = "custom_interview_access"  # CU-11


class JobKind(StrEnum):
    """OC-5: background job types that can be paused."""

    GAP_ANALYSIS = "gap_analysis"
    SCORING = "scoring"


class CustomInterviewAccess(StrEnum):
    """CU-11: who may run a Custom interview. Everyone while we test; paid plans when live."""

    EVERYONE = "everyone"
    PAID_ONLY = "paid_only"


class SiteBanner(BaseModel):
    """OC-4: a banner in the candidate app until `until`."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    severity: Literal["info", "warning", "critical"] = "info"
    until: datetime

    def active(self, now: datetime) -> bool:
        return now < self.until


class RuntimeSettings(BaseModel):
    """Every ops control with its type and default. Field names are the setting keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signups_paused: bool = False
    sessions_paused_voice: bool = False
    sessions_paused_text: bool = False
    daily_spend_cap_usd: float = Field(default=DEFAULT_DAILY_SPEND_CAP_USD, ge=0)
    site_banner: SiteBanner | None = None
    jobs_paused: list[JobKind] = Field(default_factory=list)
    sim_paused: bool = False
    sim_max_live_sessions: int = Field(
        default=DEFAULT_SIM_MAX_LIVE_SESSIONS,
        ge=0,
        le=20,
        description="SM-3: a sim run does not start while this many real sessions are live. "
        "0 turns the limit off.",
    )
    custom_interview_access: CustomInterviewAccess = CustomInterviewAccess.EVERYONE


KEYS: tuple[str, ...] = tuple(SettingKey)
assert frozenset(KEYS) == frozenset(RuntimeSettings.model_fields), "keys and fields differ"

DEFAULTS = RuntimeSettings()

# One validator per key, with the field's constraints (for example ge=0 on the spend cap).
_adapters: dict[str, TypeAdapter[Any]] = {
    name: TypeAdapter(field.rebuild_annotation())
    for name, field in RuntimeSettings.model_fields.items()
}


class UnknownSettingError(KeyError):
    pass


def _key(key: str) -> str:
    name = str(key)
    if name not in _adapters:
        raise UnknownSettingError(name)
    return name


def validate(key: str, value: Any) -> Any:
    """The typed value for `key`, or a pydantic ValidationError."""
    return _adapters[_key(key)].validate_python(value)


# --- cache ---------------------------------------------------------------------------------

_cache: tuple[float, RuntimeSettings] | None = None


def clear_cache() -> None:
    global _cache
    _cache = None


async def _load(session: AsyncSession) -> RuntimeSettings:
    rows = (await session.execute(select(RuntimeSetting.key, RuntimeSetting.value_json))).all()
    values: dict[str, Any] = {}
    for key, raw in rows:
        if key not in _adapters:
            continue  # a key from a newer release, or a removed one
        try:
            values[key] = validate(key, raw)
        except ValidationError:
            log.warning("runtime setting %s has an invalid value; using the default", key)
    return DEFAULTS.model_copy(update=values)


async def get_all(session: AsyncSession) -> RuntimeSettings:
    """All settings, from the cache when it is under 10 s old."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_TTL_S:
        return _cache[1]
    current = await _load(session)
    _cache = (now, current)
    return current


async def get(session: AsyncSession, key: str) -> Any:
    """One setting's typed value (the default when no row exists)."""
    return getattr(await get_all(session), _key(key))


async def set(session: AsyncSession, key: str, value: Any, actor: str) -> Any:
    """Validate and write one setting. Flushes but does not commit. Returns the typed value."""
    name = _key(key)
    typed = validate(name, value)
    stored = _adapters[name].dump_python(typed, mode="json")
    row = await session.get(RuntimeSetting, name)
    if row is None:
        session.add(RuntimeSetting(key=name, value_json=stored, updated_by=actor))
    else:
        row.value_json = stored
        row.updated_by = actor
        row.updated_at = datetime.now(UTC)
    await session.flush()
    clear_cache()
    return typed
