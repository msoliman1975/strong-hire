"""AC-1 export and delete cover saved questions (docs/custom-interview-spec.md: CU-8)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import USER_OWNED_TABLES, SavedQuestion, User
from strong_core.schemas import InterviewType
from strong_worker.account.bundle import build_bundle
from strong_worker.inputs.storage import LocalEncryptedFileStore


async def _saved_question(
    maker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> uuid.UUID:
    org_id, user_id = account
    async with maker() as db:
        row = SavedQuestion(
            org_id=org_id,
            user_id=user_id,
            text="Why are you leaving your current job after only a year?",
            category=InterviewType.HIRING_MANAGER,
            competencies=["motivation"],
            bank_ref="hm-why-leaving",
        )
        db.add(row)
        await db.commit()
        return row.id


async def test_cu8_export_includes_saved_questions(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    store: LocalEncryptedFileStore,
) -> None:
    """CU-8, AC-1: the export bundle has the user's saved questions."""
    org_id, user_id = account
    row_id = await _saved_question(sessionmaker, account)
    async with sessionmaker() as db:
        bundle, summary = await build_bundle(db, store, org_id, user_id, 10_000_000)
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        data = json.loads(zf.read("data.json"))
    rows = data["tables"]["saved_questions"]
    assert summary["rows"]["saved_questions"] == 1
    assert rows[0]["id"] == str(row_id)
    assert rows[0]["text"] == "Why are you leaving your current job after only a year?"
    assert rows[0]["category"] == "hiring_manager"
    assert rows[0]["competencies"] == ["motivation"]
    assert rows[0]["bank_ref"] == "hm-why-leaving"


async def test_cu8_delete_removes_saved_questions(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """CU-8, AC-1: saved questions are a user-owned table (the full account delete clears every
    one) and go with their user through the foreign key."""
    assert "saved_questions" in USER_OWNED_TABLES
    _, user_id = account
    await _saved_question(sessionmaker, account)
    async with sessionmaker() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
        assert (await db.scalars(select(SavedQuestion))).all() == []
