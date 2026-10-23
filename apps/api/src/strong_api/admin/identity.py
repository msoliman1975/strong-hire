"""Who the admins are and their server-side sessions (AA-1, AA-3, AA-8).

- Admins are rows in `admin_users`. An admin with `disabled_at` set is removed: they cannot sign
  in, and removing them revokes all of their sessions. Rows are never deleted, so the table is
  never empty again after the first start and ADMIN_EMAILS is read only once (`seed_admins`).
- A session is a row in `admin_sessions`. The browser holds a random token in the `sh_admin`
  cookie; the row id is the token's SHA-256, so the table alone cannot be used to sign in.
  A session ends 2 h after it was last used (idle) or 12 h after sign-in (absolute), whichever
  comes first. `last_seen_at` is written at most once a minute.

Every function takes `now`, so tests can move time (the app reads it from `AdminAuth.clock`).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.auth.email import EmailSender
from strong_api.auth.google import GoogleClient
from strong_api.auth.magic_links import MagicLinks
from strong_api.auth.passwords import LoginThrottle
from strong_api.auth.settings import AppEnv, AuthSettings
from strong_core.db.models import AdminSession as AdminSessionRow
from strong_core.db.models import AdminUser as AdminUserRow

log = logging.getLogger(__name__)

ADMIN_COOKIE = "sh_admin"
IDLE_TIMEOUT = timedelta(hours=2)
ABSOLUTE_TIMEOUT = timedelta(hours=12)
TOUCH_INTERVAL = timedelta(minutes=1)
ADMIN_LINK_SALT = "strong-hire-admin-link"
SEED_ACTOR = "ADMIN_EMAILS"


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AdminPrincipal:
    """The signed-in admin. Other modules use only `.email` (and `.id`)."""

    id: uuid.UUID
    email: str
    session_id: str
    session_expires_at: datetime


@dataclass
class AdminAuth:
    """What the admin sign-in routes need. Tests swap the parts (and the clock) on
    `app.state.admin_auth`."""

    settings: AuthSettings
    email_sender: EmailSender
    links: MagicLinks
    throttle: LoginThrottle
    google: GoogleClient | None = None
    clock: Callable[[], datetime] = field(default=utcnow)

    @property
    def secure_cookie(self) -> bool:
        return not self.settings.is_local and self.settings.app_env != AppEnv.TEST


# ------------------------------------------------------------------------- admins (AA-1)


async def find_admin(db: AsyncSession, email: str) -> AdminUserRow | None:
    return await db.scalar(select(AdminUserRow).where(AdminUserRow.email == normalize_email(email)))


async def find_active_admin(db: AsyncSession, email: str) -> AdminUserRow | None:
    row = await find_admin(db, email)
    return row if row is not None and row.disabled_at is None else None


async def is_active_admin(db: AsyncSession, email: str | None) -> bool:
    return bool(email) and await find_active_admin(db, str(email)) is not None


async def active_admin_emails(db: AsyncSession) -> set[str]:
    rows = await db.scalars(select(AdminUserRow.email).where(AdminUserRow.disabled_at.is_(None)))
    return set(rows)


async def seed_admins(db: AsyncSession, emails: Iterable[str]) -> int:
    """AA-1: fill an empty `admin_users` from ADMIN_EMAILS. Returns how many rows were added.

    Does nothing once the table has any row, so after the first start the env var is ignored.
    Safe when several API processes start at once: each insert runs in a savepoint, and a
    duplicate (another process won the race) is skipped.
    """
    wanted = sorted({normalize_email(e) for e in emails if e.strip()})
    if not wanted:
        return 0
    if await db.scalar(select(func.count()).select_from(AdminUserRow)):
        return 0
    added = 0
    for email in wanted:
        try:
            async with db.begin_nested():
                db.add(AdminUserRow(email=email, added_by=SEED_ACTOR))
            added += 1
        except IntegrityError:
            continue
    await db.commit()
    return added


async def add_admin(db: AsyncSession, email: str, added_by: str) -> tuple[AdminUserRow, bool]:
    """Add an admin, or turn a removed one back on. Returns (row, changed). The caller
    commits."""
    email = normalize_email(email)
    row = await find_admin(db, email)
    if row is None:
        row = AdminUserRow(email=email, added_by=added_by, added_at=utcnow())
        db.add(row)
        await db.flush()
        return row, True
    if row.disabled_at is None:
        return row, False
    row.disabled_at = None
    row.added_by = added_by
    await db.flush()
    return row, True


async def disable_admin(db: AsyncSession, row: AdminUserRow, now: datetime) -> int:
    """AA-8: remove an admin and revoke all of their sessions. Returns the number of sessions
    revoked. The caller commits."""
    row.disabled_at = now
    return await revoke_all_sessions(db, row.id, now)


# ----------------------------------------------------------------------- sessions (AA-3)


async def create_session(
    db: AsyncSession,
    admin: AdminUserRow,
    now: datetime,
    *,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, AdminSessionRow]:
    """Start a session and commit it. Returns the raw cookie token and the row."""
    token = secrets.token_urlsafe(32)
    row = AdminSessionRow(
        id=hash_token(token),
        admin_user_id=admin.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + ABSOLUTE_TIMEOUT,
        ip=(ip or None) and ip[:45],
        user_agent=(user_agent or None) and user_agent[:500],
    )
    db.add(row)
    await db.commit()
    return token, row


def session_live(row: AdminSessionRow, now: datetime) -> bool:
    return (
        row.revoked_at is None
        and now < as_utc(row.expires_at)
        and now < as_utc(row.last_seen_at) + IDLE_TIMEOUT
    )


def session_ends_at(row: AdminSessionRow) -> datetime:
    """When the session ends if it is not used again."""
    return min(as_utc(row.expires_at), as_utc(row.last_seen_at) + IDLE_TIMEOUT)


async def resolve_session(db: AsyncSession, token: str, now: datetime) -> AdminPrincipal | None:
    """The admin behind a cookie token, or None when the session is unknown, revoked, idle
    too long, past its absolute end, or its admin was removed. Refreshes `last_seen_at` at most
    once a minute."""
    if not token or len(token) > 200:
        return None
    row = await db.get(AdminSessionRow, hash_token(token))
    if row is None or not session_live(row, now):
        return None
    admin = await db.get(AdminUserRow, row.admin_user_id)
    if admin is None or admin.disabled_at is not None:
        return None
    if now - as_utc(row.last_seen_at) >= TOUCH_INTERVAL:
        row.last_seen_at = now
        await db.commit()
    return AdminPrincipal(
        id=admin.id, email=admin.email, session_id=row.id, session_expires_at=session_ends_at(row)
    )


async def revoke_session(db: AsyncSession, session_id: str, now: datetime) -> bool:
    """Revoke one session. The caller commits. False if it was not live."""
    result = await db.execute(
        update(AdminSessionRow)
        .where(AdminSessionRow.id == session_id, AdminSessionRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return bool(getattr(result, "rowcount", 0))


async def revoke_all_sessions(db: AsyncSession, admin_user_id: uuid.UUID, now: datetime) -> int:
    result = await db.execute(
        update(AdminSessionRow)
        .where(
            AdminSessionRow.admin_user_id == admin_user_id,
            AdminSessionRow.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def live_sessions(
    db: AsyncSession, admin_user_id: uuid.UUID, now: datetime
) -> list[AdminSessionRow]:
    rows = await db.scalars(
        select(AdminSessionRow)
        .where(
            AdminSessionRow.admin_user_id == admin_user_id,
            AdminSessionRow.revoked_at.is_(None),
        )
        .order_by(AdminSessionRow.created_at.desc())
    )
    return [r for r in rows if session_live(r, now)]
