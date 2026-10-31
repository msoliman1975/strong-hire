"""Coach sessions, text (CO-2 to CO-5).

    POST /coach/sessions                    start one, for a new story or an existing one, with an
                                            optional target skill and plan page (job target)
    GET  /coach/sessions/{id}               the session, its story and its turns
    POST /coach/sessions/{id}/turns         a candidate turn and the coach's reply
    POST /coach/sessions/{id}/style         switch gentle or direct (CO-5)
    POST /coach/sessions/{id}/end           end it and record its minutes
    POST /coach/sessions/{id}/voice/join    CO-6: a LiveKit token for the room coach-<id>
    GET  /stories/{id}/coach-sessions       a story's coach sessions, newest first
    POST /internal/coach/sessions/{id}/turns   the voice agent's turn (CO-6, shared token)
    POST /internal/coach/sessions/{id}/end     the voice agent ends a session (shared token)

A new story is created when the session starts (source `coach`, Draft), so the target skill has a
place to live; it is deleted again when the session ends with no part filled. The coach writes
story parts only through the turn logic in `strong_api.coach.engine` (CO-3).

Starting a session answers 503 while new sessions on its channel are paused or the daily spend
cap is reached (OC-2, OC-3). The voice join (CO-6) moves a text session to voice, since the coach
page starts in text and the mic switches to talking; that move is a new voice start and checks the
voice controls. A rejoin of a session already on voice always may (as IV-9 for interviews).

Coach sessions record minutes on the coach session row and usage events with role `coach`, like
any session; they do not use plan minutes (billing rules for coach time are undecided).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from livekit import api as livekit_api
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.coach import engine
from strong_api.coach.schemas import (
    AskFor,
    CoachSessionDetail,
    CoachSessionOut,
    CoachTurnOut,
    CoachTurnRequest,
    CoachTurnResult,
    StartCoachRequest,
    StyleRequest,
)
from strong_api.controls import ensure_sessions_open
from strong_api.inputs.deps import Db, Me
from strong_api.sessions.schemas import VoiceJoin
from strong_api.sessions.settings import (
    TextSessionSettings,
    VoiceSessionSettings,
    get_text_session_settings,
    get_voice_session_settings,
)
from strong_core.db.models import CoachSession, CoachTurn, JobTarget
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Role, get_gateway
from strong_core.schemas import (
    CoachSessionStatus,
    CoachSpeaker,
    Competency,
    Resume,
    SessionChannel,
    Story,
    StoryNote,
    StorySource,
    StoryStatus,
)
from strong_core.sim import gateway_for_org

log = logging.getLogger(__name__)

NEW_STORY_TITLE = "Untitled story"
IDEA_TITLE_MAX_CHARS = 60


def title_from_idea(line: str) -> str:
    """ST-12: a story started from a resume idea is first named after the achievement, in the
    user's own words, cut at a word to about 60 characters. The user can rename it any time."""
    text = " ".join(line.split()).rstrip(" .;")
    if len(text) <= IDEA_TITLE_MAX_CHARS:
        return text or NEW_STORY_TITLE
    cut = text[: IDEA_TITLE_MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"


COACH_ROOM_PREFIX = "coach-"  # the voice agent runs the coach in rooms named like this
TextSettings = Annotated[TextSessionSettings, Depends(get_text_session_settings)]
VoiceSettings = Annotated[VoiceSessionSettings, Depends(get_voice_session_settings)]

router = APIRouter(tags=["coach"])


def story_out(row: StoryRow) -> Story:
    return Story(
        id=row.id,
        title=row.title,
        context=row.context,
        stakes=row.stakes,
        action=row.action,
        result=row.result,
        reflection=row.reflection,
        skills=[Competency(s) for s in row.skills],
        status=row.status,
        source=row.source,
        source_session_id=row.source_session_id,
        source_question_ref=row.source_question_ref,
        notes=[StoryNote.model_validate(n) for n in row.notes_json],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def session_out(row: CoachSession) -> CoachSessionOut:
    return CoachSessionOut(
        id=row.id,
        story_id=row.story_id,
        style=row.style,
        channel=row.channel,
        status=row.status,
        minutes=row.minutes,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


def turn_out(row: CoachTurn) -> CoachTurnOut:
    return CoachTurnOut(seq=row.seq, speaker=row.speaker, text=row.text, at_ms=row.start_ms)


async def _turns(db: AsyncSession, session: CoachSession) -> list[CoachTurn]:
    rows = await db.scalars(
        select(CoachTurn)
        .where(CoachTurn.coach_session_id == session.id, CoachTurn.org_id == session.org_id)
        .order_by(CoachTurn.seq)
    )
    return list(rows)


async def _story(db: AsyncSession, session: CoachSession) -> StoryRow | None:
    if session.story_id is None:
        return None
    return await db.scalar(
        select(StoryRow).where(StoryRow.id == session.story_id, StoryRow.org_id == session.org_id)
    )


async def _detail(db: AsyncSession, session: CoachSession) -> CoachSessionDetail:
    story = await _story(db, session)
    turns = await _turns(db, session)
    return CoachSessionDetail(
        session=session_out(session),
        story=story_out(story) if story is not None else None,
        turns=[turn_out(t) for t in turns],
        missing=engine.missing_parts(story) if story is not None else list(engine.PARTS),
        asking_for=engine.asks(story)[0] if story is not None else AskFor.NOTHING,
    )


async def _owned(
    db: AsyncSession, me: Me, session_id: uuid.UUID, *, lock: bool = False
) -> CoachSession:
    query = select(CoachSession).where(
        CoachSession.id == session_id,
        CoachSession.org_id == me.org_id,
        CoachSession.user_id == me.user_id,
    )
    if lock:
        query = query.with_for_update()  # one turn at a time per session (SQLite ignores it)
    session = await db.scalar(query)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Coach session not found")
    return session


async def _owned_story(db: AsyncSession, me: Me, story_id: uuid.UUID) -> StoryRow:
    story = await db.scalar(
        select(StoryRow).where(
            StoryRow.id == story_id, StoryRow.org_id == me.org_id, StoryRow.user_id == me.user_id
        )
    )
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return story


def _add_refs(session: CoachSession, refs: set[str]) -> None:
    current = set(filter(None, (session.prompt_version or "").split(",")))
    session.prompt_version = ",".join(sorted(current | refs))[:200] or None


async def _idea(db: AsyncSession, me: Me, resume_id: uuid.UUID, ref: str) -> str:
    """ST-12: the resume achievement a story idea (RM-4) starts from."""
    row = await db.scalar(
        select(ResumeRow).where(
            ResumeRow.id == resume_id,
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
        )
    )
    if row is None or row.parsed_json is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    found = re.match(r"^roles\[(\d+)\]\.achievements\[(\d+)\]$", ref)
    resume = Resume.model_validate(row.parsed_json)
    if found is not None:
        i, j = int(found[1]), int(found[2])
        if i < len(resume.roles) and j < len(resume.roles[i].achievements):
            line = resume.roles[i].achievements[j].strip()
            if line:
                return line
    raise HTTPException(status.HTTP_404_NOT_FOUND, "No achievement at that place")


@router.post(
    "/coach/sessions", status_code=status.HTTP_201_CREATED, response_model=CoachSessionDetail
)
async def start_coach_session(body: StartCoachRequest, db: Db, me: Me) -> CoachSessionDetail:
    """CO-2: start a coach session. The coach greets and asks for the first missing thing."""
    await ensure_sessions_open(db, body.channel)  # OC-2, OC-3
    if body.job_target_id is not None:
        target = await db.scalar(
            select(JobTarget.id).where(
                JobTarget.id == body.job_target_id,
                JobTarget.org_id == me.org_id,
                JobTarget.user_id == me.user_id,
            )
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    is_new = body.story_id is None
    idea = None
    if (body.resume_id is None) != (body.resume_line_ref is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "resume_id and resume_line_ref go together"
        )
    if body.resume_id is not None and body.resume_line_ref is not None and is_new:
        idea = await _idea(db, me, body.resume_id, body.resume_line_ref)
    if body.story_id is not None:
        story = await _owned_story(db, me, body.story_id)
    else:
        story = StoryRow(
            id=uuid.uuid4(),
            org_id=me.org_id,
            user_id=me.user_id,
            # The user names it when ready; an idea gives it a first name from the achievement.
            title=title_from_idea(idea) if idea else NEW_STORY_TITLE,
            # ST-12: the achievement (the user's own words) seeds the context.
            context=idea,
            skills=[],
            notes_json=[],
            status=StoryStatus.DRAFT,
            source=StorySource.COACH,
        )
        db.add(story)
    if body.target_skill is not None:
        story.skills = engine.merge_skills(story.skills or [], [body.target_skill])
    gateway = await gateway_for_org(db, me.org_id, get_gateway())
    session = CoachSession(
        id=uuid.uuid4(),
        org_id=me.org_id,
        user_id=me.user_id,
        story_id=story.id,
        style=body.style,
        channel=body.channel,
        status=CoachSessionStatus.ACTIVE,
        minutes=0,
        model_profile=gateway.profile,
        model_id=gateway.config.alias_for(Role.COACH),
        started_at=datetime.now(UTC),
    )
    db.add(session)
    await db.flush()
    line = engine.opener(story, is_new=is_new, target_skill=body.target_skill, idea=idea)
    engine.add_turn(db, session, [], CoachSpeaker.COACH, line)
    await db.commit()
    await db.refresh(story)
    return await _detail(db, session)


@router.get("/coach/sessions/{session_id}", response_model=CoachSessionDetail)
async def get_coach_session(session_id: uuid.UUID, db: Db, me: Me) -> CoachSessionDetail:
    return await _detail(db, await _owned(db, me, session_id))


async def _turn(
    db: AsyncSession, session: CoachSession, text: str, timeout_s: float
) -> CoachTurnResult:
    if session.status != CoachSessionStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "The coach session has ended.")
    story = await _story(db, session)
    if story is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The story was deleted; end the session.")
    turns = await _turns(db, session)
    gateway = await gateway_for_org(db, session.org_id, get_gateway())
    refs: set[str] = set()
    try:
        async with asyncio.timeout(timeout_s):
            result = await engine.run_turn(db, gateway, session, story, turns, text, refs)
    except TimeoutError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "The coach took too long to answer. Send your message again.",
        ) from None
    _add_refs(session, refs)
    session.minutes = engine.session_minutes(turns)
    if result.ended:
        await _close(db, session, story)
    await db.commit()
    kept = session.story_id is not None  # an empty new story is dropped when the session ends
    if kept:
        await db.refresh(story)
    return CoachTurnResult(
        reply=result.reply,
        story=story_out(story) if kept else None,
        turns=[turn_out(t) for t in result.turns],
        asking_for=result.ask,
        conduct=result.conduct,
        ended=result.ended,
    )


@router.post("/coach/sessions/{session_id}/turns", response_model=CoachTurnResult)
async def coach_turn(
    session_id: uuid.UUID, body: CoachTurnRequest, db: Db, me: Me, settings: TextSettings
) -> CoachTurnResult:
    """CO-2, CO-3, CO-4: the candidate's turn; the story's parts update from their words."""
    session = await _owned(db, me, session_id, lock=True)
    return await _turn(db, session, body.text, settings.text_turn_timeout_s)


@router.post("/coach/sessions/{session_id}/style", response_model=CoachSessionOut)
async def set_coach_style(
    session_id: uuid.UUID, body: StyleRequest, db: Db, me: Me
) -> CoachSessionOut:
    """CO-5: gentle or direct. Only the style section of the prompt changes."""
    session = await _owned(db, me, session_id)
    if session.status != CoachSessionStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "The coach session has ended.")
    session.style = body.style
    await db.commit()
    return session_out(session)


async def _close(db: AsyncSession, session: CoachSession, story: StoryRow | None) -> None:
    """End the session: minutes up to the last turn; drop a new story that stayed empty."""
    session.status = CoachSessionStatus.ENDED
    session.ended_at = session.ended_at or datetime.now(UTC)
    session.minutes = engine.session_minutes(await _turns(db, session))
    if story is None or engine.missing_parts(story) != list(engine.PARTS):
        return
    if story.source != StorySource.COACH:
        return
    others = await db.scalar(
        select(func.count())
        .select_from(CoachSession)
        .where(CoachSession.story_id == story.id, CoachSession.id != session.id)
    )
    if not others:
        session.story_id = None
        await db.delete(story)


async def _end(db: AsyncSession, session: CoachSession) -> CoachSessionDetail:
    if session.status == CoachSessionStatus.ACTIVE:
        await _close(db, session, await _story(db, session))
        await db.commit()
    return await _detail(db, session)


@router.post("/coach/sessions/{session_id}/end", response_model=CoachSessionDetail)
async def end_coach_session(session_id: uuid.UUID, db: Db, me: Me) -> CoachSessionDetail:
    """End the session and record its minutes. Ending twice is harmless."""
    return await _end(db, await _owned(db, me, session_id, lock=True))


@router.post("/coach/sessions/{session_id}/voice/join")
async def join_coach_voice(
    session_id: uuid.UUID, db: Db, me: Me, settings: VoiceSettings
) -> VoiceJoin:
    """CO-6: a LiveKit token for the coach's voice room. Call it again after a dropped
    connection: the room stays the same and the coach goes on from the last turn."""
    session = await _owned(db, me, session_id, lock=True)
    if session.status != CoachSessionStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "The coach session has ended.")
    if session.channel != SessionChannel.VOICE:
        await ensure_sessions_open(db, SessionChannel.VOICE)  # OC-2, OC-3: a new voice start
        session.channel = SessionChannel.VOICE
        await db.commit()
    room = f"{COACH_ROOM_PREFIX}{session.id}"
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


