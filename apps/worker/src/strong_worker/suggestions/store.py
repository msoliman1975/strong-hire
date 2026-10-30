"""SG-1, SG-8: store a suggestion once. One of the same kind, source and target, in any status,
blocks a new one, so a dismissed suggestion never comes back and an accepted one is not offered
again."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.schemas import Contract, SuggestionKind, SuggestionStatus

# The columns that name a suggestion's source and target.
KEY_COLUMNS = (
    "source_session_id",
    "source_question_ref",
    "source_resume_id",
    "job_target_id",
    "story_id",
    "resume_id",
)


async def add_suggestion(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: SuggestionKind,
    payload: Contract,
    reason: str,
    prompt_ref: str | None = None,
    same: Callable[[dict[str, Any]], bool] = lambda _payload: True,
    extra: dict[str, Any] | None = None,
    **key: Any,
) -> bool:
    """Add an open suggestion unless one with this kind and key exists (`same` compares the
    stored payload when the key alone is not enough). `extra` columns are stored but not
    compared. True when it was added."""
    unknown = (set(key) | set(extra or {})) - set(KEY_COLUMNS)
    if unknown:
        raise ValueError(f"not a key column: {sorted(unknown)}")
    query = select(SuggestionRow).where(
        SuggestionRow.org_id == org_id,
        SuggestionRow.user_id == user_id,
        SuggestionRow.kind == kind,
    )
    for column in KEY_COLUMNS:
        if extra and column in extra:
            continue
        value = key.get(column)
        attr = getattr(SuggestionRow, column)
        query = query.where(attr.is_(None) if value is None else attr == value)
    if any(same(row.payload) for row in await db.scalars(query)):
        return False
    db.add(
        SuggestionRow(
            org_id=org_id,
            user_id=user_id,
            kind=kind,
            status=SuggestionStatus.OPEN,
            payload=payload.model_dump(mode="json"),
            reason=reason,
            prompt_ref=prompt_ref,
            **key,
            **(extra or {}),
        )
    )
    return True


def payload_has(field: str, value: Any) -> Callable[[dict[str, Any]], bool]:
    """`same` for add_suggestion: the stored payload has this value in `field`."""
    return lambda payload: payload.get(field) == value
