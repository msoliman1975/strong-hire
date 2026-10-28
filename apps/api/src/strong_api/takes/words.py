"""CO-8: what the candidate said about one story, in their own words, oldest first.

Story versions may quote only these texts:
- the candidate's turns in the story's coach sessions (typed, or transcribed by voice);
- for a story saved from a debrief answer (ST-2), the candidate's turns on that question in the
  interview transcript;
- for a story with no coach session, its parts: the candidate typed them (ST-1 manual entry);
- the story's takes (CO-7).

The parts of a story that has a coach session are not in the list: the coach wrote them (CO-3),
in its own wording, so they are not the candidate's words.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.coach.engine import PARTS, part_text
from strong_core.db.models import CoachSession, CoachTurn, Take
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import TURN_ORDER
from strong_core.schemas import CoachSpeaker, Phase, Speaker, StorySource


async def coach_turns(db: AsyncSession, story: StoryRow) -> list[str] | None:
    """The candidate's coach turns on the story; None when no coach session has touched it."""
    sessions = await db.scalar(
        select(CoachSession.id)
        .where(CoachSession.story_id == story.id, CoachSession.org_id == story.org_id)
        .limit(1)
    )
    if sessions is None:
        return None
    rows = await db.scalars(
        select(CoachTurn.text)
        .join(CoachSession, CoachTurn.coach_session_id == CoachSession.id)
        .where(
            CoachSession.story_id == story.id,
            CoachTurn.org_id == story.org_id,
            CoachTurn.speaker == CoachSpeaker.CANDIDATE,
        )
        .order_by(CoachSession.started_at, CoachSession.id, CoachTurn.seq)
    )
    return list(rows)


async def debrief_answer(db: AsyncSession, story: StoryRow) -> list[str]:
    """ST-2: the candidate's turns on the question the story was saved from."""
    if (
        story.source != StorySource.DEBRIEF_ANSWER
        or story.source_session_id is None
        or not story.source_question_ref
    ):
        return []
    rows = await db.scalars(
        select(TurnRow.text)
        .where(
            TurnRow.session_id == story.source_session_id,
            TurnRow.org_id == story.org_id,
            TurnRow.speaker == Speaker.CANDIDATE,
            TurnRow.phase == Phase.CORE,
            TurnRow.question_ref == story.source_question_ref,
        )
        .order_by(*TURN_ORDER)
    )
    return list(rows)


async def own_words(db: AsyncSession, story: StoryRow) -> list[str]:
    """Every text the versions may quote, oldest first. Empty texts are left out."""
    coached = await coach_turns(db, story)
    texts = await debrief_answer(db, story)
    if coached is None:
        if story.source == StorySource.MANUAL:
            texts += [t for p in PARTS if (t := part_text(story, p)) is not None]
    else:
        texts += coached
    takes = await db.scalars(
        select(Take.text)
        .where(Take.story_id == story.id, Take.org_id == story.org_id)
        .order_by(Take.created_at, Take.id)
    )
    texts += list(takes)
    return [t for t in texts if t.strip()]