@router.get("/stories/{story_id}/coach-sessions", response_model=list[CoachSessionOut])
async def list_story_coach_sessions(story_id: uuid.UUID, db: Db, me: Me) -> list[CoachSessionOut]:
    story = await _owned_story(db, me, story_id)
    rows = await db.scalars(
        select(CoachSession)
        .where(CoachSession.story_id == story.id, CoachSession.org_id == me.org_id)
        .order_by(CoachSession.created_at.desc(), CoachSession.id.desc())
    )
    return [session_out(r) for r in rows]


# --- the voice agent (CO-6, S32) -------------------------------------------------------------


def _check_token(token: str | None, settings: VoiceSessionSettings) -> None:
    expected = settings.strong_internal_token.get_secret_value()
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")


async def _internal_session(db: AsyncSession, session_id: uuid.UUID) -> CoachSession:
    session = await db.scalar(
        select(CoachSession).where(CoachSession.id == session_id).with_for_update()
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Coach session not found")
    return session


@router.post(
    "/internal/coach/sessions/{session_id}/turns",
    response_model=CoachTurnResult,
    include_in_schema=False,
)
async def internal_coach_turn(
    session_id: uuid.UUID,
    body: CoachTurnRequest,
    db: Db,
    settings: VoiceSettings,
    text_settings: TextSettings,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> CoachTurnResult:
    """The voice agent sends a transcribed candidate turn. Not for browsers."""
    _check_token(x_internal_token, settings)
    session = await _internal_session(db, session_id)
    return await _turn(db, session, body.text, text_settings.text_turn_timeout_s)


@router.post(
    "/internal/coach/sessions/{session_id}/end",
    response_model=CoachSessionDetail,
    include_in_schema=False,
)
async def internal_end_coach_session(
    session_id: uuid.UUID,
    db: Db,
    settings: VoiceSettings,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> CoachSessionDetail:
    _check_token(x_internal_token, settings)
    return await _end(db, await _internal_session(db, session_id))
