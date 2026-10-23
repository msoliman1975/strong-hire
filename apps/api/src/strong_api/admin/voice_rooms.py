"""Remove a candidate from a live voice room (AU-7: a suspended user's sessions end cleanly).

The API marks the session ended (billed and scored) itself. Removing the candidate from the
LiveKit room makes the voice agent take its normal "candidate left" path: it waits for the
reconnect window, then finishes the session as interrupted, which the API has already done, so
that call changes nothing. The candidate cannot rejoin: a suspended user gets 403 on
POST /sessions/{id}/voice/join.

The API reaches LiveKit's server API at LIVEKIT_URL (the internal address, for example
http://livekit:7880). Without it, removal is skipped and logged; the agent then ends the room when
the candidate leaves on their own.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

from fastapi import Request
from livekit import api as livekit_api

from strong_api.sessions.settings import get_voice_session_settings

log = logging.getLogger(__name__)

SESSION_ROOM_PREFIX = "session-"  # same as strong_api.sessions.router


class VoiceRooms(Protocol):
    async def remove_candidate(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Remove the candidate from the session's room. True when it was done."""


class LiveKitVoiceRooms:
    def __init__(self, url: str | None, api_key: str, api_secret: str) -> None:
        self._url = url
        self._key = api_key
        self._secret = api_secret

    async def remove_candidate(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        if not self._url:
            log.info("LIVEKIT_URL is not set; not removing the candidate of %s", session_id)
            return False
        url = self._url.replace("wss://", "https://").replace("ws://", "http://")
        client = livekit_api.LiveKitAPI(url, self._key, self._secret)
        try:
            await client.room.remove_participant(
                livekit_api.RoomParticipantIdentity(
                    room=f"{SESSION_ROOM_PREFIX}{session_id}", identity=f"candidate-{user_id}"
                )
            )
            return True
        except Exception:
            log.warning("could not remove the candidate from room of %s", session_id, exc_info=True)
            return False
        finally:
            await client.aclose()


def get_voice_rooms(request: Request) -> VoiceRooms:
    """The app's VoiceRooms (tests set app.state.voice_rooms), else LiveKit from settings."""
    rooms: VoiceRooms | None = getattr(request.app.state, "voice_rooms", None)
    if rooms is None:
        settings = get_voice_session_settings()
        rooms = LiveKitVoiceRooms(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret.get_secret_value(),
        )
        request.app.state.voice_rooms = rooms
    return rooms
