"""Users and support (AU-1..AU-10, docs/admin-spec.md).

    GET    /admin/users                         search and filter, one page at a time (AU-1)
    GET    /admin/users/{id}                    the user detail (AU-2, AU-6, AU-10)
    POST   /admin/users/{id}/grants             add minutes, free interviews or a comp plan
    DELETE /admin/users/{id}/grants/{grant_id}  revoke a grant (AU-3..AU-5)
    POST   /admin/users/{id}/suspend            suspend; open sessions end (AU-7)
    POST   /admin/users/{id}/unsuspend
    POST   /admin/users/{id}/signout            sign out everywhere: bump session_epoch (AU-8)
    POST   /admin/users/{id}/resend-link        email the user a sign-in link (AU-9)

Writes need `X-Admin-Request: 1` and a reason, and write an audit row (AA-5, AA-6).

D-8 / AA-11: resumes and gap analyses are metadata only. No route here reads their content
columns into a response; `tests/test_admin_users.py` walks the OpenAPI document to check it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin, admin_settings
from strong_api.admin.identity import active_admin_emails, is_active_admin
from strong_api.admin.router import _costs, _pairs, _session_out
from strong_api.admin.schemas import AdminAuditEntry
from strong_api.admin.users_schemas import (
    AdminActionOut,
    AdminEntitlement,
    AdminGapMeta,
    AdminGrant,
    AdminJobTarget,
    AdminOrg,
    AdminRefund,
    AdminResumeMeta,
    AdminStoryMeta,
    AdminSubscription,
    AdminUser,
    AdminUserDetail,
    AdminUserPage,
    AdminUserProfile,
    GrantIn,
    PlanName,
    StripeMode,
    UserStatus,
)
from strong_api.admin.voice_rooms import get_voice_rooms
from strong_api.auth.deps import DbSession
from strong_api.auth.magic_links import MagicLinks
from strong_api.billing.entitlements import (
    PAID_STATUSES,
    Entitlement,
    get_entitlement,
    get_subscription,
    grant_is_active,
)
from strong_api.billing.settings import BillingSettings
from strong_api.billing.webhooks import REFUND_ACTION
from strong_api.sessions.router import OPEN, _end, _runners
from strong_core.db.models import (
    AuditLog,
    Company,
    GapAnalysis,
    InterviewSession,
    JobTarget,
    MinuteGrant,
    Org,
    Resume,
    Scorecard,
    Story,
    Subscription,
    UsageEvent,
    User,
)
from strong_core.schemas import SessionChannel, SessionStatus
from strong_core.schemas.enums import GrantKind, StoryStatus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

DETAIL_SESSIONS = 100
DETAIL_AUDIT = 200
PRIVACY_ACTIONS = (
    "account.export_requested",
    "account.export_downloaded",
    "account.deleted",
    "account.files_deleted",
)
RESEND_ACTION = "user.sign_in_link_sent"
RESEND_LIMIT = 3  # links per user per window (AU-9)
RESEND_WINDOW = timedelta(minutes=15)


# ---------------------------------------------------------------- helpers


def _billing(request: Request) -> BillingSettings | None:
    settings: BillingSettings | None = getattr(request.app.state, "billing_settings", None)
    return settings


def stripe_mode(settings: BillingSettings | None) -> StripeMode | None:
    """test or live, from the Stripe secret key prefix (sk_test_, rk_live_, ...)."""
    secret = settings.stripe_secret_key if settings is not None else None
    key = secret.get_secret_value() if secret is not None else ""
    if "_test_" in key[:8]:
        return "test"
    if "_live_" in key[:8]:
        return "live"
    return None


def stripe_customer_url(customer_id: str | None, mode: StripeMode | None) -> str | None:
    if not customer_id:
        return None
    prefix = "test/" if mode == "test" else ""
    return f"https://dashboard.stripe.com/{prefix}customers/{quote(customer_id)}"


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _paid_clause(now: datetime) -> ColumnElement[bool]:
    """SQL for "paid": an active subscription or an active comp plan grant."""
    sub_paid = exists().where(
        Subscription.org_id == User.org_id, Subscription.status.in_(PAID_STATUSES)
    )
    comp = exists().where(
        MinuteGrant.org_id == User.org_id,
        MinuteGrant.kind == GrantKind.COMP_PLAN,
        MinuteGrant.revoked_at.is_(None),
        or_(MinuteGrant.expires_at.is_(None), MinuteGrant.expires_at > now),
    )
    return or_(sub_paid, comp)


def _user_out(user: User, ent: Entitlement, interviews: int, is_admin: bool) -> AdminUser:
    return AdminUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        auth_provider=user.auth_provider,
        created_at=user.created_at,
        last_sign_in_at=user.last_sign_in_at,
        plan=ent.plan,
        subscription_status=ent.status,
        comp_until=ent.comp_until,
        minutes_used=ent.minutes_used,
        minutes_cap=ent.minutes_cap,
        minutes_left=ent.minutes_left,
        free_interviews_left=ent.free_interviews_left,
        training_consent=user.training_consent,
        interviews=interviews,
        is_admin=is_admin,
        status="suspended" if user.suspended_at is not None else "active",
        suspended_at=user.suspended_at,
    )


def _grant_out(grant: MinuteGrant, now: datetime) -> AdminGrant:
    return AdminGrant(
        id=grant.id,
        kind=grant.kind,
        amount=grant.amount,
        expires_at=grant.expires_at,
        reason=grant.reason,
        granted_by=grant.granted_by,
        created_at=grant.created_at,
        revoked_at=grant.revoked_at,
        revoked_by=grant.revoked_by,
        active=grant_is_active(grant, now),
    )


def _audit_out(row: AuditLog) -> AdminAuditEntry:
    return AdminAuditEntry(
        id=row.id,
        at=row.at,
        actor=row.actor,
        action=row.action,
        entity=row.entity,
        org_id=row.org_id,
        details=row.details_json,
    )


async def _get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def _interview_counts(db: AsyncSession, org_ids: list[uuid.UUID]) -> dict[Any, Any]:
    if not org_ids:
        return {}
    return _pairs(
        await db.execute(
            select(InterviewSession.org_id, func.count(InterviewSession.id))
            .where(InterviewSession.org_id.in_(org_ids))
            .group_by(InterviewSession.org_id)
        )
    )


# ---------------------------------------------------------------- AU-1 list


@router.get("/users")
async def list_users(
    db: DbSession,
    admin: Admin,
    request: Request,
    q: Annotated[str | None, Query(max_length=200, description="Email, name or user id.")] = None,
    plan: PlanName | None = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    signed_up_from: Annotated[date | None, Query(description="UTC day, inclusive.")] = None,
    signed_up_to: Annotated[date | None, Query(description="UTC day, inclusive.")] = None,
    last_sign_in_from: Annotated[date | None, Query(description="UTC day, inclusive.")] = None,
    last_sign_in_to: Annotated[date | None, Query(description="UTC day, inclusive.")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminUserPage:
    """Users, newest first, that match every filter given (AU-1)."""
    now = datetime.now(UTC)
    conditions: list[ColumnElement[bool]] = []
    text = (q or "").strip()
    if text:
        try:
            conditions.append(User.id == uuid.UUID(text))
        except ValueError:
            like = f"%{text.lower()}%"
            conditions.append(
                or_(func.lower(User.email).like(like), func.lower(User.full_name).like(like))
            )
    if plan is not None:
        paid = _paid_clause(now)
        conditions.append(paid if plan == "paid" else ~paid)
    if user_status == "suspended":
        conditions.append(User.suspended_at.is_not(None))
    elif user_status == "active":
        conditions.append(User.suspended_at.is_(None))
    if signed_up_from is not None:
        conditions.append(User.created_at >= _day_start(signed_up_from))
    if signed_up_to is not None:
        conditions.append(User.created_at < _day_start(signed_up_to + timedelta(days=1)))
    if last_sign_in_from is not None:
        conditions.append(User.last_sign_in_at >= _day_start(last_sign_in_from))
    if last_sign_in_to is not None:
        conditions.append(User.last_sign_in_at < _day_start(last_sign_in_to + timedelta(days=1)))
    where = and_(*conditions) if conditions else None

    count_query = select(func.count()).select_from(User)
    query = select(User).order_by(User.created_at.desc(), User.id)
    if where is not None:
        count_query = count_query.where(where)
        query = query.where(where)
    total = int(await db.scalar(count_query) or 0)
    users = list(await db.scalars(query.offset((page - 1) * page_size).limit(page_size)))

    admins = await active_admin_emails(db)  # AA-1: admin_users, not ADMIN_EMAILS
    billing = _billing(request)
    counts = await _interview_counts(db, [u.org_id for u in users])
    rows = []
    for user in users:
        ent = await get_entitlement(db, user.org_id, billing, now)
        rows.append(
            _user_out(user, ent, int(counts.get(user.org_id, 0)), user.email.lower() in admins)
        )
    return AdminUserPage(users=rows, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------- AU-2 detail


def _job_title(row: JobTarget) -> tuple[str | None, str | None]:
    """Company and title from the extracted posting (no other posting fields)."""
    parsed = row.parsed_json if isinstance(row.parsed_json, dict) else {}
    company = parsed.get("company_name")
    title = parsed.get("title")
    return (
        str(company) if isinstance(company, str) else None,
        str(title) if isinstance(title, str) else None,
    )


async def _detail(db: AsyncSession, request: Request, user: User) -> AdminUserDetail:
    now = datetime.now(UTC)
    billing = _billing(request)
    org_id = user.org_id
    ent = await get_entitlement(db, org_id, billing, now)
    counts = await _interview_counts(db, [org_id])
    is_admin = await is_active_admin(db, user.email)

    org = await db.get(Org, org_id)
    sub = await get_subscription(db, org_id)
    mode = stripe_mode(billing)
    subscription = (
        AdminSubscription(
            status=sub.status,
            stripe_customer_id=sub.stripe_customer_id,
            stripe_subscription_id=sub.stripe_subscription_id,
            stripe_customer_url=stripe_customer_url(sub.stripe_customer_id, mode),
            stripe_mode=mode,
            period_start=sub.period_start,
            period_end=sub.period_end,
            minutes_cap=sub.minutes_cap or 0,
            minutes_used=sub.minutes_used or 0,
            cancel_at_period_end=bool(sub.cancel_at_period_end),
            created_at=sub.created_at,
        )
        if sub is not None
        else None
    )
    grants = list(
        await db.scalars(
            select(MinuteGrant)
            .where(MinuteGrant.org_id == org_id)
            .order_by(MinuteGrant.created_at.desc(), MinuteGrant.id)
        )
    )

    session_rows = (
        await db.execute(
            select(InterviewSession, Scorecard)
            .outerjoin(Scorecard, Scorecard.session_id == InterviewSession.id)
            .where(InterviewSession.org_id == org_id)
            .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
            .limit(DETAIL_SESSIONS)
        )
    ).all()
    costs = await _costs(db, [s.id for s, _ in session_rows])
    sessions = [_session_out(s, user, card, costs[s.id]) for s, card in session_rows]

    # Only the columns we show are read: no posting text, resume content or gap results.
    targets = await db.execute(
        select(JobTarget, Company.name)
        .outerjoin(Company, Company.id == JobTarget.company_id)
        .where(JobTarget.org_id == org_id)
        .order_by(JobTarget.created_at.desc())
    )
    job_targets = []
    for target, company_name in targets:
        posting_company, title = _job_title(target)
        job_targets.append(
            AdminJobTarget(
                id=target.id,
                company=company_name or posting_company,
                title=title,
                level=target.level,
                created_at=target.created_at,
                archived_at=target.archived_at,
                deleted_at=target.deleted_at,
            )
        )
    resume_rows = await db.execute(
        select(
            Resume.id,
            Resume.uploaded_at,
            Resume.confirmed_at,
            Resume.deleted_at,
            Resume.parsed_json.is_not(None),
        )
        .where(Resume.org_id == org_id)
        .order_by(Resume.uploaded_at.desc())
    )
    resumes = []
    for rid, uploaded, confirmed, deleted, parsed in resume_rows:
        state = (
            "deleted"
            if deleted is not None
            else "confirmed"
            if confirmed is not None
            else "to_confirm"
            if parsed
            else "reading"
        )
        resumes.append(
            AdminResumeMeta(
                id=rid,
                uploaded_at=uploaded,
                confirmed_at=confirmed,
                deleted_at=deleted,
                status=state,
            )
        )
    gap_rows = await db.execute(
        select(
            GapAnalysis.id,
            GapAnalysis.job_target_id,
            GapAnalysis.resume_id,
            GapAnalysis.status,
            GapAnalysis.error.is_not(None),
            GapAnalysis.created_at,
            GapAnalysis.updated_at,
        )
        .where(GapAnalysis.org_id == org_id)
        .order_by(GapAnalysis.created_at.desc())
    )
    gaps = [
        AdminGapMeta(
            id=gid,
            job_target_id=jid,
            resume_id=rid,
            status=gstatus,
            has_error=bool(has_error),
            created_at=created,
            updated_at=updated,
        )
        for gid, jid, rid, gstatus, has_error, created, updated in gap_rows
    ]

    # AD-4: story counts only; the library's text never leaves the user's own app.
    story_total, story_proven, story_last = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Story.status == StoryStatus.PROVEN),
                func.max(Story.created_at),
            ).where(Story.org_id == org_id)
        )
    ).one()

    cost, unknown = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageEvent.cost_usd), 0),
                func.count().filter(UsageEvent.cost_known.is_(False)),
            ).where(UsageEvent.org_id == org_id)
        )
    ).one()

    audit_rows = list(
        await db.scalars(
            select(AuditLog)
            .where(or_(AuditLog.org_id == org_id, AuditLog.entity == f"user:{user.id}"))
            .order_by(AuditLog.at.desc(), AuditLog.id)
            .limit(DETAIL_AUDIT)
        )
    )
    refunds = []
    for row in audit_rows:
        if row.action != REFUND_ACTION:
            continue
        d = row.details_json or {}
        amount = d.get("amount_refunded")
        refunds.append(
            AdminRefund(
                at=row.at,
                charge_id=d.get("charge_id") if isinstance(d.get("charge_id"), str) else None,
                amount_refunded=amount if isinstance(amount, int) else None,
                currency=d.get("currency") if isinstance(d.get("currency"), str) else None,
                livemode=bool(d.get("livemode")),
            )
        )

    return AdminUserDetail(
        user=_user_out(user, ent, int(counts.get(org_id, 0)), is_admin),
        profile=AdminUserProfile(
            full_name=user.full_name,
            current_title=user.current_title,
            years_experience=user.years_experience,
            target_level=user.target_level,
            country=user.country,
            time_zone=user.time_zone,
            linkedin_url=user.linkedin_url,
            profile_completed_at=user.profile_completed_at,
            email_verified_at=user.email_verified_at,
            has_password=user.password_hash is not None,
        ),
        org=AdminOrg(
            id=org.id, name=org.name, type=org.type, plan=org.plan, created_at=org.created_at
        )
        if org is not None
        else None,
        suspended_reason=user.suspended_reason,
        session_epoch=user.session_epoch or 0,
        subscription=subscription,
        entitlement=AdminEntitlement(
            plan=ent.plan,
            minutes_used=ent.minutes_used,
            plan_minutes_cap=ent.plan_minutes_cap,
            minutes_granted=ent.minutes_granted,
            minutes_cap=ent.minutes_cap,
            minutes_left=ent.minutes_left,
            free_interviews_total=ent.free_interviews_total,
            free_interviews_granted=ent.free_interviews_granted,
            free_interviews_used=ent.free_interviews_used,
            free_interviews_left=ent.free_interviews_left,
            comp_until=ent.comp_until,
            block_code=ent.block_code,
        ),
        grants=[_grant_out(g, now) for g in grants],
        sessions=sessions,
        job_targets=job_targets,
        resume_count=len(resumes),
        resumes=resumes,
        gap_analysis_count=len(gaps),
        gap_analyses=gaps,
        stories=AdminStoryMeta(
            total=int(story_total or 0),
            draft=int(story_total or 0) - int(story_proven or 0),
            proven=int(story_proven or 0),
            last_saved_at=story_last,
        ),
        cost_to_date_usd=round(float(Decimal(cost or 0)), 6),
        cost_unknown_events=int(unknown or 0),
        refunds=refunds,
        privacy_actions=[_audit_out(r) for r in audit_rows if r.action in PRIVACY_ACTIONS],
        audit=[_audit_out(r) for r in audit_rows],
    )


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: uuid.UUID, db: DbSession, admin: Admin, request: Request
) -> AdminUserDetail:
    """AU-2. Resumes and gap analyses are metadata only (D-8)."""
    return await _detail(db, request, await _get_user(db, user_id))


# ---------------------------------------------------------------- AU-3..AU-5 grants


def _grant_state(grant: MinuteGrant) -> dict[str, Any]:
    return {
        "id": str(grant.id),
        "kind": grant.kind.value,
        "amount": grant.amount,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
    }


@router.post("/users/{user_id}/grants", status_code=status.HTTP_201_CREATED)
async def add_grant(
    user_id: uuid.UUID, body: GrantIn, db: DbSession, admin: AdminWrite
) -> AdminGrant:
    """Add minutes (AU-3), free interviews (AU-4) or a comp plan (AU-5)."""
    user = await _get_user(db, user_id)
    now = datetime.now(UTC)
    if body.expires_at is not None and body.expires_at <= now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "expires_at is in the past")
    grant = MinuteGrant(
        id=uuid.uuid4(),
        org_id=user.org_id,
        user_id=user.id,
        kind=body.kind,
        amount=body.amount,
        expires_at=body.expires_at,
        reason=body.reason,
        granted_by=admin.email,
        created_at=now,
    )
    db.add(grant)
    audit_action(
        db,
        admin,
        f"user.grant_added.{body.kind.value}",
        f"user:{user.id}",
        org_id=user.org_id,
        reason=body.reason,
        before=None,
        after=_grant_state(grant),
    )
    await db.commit()
    return _grant_out(grant, now)


@router.delete("/users/{user_id}/grants/{grant_id}")
async def revoke_grant(
    user_id: uuid.UUID, grant_id: uuid.UUID, body: ActionIn, db: DbSession, admin: AdminWrite
) -> AdminGrant:
    """Revoke a grant. The row stays in the ledger with revoked_at and revoked_by."""
    user = await _get_user(db, user_id)
    grant = await db.get(MinuteGrant, grant_id)
    if grant is None or grant.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    if grant.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The grant was already revoked")
    before = _grant_state(grant)
    now = datetime.now(UTC)
    grant.revoked_at = now
    grant.revoked_by = admin.email
    audit_action(
        db,
        admin,
        f"user.grant_revoked.{grant.kind.value}",
        f"user:{user.id}",
        org_id=user.org_id,
        reason=body.reason,
        before=before,
        after=_grant_state(grant),
    )
    await db.commit()
    return _grant_out(grant, now)


# ---------------------------------------------------------------- AU-7 suspend


async def _end_open_sessions(request: Request, db: AsyncSession, user: User) -> list[str]:
    """End the user's open sessions the normal way: billed and scored if they started, failed
    if not. Live voice sessions also lose their candidate (the agent's interrupted path)."""
    rows = list(
        await db.scalars(
            select(InterviewSession).where(
                InterviewSession.org_id == user.org_id, InterviewSession.status.in_(OPEN)
            )
        )
    )
    ended = []
    queue = request.app.state.queue
    rooms = get_voice_rooms(request)
    for session in rows:
        live_voice = (
            session.channel == SessionChannel.VOICE and session.status == SessionStatus.IN_PROGRESS
        )
        runner = _runners(request).pop(session.id, None)
        try:
            await _end(db, queue, session, runner)
        except Exception:
            log.exception("could not end session %s of a suspended user", session.id)
            await db.rollback()
            continue
        ended.append(str(session.id))
        if live_voice:
            await rooms.remove_candidate(session.id, user.id)
    return ended


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: uuid.UUID, body: ActionIn, request: Request, db: DbSession, admin: AdminWrite
) -> AdminActionOut:
    """AU-7: the user's requests and sign-ins get 403 with a neutral message. Sessions in
    progress end cleanly."""
    user = await _get_user(db, user_id)
    if user.suspended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The user is already suspended")
    if await is_active_admin(db, user.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Remove the admin access first")
    user.suspended_at = datetime.now(UTC)
    user.suspended_reason = body.reason
    open_ids = [
        str(i)
        for i in await db.scalars(
            select(InterviewSession.id).where(
                InterviewSession.org_id == user.org_id, InterviewSession.status.in_(OPEN)
            )
        )
    ]
    audit_action(
        db,
        admin,
        "user.suspended",
        f"user:{user.id}",
        org_id=user.org_id,
        reason=body.reason,
        before={"suspended_at": None},
        after={"suspended_at": user.suspended_at.isoformat()},
        details={"open_sessions": open_ids},
    )
    await db.commit()
    ended = await _end_open_sessions(request, db, user)
    return AdminActionOut(
        action="user.suspended", user_id=user.id, details={"sessions_ended": ended}
    )


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(
    user_id: uuid.UUID, body: ActionIn, db: DbSession, admin: AdminWrite
) -> AdminActionOut:
    user = await _get_user(db, user_id)
    if user.suspended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The user is not suspended")
    before = {"suspended_at": user.suspended_at.isoformat(), "reason": user.suspended_reason}
    user.suspended_at = None
    user.suspended_reason = None
    audit_action(
        db,
        admin,
        "user.unsuspended",
        f"user:{user.id}",
        org_id=user.org_id,
        reason=body.reason,
        before=before,
        after={"suspended_at": None},
    )
    await db.commit()
    return AdminActionOut(action="user.unsuspended", user_id=user.id)


# ---------------------------------------------------------------- AU-8 force sign-out


@router.post("/users/{user_id}/signout")
async def force_sign_out(
    user_id: uuid.UUID, body: ActionIn, db: DbSession, admin: AdminWrite
) -> AdminActionOut:
    """AU-8: every session cookie of the user stops working; they sign in again."""
    user = await _get_user(db, user_id)
    before = user.session_epoch or 0
    user.session_epoch = before + 1
    audit_action(
        db,
        admin,
        "user.signed_out",
        f"user:{user.id}",
        org_id=user.org_id,
        reason=body.reason,
        before={"session_epoch": before},
        after={"session_epoch": user.session_epoch},
    )
    await db.commit()
    return AdminActionOut(
        action="user.signed_out", user_id=user.id, details={"session_epoch": user.session_epoch}
    )


# ---------------------------------------------------------------- AU-9 resend sign-in link


@router.post("/users/{user_id}/resend-link", status_code=status.HTTP_202_ACCEPTED)
async def resend_sign_in_link(
    user_id: uuid.UUID, body: ActionIn, request: Request, db: DbSession, admin: AdminWrite
) -> AdminActionOut:
    """AU-9: email the user a sign-in link. At most RESEND_LIMIT per user per 15 minutes.

    The link goes to the user's inbox only; the admin never sees it (no impersonation)."""
    user = await _get_user(db, user_id)
    since = datetime.now(UTC) - RESEND_WINDOW
    recent = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == RESEND_ACTION,
            AuditLog.entity == f"user:{user.id}",
            AuditLog.at >= since,
        )
    )
    if int(recent or 0) >= RESEND_LIMIT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"{RESEND_LIMIT} links were sent in the last 15 minutes. Wait, then try again.",
        )
    links: MagicLinks = request.app.state.magic_links
    auth = admin_settings(request)
    token = links.issue(user.email)
    link = f"{auth.api_public_url.rstrip('/')}/auth/magic-link/callback?token={quote(token)}"
    await request.app.state.email_sender.send_magic_link(user.email, link)
    audit_action(
        db,
        admin,
        RESEND_ACTION,
        f"user:{user.id}",
        org_id=user.org_id,
        reason=body.reason,
    )
    await db.commit()
    return AdminActionOut(action=RESEND_ACTION, user_id=user.id)
