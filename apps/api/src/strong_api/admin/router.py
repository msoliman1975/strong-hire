"""Admin area (R2): review test interviews and the interviewer's reasoning.

    GET /admin/users                 every user: plan, minutes, consent, interviews, last sign-in
    GET /admin/sessions              interviews of all users (filters: user, date, type), with
                                     model cost and a cost total per day
    GET /admin/sessions/{id}         one interview: metadata always; transcript and traces only
                                     when the user's training consent is on now
    GET /admin/sessions/{id}/transcript.txt   the transcript as a text file (same consent rule)
    GET /admin/sessions/{id}/audio   the recording of an AI candidate (P13) voice interview, from
                                     the saved sim runs (same consent rule)
    GET /admin/audit                 the audit log (admin views by default)

Only ADMIN_EMAILS users may call these routes. Everyone else, signed in or not, gets 404.
Consent is read at view time, so turning it off hides old transcripts and traces too. Each view
or download of a transcript, traces or audio writes an audit_logs row.

Cost: per-session cost is the interviewer's model cost. Sessions save it as an LLM usage event
when they end (tokens times the prices in config/litellm.<profile>.yaml); for a session without
one, the sum of its trace costs is used. Scorer, speech-to-text and text-to-speech cost is not
counted here.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin.schemas import (
    AdminAuditEntry,
    AdminMessage,
    AdminScore,
    AdminSession,
    AdminSessionDetail,
    AdminSessionList,
    AdminTrace,
    AdminUser,
    CostSource,
    DailyCost,
)
from strong_api.auth.deps import DbSession, optional_user
from strong_api.auth.settings import AuthSettings
from strong_api.auth.sim import is_sim_user
from strong_api.billing.entitlements import as_utc, get_entitlement
from strong_core.db.models import (
    TRACE_RETENTION_DAYS,
    AuditLog,
    InterviewerTrace,
    InterviewSession,
    Scorecard,
    UsageEvent,
    User,
)
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import TURN_ORDER
from strong_core.schemas import InterviewType, Turn, UsageComponent

SESSION_LIMIT = 500
AUDIT_LIMIT = 500


def admin_settings(request: Request) -> AuthSettings:
    settings: AuthSettings = request.app.state.admin_auth_settings
    return settings


async def require_admin(
    user: Annotated[User | None, Depends(optional_user)],
    settings: Annotated[AuthSettings, Depends(admin_settings)],
) -> User:
    """The signed-in admin. 404 for everyone else, so the area does not show it exists."""
    if user is None or not settings.is_admin(user.email):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return user


Admin = Annotated[User, Depends(require_admin)]

router = APIRouter(prefix="/admin", tags=["admin"])


def _pairs(result: Any) -> dict[Any, Any]:
    """Two-column rows as a dict. (dict(result) would treat the Result as a mapping.)"""
    return {key: value for key, value in result.tuples()}


def _float(value: Decimal | float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _scores(card: Scorecard | None) -> list[AdminScore]:
    if card is None:
        return []
    out = []
    for item in card.competency_scores_json or []:
        if isinstance(item, dict) and "competency" in item and "score" in item:
            out.append(AdminScore(competency=item["competency"], score=int(item["score"])))
    return out


def _duration_s(row: InterviewSession) -> int | None:
    start, end = as_utc(row.started_at), as_utc(row.ended_at)
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds()))


async def _costs(
    db: AsyncSession, session_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[float | None, CostSource]]:
    if not session_ids:
        return {}
    usage = _pairs(
        await db.execute(
            select(UsageEvent.session_id, func.sum(UsageEvent.cost_usd))
            .where(
                UsageEvent.session_id.in_(session_ids),
                UsageEvent.component == UsageComponent.LLM,
            )
            .group_by(UsageEvent.session_id)
        )
    )
    traced = _pairs(
        await db.execute(
            select(InterviewerTrace.session_id, func.sum(InterviewerTrace.cost_usd))
            .where(InterviewerTrace.session_id.in_(session_ids))
            .group_by(InterviewerTrace.session_id)
        )
    )
    out: dict[uuid.UUID, tuple[float | None, CostSource]] = {}
    for sid in session_ids:
        from_usage, from_traces = usage.get(sid), traced.get(sid)
        if from_usage is not None and Decimal(from_usage) > 0:
            out[sid] = (_float(from_usage), "usage_events")
        elif from_traces is not None:
            out[sid] = (_float(from_traces), "traces")
        else:
            out[sid] = (None, "none")
    return out


def _session_out(
    row: InterviewSession,
    user: User | None,
    card: Scorecard | None,
    cost: tuple[float | None, CostSource],
) -> AdminSession:
    return AdminSession(
        id=row.id,
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        training_consent=bool(user and user.training_consent),
        created_at=row.created_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        interview_type=row.type,
        difficulty=row.difficulty,
        mode=row.mode,
        duration_min=row.duration_min,
        duration_s=_duration_s(row),
        channel=row.channel,
        status=row.status,
        minutes_billed=row.minutes_billed or 0,
        hire_signal=card.hire_signal if card else None,
        scores=_scores(card),
        model_profile=row.model_profile,
        interviewer_model_id=row.interviewer_model_id,
        prompt_version=row.prompt_version,
        cost_usd=cost[0],
        cost_source=cost[1],
    )


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


@router.get("/users")
async def list_users(db: DbSession, admin: Admin, request: Request) -> list[AdminUser]:
    settings = admin_settings(request)
    users = list(await db.scalars(select(User).order_by(User.created_at.desc())))
    counts = _pairs(
        await db.execute(
            select(InterviewSession.org_id, func.count(InterviewSession.id)).group_by(
                InterviewSession.org_id
            )
        )
    )
    out = []
    for user in users:
        ent = await get_entitlement(db, user.org_id)
        out.append(
            AdminUser(
                id=user.id,
                email=user.email,
                created_at=user.created_at,
                last_sign_in_at=user.last_sign_in_at,
                plan=ent.plan,
                subscription_status=ent.status,
                minutes_used=ent.minutes_used,
                minutes_cap=ent.minutes_cap,
                training_consent=user.training_consent,
                interviews=int(counts.get(user.org_id, 0)),
                is_admin=settings.is_admin(user.email),
            )
        )
    return out


@router.get("/sessions")
async def list_sessions(
    db: DbSession,
    admin: Admin,
    user_id: uuid.UUID | None = None,
    day_from: Annotated[date | None, Query(description="First day (UTC), inclusive.")] = None,
    day_to: Annotated[date | None, Query(description="Last day (UTC), inclusive.")] = None,
    interview_type: InterviewType | None = None,
) -> AdminSessionList:
    """Interviews of all users, newest first, with the interviewer's model cost."""
    query = (
        select(InterviewSession, User, Scorecard)
        .outerjoin(User, User.org_id == InterviewSession.org_id)
        .outerjoin(Scorecard, Scorecard.session_id == InterviewSession.id)
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        .limit(SESSION_LIMIT)
    )
    if user_id is not None:
        query = query.where(User.id == user_id)
    if day_from is not None:
        query = query.where(InterviewSession.created_at >= _day_start(day_from))
    if day_to is not None:
        query = query.where(InterviewSession.created_at < _day_start(day_to + timedelta(days=1)))
    if interview_type is not None:
        query = query.where(InterviewSession.type == interview_type)
    rows = (await db.execute(query)).tuples().all()
    costs = await _costs(db, [r[0].id for r in rows])
    sessions = [_session_out(s, u, c, costs[s.id]) for s, u, c in rows]
    per_day: dict[date, list[AdminSession]] = defaultdict(list)
    for item in sessions:
        created = as_utc(item.created_at)
        assert created is not None
        per_day[created.date()].append(item)
    daily = [
        DailyCost(
            day=day,
            sessions=len(items),
            cost_usd=round(sum(i.cost_usd or 0.0 for i in items), 6),
        )
        for day, items in sorted(per_day.items(), reverse=True)
    ]
    return AdminSessionList(
        sessions=sessions,
        daily=daily,
        total_cost_usd=round(sum(d.cost_usd for d in daily), 6),
        limit=SESSION_LIMIT,
    )


