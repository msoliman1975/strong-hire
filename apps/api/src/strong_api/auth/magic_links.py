"""Email magic links: signed, time-limited, single-use tokens. Nothing is stored until use."""

from __future__ import annotations

import time
import uuid
from typing import Protocol

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from redis.asyncio import Redis

_SALT = "strong-hire-magic-link"


class InvalidMagicLinkError(Exception):
    """The token is malformed, expired or already used."""


class UsedTokenStore(Protocol):
    async def claim(self, token_id: str, ttl_s: int) -> bool:
        """Mark a token as used. Return False if it was used before."""


class RedisUsedTokenStore:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def claim(self, token_id: str, ttl_s: int) -> bool:
        client = Redis.from_url(self._redis_url)
        try:
            return bool(await client.set(f"auth:magic:{token_id}", "1", nx=True, ex=ttl_s))
        finally:
            await client.aclose()


class MemoryUsedTokenStore:
    """For tests."""

    def __init__(self) -> None:
        self._used: dict[str, float] = {}

    async def claim(self, token_id: str, ttl_s: int) -> bool:
        now = time.monotonic()
        self._used = {k: v for k, v in self._used.items() if v > now}
        if token_id in self._used:
            return False
        self._used[token_id] = now + ttl_s
        return True


class MagicLinks:
    def __init__(self, secret: str, max_age_s: int, store: UsedTokenStore) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt=_SALT)
        self._max_age_s = max_age_s
        self._store = store

    def issue(self, email: str) -> str:
        return self._serializer.dumps({"email": email, "jti": uuid.uuid4().hex})

    async def redeem(self, token: str) -> str:
        """Return the email the token was issued for, and burn the token."""
        try:
            data = self._serializer.loads(token, max_age=self._max_age_s)
        except SignatureExpired as exc:
            raise InvalidMagicLinkError("expired") from exc
        except BadSignature as exc:
            raise InvalidMagicLinkError("invalid") from exc
        email, jti = data.get("email"), data.get("jti")
        if not isinstance(email, str) or not isinstance(jti, str):
            raise InvalidMagicLinkError("invalid")
        if not await self._store.claim(jti, self._max_age_s):
            raise InvalidMagicLinkError("used")
        return email
