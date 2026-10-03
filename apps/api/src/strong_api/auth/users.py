"""User lookup and sign-up. Each new user gets a personal org (spec: Data model)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import AuditLog, Org, User
from strong_core.schemas import AuthProvider, OrgType


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def find_user(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(func.lower(User.email) == normalize_email(email)))
    return result.scalar_one_or_none()


async def get_user(db: AsyncSession, user_id: str) -> User | None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    return await db.get(User, uid)


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    provider: AuthProvider,
    age_confirmed: bool,
    terms_accepted: bool,
    training_consent: bool,
) -> User:
    """Create the personal org and the user, and record the sign-up confirmations.

    There is no column for the 18+ confirmation, so it is kept in the audit log entry.
    """
    if not (age_confirmed and terms_accepted):
        raise ValueError("sign-up needs the 18+ confirmation and accepted terms")
    email = normalize_email(email)
    org = Org(name=email, type=OrgType.PERSONAL, plan="free")
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id, email=email, auth_provider=provider, training_consent=training_consent
    )
    db.add(user)
    await db.flush()
    db.add(
        AuditLog(
            org_id=org.id,
            actor=email,
            action="user.signup",
            entity=f"user:{user.id}",
            details_json={
                "auth_provider": provider.value,
                "age_confirmed_18_plus": age_confirmed,
                "terms_accepted": terms_accepted,
                "training_consent": training_consent,
            },
        )
    )
    await db.commit()
    await db.refresh(user)
    return user
