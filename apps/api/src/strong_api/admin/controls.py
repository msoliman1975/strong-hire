"""Operations → Controls (admin spec OC-1 to OC-6, AA-6, D-11).

    GET /admin/ops/settings          every runtime setting: value, default, who changed it, when;
                                     plus today's model cost against the daily cap
    PUT /admin/ops/settings/{key}    change one setting {value, reason}; audited before/after
    GET /admin/ops/models            read-only (D-11): this API's MODEL_PROFILE, the role → alias
                                     and tier map from config/models.<profile>.yaml, and the
                                     profile each service reports in its Redis heartbeat

The settings and their types live in strong_core.runtime_settings; the candidate side enforces
them in strong_api.controls. A change reaches every process within about 10 s (its cache).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin
from strong_api.auth.deps import DbSession
from strong_api.controls import spend_today_usd
from strong_core import runtime_settings as rs
from strong_core.config import get_settings
from strong_core.db.models import RuntimeSetting
from strong_core.gateway import Role, get_gateway
from strong_core.gateway.types import CHAT_ROLES

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

HEARTBEAT_PATTERN = "heartbeat:*"
HEARTBEAT_TIMEOUT_S = 2.0
TEST_ONLY_ROLES = frozenset({Role.CANDIDATE, Role.JUDGE})

HeartbeatSource = Callable[[], Awaitable[list[dict[str, Any]]]]


class OpsSettingMeta(BaseModel):
    key: rs.SettingKey
    is_default: bool
    updated_by: str | None = Field(description="Admin email of the last change; None: never set")
    updated_at: datetime | None


class OpsSettings(BaseModel):
    values: rs.RuntimeSettings = Field(description="The value in force for every key")
    defaults: rs.RuntimeSettings
    meta: list[OpsSettingMeta]
    spend_today_usd: float = Field(description="OC-3: model cost since UTC midnight (30 s cache)")


class SettingIn(ActionIn):
    value: Any = Field(description="The new value; its type depends on the key (null clears)")


class RoleModel(BaseModel):
    role: str
    alias: str = Field(description="LiteLLM alias from config/models.<profile>.yaml")
    kind: str
    tier: str | None
    test_only: bool = Field(description="Roles only the AI candidate (P13) uses")


class ServiceProfile(BaseModel):
    service: str
    instance: str
    model_profile: str | None
    version: str | None
    at: datetime | None = Field(description="When the heartbeat was written")


class ModelProfileOut(BaseModel):
    api_profile: str
    roles: list[RoleModel]
    services: list[ServiceProfile] = Field(description="From heartbeat:<service>:<instance>")
    heartbeats_available: bool = Field(description="False when Redis could not be read")
    mismatch: bool = Field(description="A service reports a profile other than the API's")


# --- settings ------------------------------------------------------------------------------


async def _rows(db: DbSession) -> dict[str, RuntimeSetting]:
    rows = (await db.scalars(select(RuntimeSetting))).all()
    return {r.key: r for r in rows}


def _values(rows: dict[str, RuntimeSetting]) -> rs.RuntimeSettings:
    """The values in the table now (not the 10 s cache), defaults for missing or bad rows."""
    update: dict[str, Any] = {}
    for key in rs.KEYS:
        row = rows.get(key)
        if row is None:
            continue
        try:
            update[key] = rs.validate(key, row.value_json)
        except ValidationError:
            log.warning("runtime setting %s has an invalid value; showing the default", key)
    return rs.DEFAULTS.model_copy(update=update)


def _dump(values: rs.RuntimeSettings, key: str) -> Any:
    return values.model_dump(mode="json")[key]


async def _settings_out(db: DbSession) -> OpsSettings:
    rows = await _rows(db)
    values = _values(rows)
    meta = [
        OpsSettingMeta(
            key=rs.SettingKey(key),
            is_default=_dump(values, key) == _dump(rs.DEFAULTS, key),
            updated_by=rows[key].updated_by if key in rows else None,
            updated_at=rows[key].updated_at if key in rows else None,
        )
        for key in rs.KEYS
    ]
    return OpsSettings(
        values=values,
        defaults=rs.DEFAULTS,
        meta=meta,
        spend_today_usd=float(await spend_today_usd(db)),
    )


@router.get("/ops/settings")
async def get_ops_settings(_: Admin, db: DbSession) -> OpsSettings:
    """OC-1..OC-5: every control, its default, and who changed it last."""
    return await _settings_out(db)


@router.put("/ops/settings/{key}")
async def put_ops_setting(
    key: str, body: SettingIn, admin: AdminWrite, db: DbSession
) -> OpsSettings:
    """Change one control (AA-6: audited with the value before and after)."""
    if key not in rs.KEYS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No setting {key!r}")
    try:
        typed = rs.validate(key, body.value)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid value: {first['msg']}"
        ) from exc
    if isinstance(typed, rs.SiteBanner) and typed.until.tzinfo is None:
        typed = typed.model_copy(update={"until": typed.until.replace(tzinfo=UTC)})
    if isinstance(typed, list):
        typed = sorted(set(typed))  # jobs_paused: one entry per kind, stable order
    before = _values(await _rows(db))
    await rs.set(db, key, typed, actor=admin.email)
    after = before.model_copy(update={key: typed})
    audit_action(
        db,
        admin,
        "ops.setting_changed",
        f"runtime_setting:{key}",
        reason=body.reason,
        before={key: _dump(before, key)},
        after={key: _dump(after, key)},
    )
    await db.commit()
    rs.clear_cache()
    return await _settings_out(db)


# --- model profile (OC-6) ---------------------------------------------------------------------


async def redis_heartbeats() -> list[dict[str, Any]]:
    """Every heartbeat:<service>:<instance> value in Redis (A3 writes them, TTL 60 s)."""
    client = Redis.from_url(get_settings().redis_url)
    try:
        out: list[dict[str, Any]] = []
        async for key in client.scan_iter(match=HEARTBEAT_PATTERN, count=100):
            raw = await client.get(key)
            if raw is None:
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if isinstance(data, dict):
                name = key.decode() if isinstance(key, bytes) else str(key)
                parts = name.split(":", 2)
                data.setdefault("service", parts[1] if len(parts) > 1 else "unknown")
                data.setdefault("instance", parts[2] if len(parts) > 2 else "")
                out.append(data)
        return out
    finally:
        await client.aclose()


def _heartbeat_source(request: Request) -> HeartbeatSource:
    source: HeartbeatSource | None = getattr(request.app.state, "heartbeat_source", None)
    return source or redis_heartbeats


def _when(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


@router.get("/ops/models")
async def get_ops_models(_: Admin, request: Request) -> ModelProfileOut:
    """OC-6, D-11: what runs, read-only. Never names a model: aliases and tiers only."""
    gateway = get_gateway()
    roles: list[RoleModel] = []
    for role in Role:
        caps = gateway.capabilities(role)
        roles.append(
            RoleModel(
                role=role.value,
                alias=gateway.config.alias_for(role),
                kind=caps.kind.value,
                tier=caps.tier.value if caps.tier is not None and role in CHAT_ROLES else None,
                test_only=role in TEST_ONLY_ROLES,
            )
        )
    available = True
    try:
        beats = await asyncio.wait_for(_heartbeat_source(request)(), HEARTBEAT_TIMEOUT_S)
    except Exception as exc:
        log.warning("could not read the service heartbeats: %s", type(exc).__name__)
        beats, available = [], False
    services = sorted(
        (
            ServiceProfile(
                service=str(b.get("service", "unknown")),
                instance=str(b.get("instance", "")),
                model_profile=_text(b.get("model_profile")),
                version=_text(b.get("version")),
                at=_when(b.get("at")),
            )
            for b in beats
        ),
        key=lambda s: (s.service, s.instance),
    )
    profile = gateway.profile
    mismatch = any(s.model_profile not in (None, profile) for s in services)
    return ModelProfileOut(
        api_profile=profile,
        roles=roles,
        services=services,
        heartbeats_available=available,
        mismatch=mismatch,
    )
