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
    """Signed links for one purpose (the salt): sign-in, confirm email or reset password."""

    def __init__(
        self, secret: str, max_age_s: int, store: UsedTokenStore, *, salt: str = _SALT
    ) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt=salt)
        self._max_age_s = max_age_s
        self._store = store

    def issue(self, email: str, **extra: str) -> str:
        return self._serializer.dumps({**extra, "email": email, "jti": uuid.uuid4().hex})

    def peek(self, token: str) -> dict[str, str]:
        """Check the signature and age without using the token up."""
        try:
            data = self._serializer.loads(token, max_age=self._max_age_s)
        except SignatureExpired as exc:
            raise InvalidMagicLinkError("expired") from exc
        except BadSignature as exc:
            raise InvalidMagicLinkError("invalid") from exc
        if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
            raise InvalidMagicLinkError("invalid")
        if not isinstance(data.get("email"), str) or not isinstance(data.get("jti"), str):
            raise InvalidMagicLinkError("invalid")
        return data

    async def redeem_data(self, token: str) -> dict[str, str]:
        """Return the token's data, and burn the token."""
        data = self.peek(token)
        if not await self._store.claim(data["jti"], self._max_age_s):
            raise InvalidMagicLinkError("used")
        return data

    async def redeem(self, token: str) -> str:
        """Return the email the token was issued for, and burn the token."""
        return (await self.redeem_data(token))["email"]
