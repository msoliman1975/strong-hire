"""Interview sessions (P7).

    POST /sessions                         create a session (402 when the plan does not allow it;
                                           free accounts may start 10-minute minis only)
    GET  /sessions/{id}                    one session
    GET  /job-targets/{id}/sessions        a job's sessions, newest first
    POST /sessions/{id}/end                end it: bill minutes, start scoring
    POST /sessions/{id}/text/open          text channel: the interviewer greets (PL-7)
    POST /sessions/{id}/text/turn          text channel: a candidate turn and the reply
    POST /sessions/{id}/coach              pause, resume, hint, redo (Coach mode only, IV-8)
    POST /sessions/{id}/voice/join         voice channel: start, and a LiveKit token for the room
    POST /internal/sessions/{id}/end       the voice agent ends a session (shared token)

Creating a session queues the interviewer brief job (P6). The text channel runs the same
controller and interviewer as the voice agent (strong_interview), with typed input. It exists
only when APP_ENV is local or test, and its runners live in this API process: if the API
restarts, an open text session must be ended.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from livekit import api as livekit_api
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.auth.settings import AppEnv, get_auth_settings
from strong_api.auth.sim import is_sim_user
from strong_api.billing.entitlements import ensure_can_start_session, record_session_minutes
from strong_api.inputs.deps import CurrentUser, Db, Me, Queue
from strong_api.inputs.queue import BUILD_INTERVIEWER_BRIEF, JobQueue
from strong_api.scoring.router import _brief, _config, _owned_session, _owned_target, start_scoring
from strong_api.sessions.schemas import (
    CoachRequest,
    CreateSessionRequest,
    InternalEndRequest,
    SessionRecord,
    TextTurnRequest,
    TextTurns,
    VoiceJoin,
)
from strong_api.sessions.settings import VoiceSessionSettings, get_voice_session_settings
from strong_core.db.models import InterviewSession, JobTarget, UsageEvent
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import next_turn_seq
from strong_core.gateway import Role, get_gateway
from strong_core.schemas import JobPosting, SessionChannel, SessionStatus, Turn, UsageComponent
from strong_core.sim import gateway_for_org
from strong_interview import (
    CoachNotAllowedError,
    Interviewer,
    InterviewRunner,
    SessionController,
    SessionFacts,
)
from strong_interview.trace_store import SqlTraceSink

log = logging.getLogger(__name__)

OPEN = {SessionStatus.CREATED, SessionStatus.IN_PROGRESS, SessionStatus.INTERRUPTED}
SESSION_ROOM_PREFIX = "session-"  # the voice agent runs the interview in rooms named like this
VoiceSettings = Annotated[VoiceSessionSettings, Depends(get_voice_session_settings)]

router = APIRouter(tags=["sessions"])


def _record(session: InterviewSession, target: JobTarget | None) -> SessionRecord:
    return SessionRecord(
        id=session.id,
        job_target_id=session.job_target_id,
        config=_config(session, target),
        channel=session.channel,
        status=session.status,
        brief_ready=_brief(session) is not None,
        started_at=session.started_at,
        ended_at=session.ended_at,
        minutes_billed=session.minutes_billed or 0,
    )


async def _text_allowed(db: AsyncSession, me: CurrentUser) -> bool:
    """Text sessions are a dev feature (PL-7), and the AI candidate's way in (P13)."""
    if get_auth_settings().app_env in (AppEnv.LOCAL, AppEnv.TEST):
        return True
    return await is_sim_user(db, me.user_id)


def _runners(request: Request) -> dict[uuid.UUID, InterviewRunner]:
    runners: dict[uuid.UUID, InterviewRunner] | None = getattr(
        request.app.state, "text_runners", None
    )
    if runners is None:
        runners = {}
        request.app.state.text_runners = runners
    return runners


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(body: CreateSessionRequest, db: Db, me: Me, queue: Queue) -> SessionRecord:
    """Create a session and queue its interviewer brief (IV-2, IV-4, IV-6, IV-8)."""
    target = await _owned_target(db, me, body.job_target_id)
    if target.deleted_at is not None:  # R1: a deleted job cannot get new sessions
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job target not found")
    if target.parsed_json is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The job posting is still being read.")
    if body.channel == SessionChannel.TEXT and not await _text_allowed(db, me):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Text sessions are a dev feature.")
    config = body.config
    if not await is_sim_user(db, me.user_id):  # the AI candidate has no plan (P13)
        await ensure_can_start_session(db, me.org_id, config.duration_min)
    target.level = config.level  # the level confirmed at setup sets the bar (IV-6)
    session = InterviewSession(
        org_id=me.org_id,
        job_target_id=target.id,
        type=config.interview_type,
        difficulty=config.difficulty,
        mode=config.mode,
        duration_min=config.duration_min,
        channel=body.channel,
        model_profile=get_gateway().profile,
    )
    db.add(session)
    await db.commit()
    await queue.enqueue(
        BUILD_INTERVIEWER_BRIEF,
        f"brief:{session.id}:{uuid.uuid4().hex[:8]}",
        session_id=str(session.id),
        org_id=str(session.org_id),
    )
    await db.refresh(session)
    return _record(session, target)


