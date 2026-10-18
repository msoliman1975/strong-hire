"""Email and password sign-in (AC-4, AC-5, AC-6): hashing, password rules and the lockout.

Hashes are Argon2id with the argon2-cffi defaults. A failed sign-in counts against the email;
after LOCKOUT_FAILURES failures in LOCKOUT_WINDOW_S the email is refused until the window ends.
"""

from __future__ import annotations

import hashlib
import time
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from redis.asyncio import Redis

MIN_LENGTH = 8
MAX_LENGTH = 128
LOCKOUT_FAILURES = 5
LOCKOUT_WINDOW_S = 15 * 60

_hasher = PasswordHasher()
# Verified when the email has no password, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash("strong-hire-no-such-user")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def fingerprint(password_hash: str | None) -> str:
    """A short digest of the current hash. Links carry it, so they stop working once the
    password changes."""
    return hashlib.sha256((password_hash or "none").encode()).hexdigest()[:16]


def password_problem(password: str, email: str) -> str | None:
    """The rule the password breaks, as a sentence for the user, or None."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    name = email.split("@", 1)[0].strip().lower()
    if len(name) >= 3 and name in password.lower():
        return "Do not use your email name in the password."
    return None


class LoginThrottle(Protocol):
    async def blocked(self, key: str) -> bool: ...
    async def fail(self, key: str) -> None: ...
    async def reset(self, key: str) -> None: ...


class RedisLoginThrottle:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    @staticmethod
    def _key(key: str) -> str:
        return f"auth:pwfail:{key}"

    async def blocked(self, key: str) -> bool:
        client = Redis.from_url(self._redis_url)
        try:
            count = await client.get(self._key(key))
            return count is not None and int(count) >= LOCKOUT_FAILURES
        finally:
            await client.aclose()

    async def fail(self, key: str) -> None:
        client = Redis.from_url(self._redis_url)
        try:
            count = await client.incr(self._key(key))
            if count == 1:
                await client.expire(self._key(key), LOCKOUT_WINDOW_S)
        finally:
            await client.aclose()

    async def reset(self, key: str) -> None:
        client = Redis.from_url(self._redis_url)
        try:
            await client.delete(self._key(key))
        finally:
            await client.aclose()


class MemoryLoginThrottle:
    """For tests."""

    def __init__(self) -> None:
        self._fails: dict[str, tuple[int, float]] = {}

    def _count(self, key: str) -> int:
        count, until = self._fails.get(key, (0, 0.0))
        return count if until > time.monotonic() else 0

    async def blocked(self, key: str) -> bool:
        return self._count(key) >= LOCKOUT_FAILURES

    async def fail(self, key: str) -> None:
        count = self._count(key)
        until = self._fails[key][1] if count else time.monotonic() + LOCKOUT_WINDOW_S
        self._fails[key] = (count + 1, until)

    async def reset(self, key: str) -> None:
        self._fails.pop(key, None)
