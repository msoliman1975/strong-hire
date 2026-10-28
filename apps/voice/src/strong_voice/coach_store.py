"""Database and API access for voice coach sessions (CO-6).

coach_session_id_from_room   a room named coach-<uuid> is a coach session
load_coach_session           the session's org and the coach's last line
ApiCoach                     the API's coach turn logic, through its internal endpoints (S30)

Turns are not written here: the API saves both turns of each exchange (text only).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import CoachSession, CoachTurn
from strong_core.schemas import CoachSessionStatus, CoachSpeaker, SessionChannel
from strong_voice.coach import CoachTurnError
from strong_voice.session_store import AgentApiSettings

COACH_ROOM_PREFIX = "coach-"
TURN_TIMEOUT_S = 60.0
TURN_MAX_CHARS = 4000  # the API's limit for one turn


def coach_session_id_from_room(room: str) -> uuid.UUID | None:
    if not room.startswith(COACH_ROOM_PREFIX):
        return None
    try:
        return uuid.UUID(room.removeprefix(COACH_ROOM_PREFIX))
    except ValueError:
        return None


@dataclass
class LoadedCoachSession:
    id: uuid.UUID
    org_id: uuid.UUID
    opener: str | None


async def load_coach_session(
    maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> LoadedCoachSession | None:
    """An active voice coach session and the coach's last line. None if there is none."""
    async with maker() as db:
        row = await db.get(CoachSession, session_id)
        if (
            row is None
            or row.status != CoachSessionStatus.ACTIVE
            or row.channel != SessionChannel.VOICE
        ):
            return None
        opener = await db.scalar(
            select(CoachTurn.text)
            .where(
                CoachTurn.coach_session_id == row.id,
                CoachTurn.org_id == row.org_id,
                CoachTurn.speaker == CoachSpeaker.COACH,
            )
            .order_by(CoachTurn.seq.desc())
            .limit(1)
        )
        return LoadedCoachSession(id=row.id, org_id=row.org_id, opener=opener)


@dataclass
class ApiCoach:
    settings: AgentApiSettings
    timeout_s: float = TURN_TIMEOUT_S

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.api_internal_url,
            timeout=self.timeout_s,
            headers={"X-Internal-Token": self.settings.strong_internal_token},
        )

    async def turn(self, session_id: uuid.UUID, text: str) -> dict[str, Any]:
        """The coach's reply as the API returns it (CoachTurnResult)."""
        try:
            async with self._client() as http:
                resp = await http.post(
                    f"/internal/coach/sessions/{session_id}/turns",
                    json={"text": text[:TURN_MAX_CHARS]},
                )
        except httpx.HTTPError as exc:
            raise CoachTurnError(str(exc)) from exc
        if resp.status_code == 409:  # the session ended (in another tab, or by the API)
            return {"reply": None, "ended": True}
        if resp.status_code >= 500:
            raise CoachTurnError(f"coach turn answered {resp.status_code}")
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def end(self, session_id: uuid.UUID) -> None:
        async with self._client() as http:
            resp = await http.post(f"/internal/coach/sessions/{session_id}/end")
            resp.raise_for_status()