@router.get("/sessions/{session_id}")
async def get_session(session_id: uuid.UUID, db: Db, me: Me) -> SessionRecord:
    session = await _owned_session(db, me, session_id)
    return _record(session, await db.get(JobTarget, session.job_target_id))


@router.get("/job-targets/{job_target_id}/sessions")
async def list_sessions(job_target_id: uuid.UUID, db: Db, me: Me) -> list[SessionRecord]:
    target = await _owned_target(db, me, job_target_id)
    rows = await db.scalars(
        select(InterviewSession)
        .where(InterviewSession.job_target_id == target.id, InterviewSession.org_id == me.org_id)
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
    )
    return [_record(s, target) for s in rows]


async def _end(
    db: AsyncSession, queue: JobQueue, session: InterviewSession, runner: InterviewRunner | None
) -> None:
    if session.status not in OPEN:
        return
    if runner is not None:
        session.prompt_version = ",".join(sorted(runner.interviewer.prompt_refs))[:200] or None
        await _flush_traces(runner)
        interviewer = runner.interviewer
        if session.started_at is not None:
            # The text channel's interviewer tokens and cost, like the voice agent saves them.
            db.add(
                UsageEvent(
                    org_id=session.org_id,
                    session_id=session.id,
                    component=UsageComponent.LLM,
                    units=Decimal(interviewer.input_tokens + interviewer.output_tokens),
                    cost_usd=Decimal(f"{interviewer.cost_usd:.6f}"),
                )
            )
    if session.started_at is None:
        # Never started: no minutes, no scoring, and the free interview is not used.
        session.ended_at = datetime.now(UTC)
        session.status = SessionStatus.FAILED
        await db.commit()
        return
    session.ended_at = datetime.now(UTC)
    await record_session_minutes(db, session)
    await start_scoring(db, queue, session)  # commits; sets status scoring


async def _flush_traces(runner: InterviewRunner) -> None:
    """Wait for trace rows still being written (R2). Never raises."""
    if isinstance(runner.trace, SqlTraceSink):
        try:
            await runner.trace.flush()
        except Exception:
            log.warning("could not flush the interviewer traces", exc_info=True)


@router.post("/sessions/{session_id}/end")
async def end_session(
    session_id: uuid.UUID, request: Request, db: Db, me: Me, queue: Queue
) -> SessionRecord:
    """End the session. Started sessions are billed and scored (FB-3); safe to call twice."""
    session = await _owned_session(db, me, session_id)
    runner = _runners(request).pop(session.id, None)
    await _end(db, queue, session, runner)
    await db.refresh(session)
    return _record(session, await db.get(JobTarget, session.job_target_id))


# ---------------------------------------------------------------- text channel (PL-7)


async def _text_session(db: Db, me: Me, session_id: uuid.UUID) -> InterviewSession:
    if not await _text_allowed(db, me):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    session = await _owned_session(db, me, session_id)
    if session.channel != SessionChannel.TEXT:
        raise HTTPException(status.HTTP_409_CONFLICT, "This is not a text session.")
    if session.status not in OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "The session has ended.")
    return session


def _turn_saver(request: Request, session: InterviewSession, lock: asyncio.Lock):  # type: ignore[no-untyped-def]
    """Saves each turn. `lock` is the trace sink's lock: a turn save and a trace insert of the
    same session take turns, so one never ends the other's open transaction (tests share one
    SQLite connection)."""
    maker = request.app.state.sessionmaker

    async def save(turn: Turn) -> None:
        async with lock, maker() as db:
            db.add(
                TurnRow(
                    org_id=session.org_id,
                    session_id=session.id,
                    speaker=turn.speaker,
                    phase=turn.phase,
                    text=turn.text,
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                    question_ref=turn.question_ref,
                    seq=await next_turn_seq(db, session.id),
                )
            )
            await db.commit()

    return save


def _facts(target: JobTarget | None, company: str | None) -> SessionFacts:
    if target is None or target.parsed_json is None:
        return SessionFacts(company_name=company)
    posting = JobPosting.model_validate(target.parsed_json)
    return SessionFacts(
        company_name=company or posting.company_name,
        job_title=posting.title,
        team=posting.team,
        notes=tuple(posting.responsibilities[:5]),
    )