def _trace_out(row: InterviewerTrace) -> AdminTrace:
    messages = None
    if isinstance(row.messages_json, list):
        messages = [
            AdminMessage(
                role=str(m.get("role", "")),
                content=str(m.get("content", "")),
                prompt_ref=m.get("prompt_ref"),
            )
            for m in row.messages_json
            if isinstance(m, dict)
        ]
    return AdminTrace(
        seq=row.seq,
        turn_index=row.turn_index,
        call=row.call,
        move=row.move,
        reason=row.reason_json,
        phase=row.phase,
        elapsed_ms=row.elapsed_ms,
        phase_deadline_ms=row.phase_deadline_ms,
        question_ref=row.question_ref,
        messages=messages,
        raw_reply=row.raw_reply,
        spoken_text=row.spoken_text,
        model=row.model,
        prompt_refs=row.prompt_refs,
        input_tokens=row.input_tokens or 0,
        output_tokens=row.output_tokens or 0,
        cost_usd=_float(row.cost_usd),
        latency_ms=row.latency_ms,
        error=row.error,
        created_at=row.created_at,
    )


def _audit(admin: User, action: str, row: InterviewSession, details: dict[str, Any]) -> AuditLog:
    return AuditLog(
        org_id=row.org_id,
        actor=admin.email,
        action=action,
        entity=f"session:{row.id}",
        details_json=details,
    )


