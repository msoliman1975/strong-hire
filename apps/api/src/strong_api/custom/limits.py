"""Fair-use limits for the CU-5 check (one model call per request) and saved questions (CU-8).

The check limit is a sliding window per user, kept in the API process. Over the limit the API
answers 429 with detail {"code": "rate_limited", "message", "retry_after_s"} and a Retry-After
header, like the gap analysis limit (GA-4). With several API processes each keeps its own count,
which is fine for a fair-use limit.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CustomSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    custom_check_per_minute: int = Field(default=20, ge=1, description="CU-5 checks per minute.")
    custom_check_per_day: int = Field(default=300, ge=1, description="CU-5 checks per day.")
    saved_questions_max: int = Field(default=100, ge=1, description="CU-8: saved per user.")


@lru_cache
def get_custom_settings() -> CustomSettings:
    return CustomSettings()


class SlidingWindowLimiter:
    """Allows `per_minute` calls a minute and `per_day` a day for each key."""

    def __init__(self) -> None:
        self._calls: dict[uuid.UUID, deque[float]] = {}

    def hit(self, key: uuid.UUID, per_minute: int, per_day: int, now: float | None = None) -> int:
        """Record a call. Returns 0 when allowed, else the seconds to wait (nothing recorded)."""
        now = time.monotonic() if now is None else now
        calls = self._calls.setdefault(key, deque())
        while calls and calls[0] <= now - 86_400:
            calls.popleft()
        if len(calls) >= per_day:
            return max(1, int(calls[0] + 86_400 - now) + 1)
        recent = [t for t in calls if t > now - 60]
        if len(recent) >= per_minute:
            return max(1, int(recent[0] + 60 - now) + 1)
        calls.append(now)
        return 0