@router.post("/sessions/{session_id}/text/open")
async def open_text_session(session_id: uuid.UUID, request: Request, db: Db, me: Me) -> TextTurns:
    """Start the text session: the interviewer greets the candidate."""
    session = await _text_session(db, me, session_id)
    runners = _runners(request)
    if session.id in runners:
        raise HTTPException(status.HTTP_409_CONFLICT, "The session is already open.")
    if session.started_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The text session was lost; end it.")
    brief = _brief(session)
    if brief is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The interview plan is not ready yet.")
    gateway = await gateway_for_org(db, session.org_id, get_gateway())  # sim budget (P13)
    target = await db.get(JobTarget, session.job_target_id)
    interviewer = Interviewer(gateway, brief, facts=_facts(target, brief.company_name))
    sink = SqlTraceSink(request.app.state.sessionmaker, session.org_id, session.id)
    runner = InterviewRunner(
        SessionController(brief),
        interviewer,
        on_turn=_turn_saver(request, session, sink.lock),
        trace=sink,
    )
    session.status = SessionStatus.IN_PROGRESS
    session.started_at = datetime.now(UTC)
    session.model_profile = gateway.profile
    session.interviewer_model_id = gateway.config.alias_for(Role.INTERVIEWER)
    await db.commit()
    runners[session.id] = runner
    turns = await runner.open()
    await _flush_traces(runner)  # the text channel answers after its traces are saved
    return TextTurns(turns=turns, ended=runner.ended, phase=runner.controller.phase.value)


def _runner(request: Request, session: InterviewSession) -> InterviewRunner:
    runner = _runners(request).get(session.id)
    if runner is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The text session is not open.")
    return runner


@router.post("/sessions/{session_id}/text/turn")
async def text_turn(
    session_id: uuid.UUID, body: TextTurnRequest, request: Request, db: Db, me: Me, queue: Queue
) -> TextTurns:
    """The candidate's turn. Returns the interviewer's reply; the session ends on its own."""
    session = await _text_session(db, me, session_id)
    runner = _runner(request, session)
    turns = await runner.respond(body.text)
    await _flush_traces(runner)  # the text channel answers after its traces are saved
    if runner.ended:
        _runners(request).pop(session.id, None)
        await _end(db, queue, session, runner)
    return TextTurns(turns=turns, ended=runner.ended, phase=runner.controller.phase.value)


@router.post("/sessions/{session_id}/coach")
async def coach(
    session_id: uuid.UUID, body: CoachRequest, request: Request, db: Db, me: Me
) -> TextTurns:
    """Coach mode only (IV-8): pause and resume the clock, ask for a hint, redo the answer."""
    session = await _text_session(db, me, session_id)
    runner = _runner(request, session)
    turns: list[Turn] = []
    try:
        if body.command == "pause":
            runner.pause()
        elif body.command == "resume":
            runner.resume()
        else:
            turns = await runner.coach(body.command)
            await _flush_traces(runner)  # the text channel answers after its traces are saved
    except CoachNotAllowedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return TextTurns(turns=turns, ended=runner.ended, phase=runner.controller.phase.value)


# ---------------------------------------------------------------- voice channel (IV-1, IV-9)


@router.post("/sessions/{session_id}/voice/join")
async def join_voice_session(
    session_id: uuid.UUID, db: Db, me: Me, settings: VoiceSettings
) -> VoiceJoin:
    """Start the voice session (first join) and return a LiveKit token for its room.

    Call it again after a dropped connection: the room stays the same, so the voice agent goes
    on at the same phase and question when the candidate is back within 2 minutes (IV-9).
    """
    session = await _owned_session(db, me, session_id)
    if session.channel != SessionChannel.VOICE:
        raise HTTPException(status.HTTP_409_CONFLICT, "This is not a voice session.")
    if session.status not in OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "The session has ended.")
    if _brief(session) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The interview plan is not ready yet.")
    if session.started_at is None:
        gateway = get_gateway()
        session.status = SessionStatus.IN_PROGRESS
        session.started_at = datetime.now(UTC)
        session.model_profile = gateway.profile
        session.interviewer_model_id = gateway.config.alias_for(Role.INTERVIEWER)
        await db.commit()
    room = f"{SESSION_ROOM_PREFIX}{session.id}"
    identity = f"candidate-{me.user_id}"
    grants = livekit_api.VideoGrants(
        room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True
    )
    token = (
        livekit_api.AccessToken(
            settings.livekit_api_key, settings.livekit_api_secret.get_secret_value()
        )
        .with_identity(identity)
        .with_name("Candidate")
        .with_grants(grants)
        .with_ttl(timedelta(minutes=settings.token_ttl_minutes))
        .to_jwt()
    )
    return VoiceJoin(
        livekit_url=settings.livekit_public_url, room=room, token=token, identity=identity
    )


@router.post("/internal/sessions/{session_id}/end", include_in_schema=False)
async def internal_end_session(
    session_id: uuid.UUID,
    body: InternalEndRequest,
    db: Db,
    queue: Queue,
    settings: VoiceSettings,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """The voice agent ends a session: bill the minutes and start scoring. Not for browsers."""
    expected = settings.strong_internal_token.get_secret_value()
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    session = await db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    await _end(db, queue, session, None)
    await db.refresh(session)
    return {"status": session.status.value, "interrupted": str(body.interrupted).lower()}