async def _find(
    db: AsyncSession, session_id: uuid.UUID
) -> tuple[InterviewSession, User | None, Scorecard | None]:
    found = (
        await db.execute(
            select(InterviewSession, User, Scorecard)
            .outerjoin(User, User.org_id == InterviewSession.org_id)
            .outerjoin(Scorecard, Scorecard.session_id == InterviewSession.id)
            .where(InterviewSession.id == session_id)
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    row, user, card = found.tuple()
    return row, user, card


def _content_user(user: User | None) -> User:
    """The session's user when consent is on now; 404 otherwise, as for a missing file."""
    if user is None or not user.training_consent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No consent for this interview")
    return user


async def _transcript(db: AsyncSession, row: InterviewSession) -> list[Turn]:
    turn_rows = await db.scalars(
        select(TurnRow).where(TurnRow.session_id == row.id).order_by(*TURN_ORDER)
    )
    return [
        Turn(
            speaker=t.speaker,
            phase=t.phase,
            text=t.text,
            start_ms=t.start_ms,
            end_ms=t.end_ms,
            question_ref=t.question_ref,
        )
        for t in turn_rows
    ]


def _find_recording(results_dir: str, session_id: uuid.UUID) -> tuple[Path, int] | None:
    """The newest <run>/<session id>/audio.ogg under the results folder, with its size.

    The path is built from the session id only (a UUID), and it must resolve inside the folder.
    """
    root = Path(results_dir).resolve()
    if not root.is_dir():
        return None
    found = []
    for path in root.glob(f"*/{session_id}/audio.ogg"):
        resolved = path.resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            stat = resolved.stat()
            found.append((stat.st_mtime, resolved, stat.st_size))
    if not found:
        return None
    _, newest, size = max(found)
    return newest, size


async def _sim_audio(
    db: AsyncSession, user: User, row: InterviewSession, settings: AuthSettings
) -> tuple[Path, int] | None:
    """The saved recording of a sim voice interview and its size, or None.

    Only the sim user's sessions have recordings; real users' audio is never stored.
    """
    if not await is_sim_user(db, user.id):
        return None
    return await asyncio.to_thread(_find_recording, settings.sim_results_dir, row.id)


def _transcript_text(row: InterviewSession, user: User, transcript: list[Turn]) -> str:
    lines = [
        f"Interview {row.id}",
        f"User: {user.email}",
        f"Setup: {row.type}, {row.difficulty}, {row.mode}, {row.channel}, "
        f"{row.duration_min} minutes planned",
        f"Created: {as_utc(row.created_at)}",
        "",
    ]
    for turn in transcript:
        seconds = (turn.start_ms or 0) // 1000
        who = "Interviewer" if turn.speaker == "interviewer" else "Candidate"
        lines.append(f"[{seconds // 60:02d}:{seconds % 60:02d}] {who} [{turn.phase}]: {turn.text}")
        lines.append("")
    return "\n".join(lines)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID, db: DbSession, admin: Admin, request: Request
) -> AdminSessionDetail:
    """One interview. Transcript and traces only when the user's consent is on now."""
    row, user, card = await _find(db, session_id)
    cost = (await _costs(db, [row.id]))[row.id]
    meta = _session_out(row, user, card, cost)
    if user is None or not user.training_consent:
        return AdminSessionDetail(
            session=meta,
            content_visible=False,
            transcript=None,
            traces=None,
            trace_retention_days=TRACE_RETENTION_DAYS,
        )
    transcript = await _transcript(db, row)
    trace_rows = await db.scalars(
        select(InterviewerTrace)
        .where(InterviewerTrace.session_id == row.id)
        .order_by(InterviewerTrace.seq, InterviewerTrace.created_at)
    )
    traces = [_trace_out(t) for t in trace_rows]
    who = {"user_id": str(user.id)}
    db.add(_audit(admin, "admin.transcript_viewed", row, {**who, "turns": len(transcript)}))
    db.add(_audit(admin, "admin.traces_viewed", row, {**who, "traces": len(traces)}))
    await db.commit()
    audio = await _sim_audio(db, user, row, admin_settings(request))
    return AdminSessionDetail(
        session=meta,
        content_visible=True,
        transcript=transcript,
        traces=traces,
        trace_retention_days=TRACE_RETENTION_DAYS,
        audio_available=audio is not None,
    )


@router.get("/sessions/{session_id}/transcript.txt", response_class=PlainTextResponse)
async def download_transcript(
    session_id: uuid.UUID, db: DbSession, admin: Admin
) -> PlainTextResponse:
    """The transcript as a text file. 404 when the user's consent is off now."""
    row, found_user, _ = await _find(db, session_id)
    user = _content_user(found_user)
    transcript = await _transcript(db, row)
    details = {"user_id": str(user.id), "turns": len(transcript)}
    db.add(_audit(admin, "admin.transcript_downloaded", row, details))
    await db.commit()
    return PlainTextResponse(
        _transcript_text(row, user, transcript),
        headers={"Content-Disposition": f'attachment; filename="interview-{row.id}.txt"'},
    )


@router.get("/sessions/{session_id}/audio", response_class=FileResponse)
async def download_audio(
    session_id: uuid.UUID, db: DbSession, admin: Admin, request: Request
) -> FileResponse:
    """The recording of an AI candidate voice interview, as stereo Ogg Opus.

    The left channel is what the candidate heard, the right channel what it said. 404 for every
    other session.
    """
    row, found_user, _ = await _find(db, session_id)
    user = _content_user(found_user)
    audio = await _sim_audio(db, user, row, admin_settings(request))
    if audio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No recording for this interview")
    path, size = audio
    details = {"user_id": str(user.id), "bytes": size}
    db.add(_audit(admin, "admin.audio_downloaded", row, details))
    await db.commit()
    return FileResponse(path, media_type="audio/ogg", filename=f"interview-{row.id}.ogg")


@router.get("/audit")
async def list_audit(
    db: DbSession, admin: Admin, scope: Literal["admin", "all"] = "admin"
) -> list[AdminAuditEntry]:
    """Newest first. `admin` shows the admin views only; `all` shows every entry."""
    query = select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id).limit(AUDIT_LIMIT)
    if scope == "admin":
        query = query.where(AuditLog.action.like("admin.%"))
    return [
        AdminAuditEntry(
            id=r.id,
            at=r.at,
            actor=r.actor,
            action=r.action,
            entity=r.entity,
            org_id=r.org_id,
            details=r.details_json,
        )
        for r in await db.scalars(query)
    ]
