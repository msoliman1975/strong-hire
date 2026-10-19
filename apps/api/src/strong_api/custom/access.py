"""CU-11: who may use Custom interviews.

The runtime setting `custom_interview_access` (strong_core.runtime_settings) switches it without
a deploy:

- `everyone` (default while we test): every signed-in user. Custom has no 10-minute mini
  (D-14), so a free account may run a 30-minute Custom session as one of its free interviews
  (`FREE_CUSTOM_DURATION`); 45 minutes still needs the plan. Paid plans count minutes as usual.
- `paid_only`: a user without a paid plan (`Entitlement.full_interviews_allowed`, the same rule
  that allows 30 and 45 minute sessions) gets HTTP 403 with detail
  {"code": "upgrade_required", "message", "upgrade_url"}. The free interview (BL-2) can never
  be Custom then.

The AI candidate (P13) has no plan and is never refused here.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.auth.sim import is_sim_user
from strong_api.billing.entitlements import UPGRADE_PATH, get_entitlement
from strong_api.inputs.deps import CurrentUser
from strong_core import runtime_settings as rs

UPGRADE_REQUIRED = "upgrade_required"
CUSTOM_LOCKED_MESSAGE = (
    "Custom interviews are part of the subscription. Subscribe to build your own interview."
)


FREE_CUSTOM_DURATION = 30
"""CU-11: the Custom session length a free account may run while Custom is open to everyone."""


async def custom_open_to_everyone(db: AsyncSession) -> bool:
    settings = await rs.get_all(db)
    return settings.custom_interview_access == rs.CustomInterviewAccess.EVERYONE


async def custom_allowed(db: AsyncSession, me: CurrentUser) -> bool:
    """True when the user may build and run Custom interviews now (CU-11)."""
    settings = await rs.get_all(db)
    if settings.custom_interview_access != rs.CustomInterviewAccess.PAID_ONLY:
        return True
    if await is_sim_user(db, me.user_id):
        return True
    return (await get_entitlement(db, me.org_id)).full_interviews_allowed


async def ensure_custom_allowed(db: AsyncSession, me: CurrentUser) -> None:
    """Raise HTTP 403 `upgrade_required` when Custom is locked for this user (CU-11)."""
    if not await custom_allowed(db, me):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "code": UPGRADE_REQUIRED,
                "message": CUSTOM_LOCKED_MESSAGE,
                "upgrade_url": UPGRADE_PATH,
            },
        )


async def custom_advice_scope(db: AsyncSession, me: CurrentUser) -> tuple[bool, bool]:
    """CU-10: whether the progress may recommend a Custom session to this user, and whether it
    may be 45 minutes long (a Case category needs that, D-3). Locked users (CU-11) get none."""
    if not await custom_allowed(db, me):
        return False, False
    if await is_sim_user(db, me.user_id):
        return True, True
    return True, (await get_entitlement(db, me.org_id)).full_interviews_allowed
