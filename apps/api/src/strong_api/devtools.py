"""Dev-only API: model spend for the top-bar indicator (testing and validation only).

    GET /dev/model-usage   today's and this month's spend against the LiteLLM budgets

It exists only when APP_ENV is local or test, like the dev login. It reads the app key's spend
and its team's spend from LiteLLM with the master key. With no app key (every profile except
claude), nothing is tracked and the web app hides the indicator.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from strong_api.auth.settings import AppEnv, get_auth_settings
from strong_api.inputs.deps import Me
from strong_core.config import get_settings

router = APIRouter(tags=["dev"])


class Budget(BaseModel):
    spend_usd: float
    budget_usd: float | None
    resets_at: datetime | None


class ModelUsage(BaseModel):
    profile: str
    tracked: bool
    today: Budget | None = None
    month: Budget | None = None
    rpm_limit: int | None = None


async def litellm_http() -> AsyncIterator[httpx.AsyncClient]:
    """The LiteLLM admin API, with the master key. Tests replace this dependency."""
    base = (get_settings().model_gateway_url or "http://litellm:4000/v1").removesuffix("/v1")
    master = os.environ.get("LITELLM_MASTER_KEY", "sk-local-dev-only")
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": f"Bearer {master}"}, timeout=5
    ) as http:
        yield http


LiteLLM = Annotated[httpx.AsyncClient, Depends(litellm_http)]


def _budget(data: dict[str, Any]) -> Budget:
    return Budget(
        spend_usd=round(float(data.get("spend") or 0.0), 4),
        budget_usd=data.get("max_budget"),
        resets_at=data.get("budget_reset_at"),
    )


@router.get("/dev/model-usage")
async def model_usage(_: Me, http: LiteLLM) -> ModelUsage:
    """Spend today and this month for the app key (claude profile). Dev and test only."""
    if get_auth_settings().app_env not in (AppEnv.LOCAL, AppEnv.TEST):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    settings = get_settings()
    profile = str(settings.model_profile.value)
    key = settings.model_gateway_api_key
    if not key or key == os.environ.get("LITELLM_MASTER_KEY", "sk-local-dev-only"):
        return ModelUsage(profile=profile, tracked=False)
    try:
        resp = await http.get("/key/info", params={"key": key})
        resp.raise_for_status()
        info: dict[str, Any] = resp.json().get("info") or {}
        month = None
        if info.get("team_id"):
            team = await http.get("/team/info", params={"team_id": info["team_id"]})
            team.raise_for_status()
            month = _budget(team.json().get("team_info") or {})
    except (httpx.HTTPError, ValueError):
        return ModelUsage(profile=profile, tracked=False)
    return ModelUsage(
        profile=profile,
        tracked=True,
        today=_budget(info),
        month=month,
        rpm_limit=info.get("rpm_limit"),
    )
