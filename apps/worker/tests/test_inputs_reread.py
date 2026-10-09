"""IN-3: re-read stored CV files with the current reader and extractor (one-off command)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import get_settings
from strong_core.db.models import AuditLog
from strong_core.db.models import Resume as ResumeRow
from strong_core.gateway import ModelGateway
from strong_worker.inputs.reread import ACTION, reread_resumes
from strong_worker.inputs.storage import LocalEncryptedFileStore
from strong_worker.inputs.testing import set_extractor_output

RESUMES = get_settings().repo_root / "evals/fixtures/inputs/resumes"
OLD = {"summary": None, "roles": [], "skills": ["Old"], "education": [], "certifications": []}
Account = tuple[uuid.UUID, uuid.UUID]


async def stored_resume(
    maker: async_sessionmaker[AsyncSession],
    store: LocalEncryptedFileStore,
    account: Account,
    **values: Any,
) -> uuid.UUID:
    org_id, user_id = account
    data = (RESUMES / "date-column.pdf").read_bytes()
    async with maker() as db:
        row = ResumeRow(org_id=org_id, user_id=user_id, parsed_json=OLD, **values)
        db.add(row)
        await db.flush()
        row.file_ref = await store.put(f"resumes/{org_id}/{row.id}.pdf", data)
        await db.commit()
        return row.id


async def load(maker: async_sessionmaker[AsyncSession], rid: uuid.UUID) -> ResumeRow:
    async with maker() as db:
        row = await db.get(ResumeRow, rid)
        assert row is not None
        return row


async def test_in3_reread_updates_stored_cvs_and_skips_deleted_and_confirmed(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: LocalEncryptedFileStore,
    gateway: ModelGateway,
    account: Account,
    fake_fixtures: Path,
) -> None:
    expected = json.loads((RESUMES / "date-column.json").read_text(encoding="utf-8"))
    set_extractor_output(fake_fixtures, "Resume", expected)
    plain = await stored_resume(sessionmaker, store, account)
    deleted = await stored_resume(sessionmaker, store, account, deleted_at=datetime.now(UTC))
    confirmed = await stored_resume(sessionmaker, store, account, confirmed_at=datetime.now(UTC))
    async with sessionmaker() as db:
        db.add(ResumeRow(org_id=account[0], user_id=account[1], parsed_json=OLD))  # no file
        await db.commit()

    dry = await reread_resumes(sessionmaker, store, gateway, dry_run=True)
    assert dry.outcomes == {"would_update": 1, "skipped_confirmed": 1}
    assert (await load(sessionmaker, plain)).parsed_json == OLD

    summary = await reread_resumes(sessionmaker, store, gateway)

    assert summary.outcomes == {"updated": 1, "skipped_confirmed": 1}
    assert (await load(sessionmaker, plain)).parsed_json == expected
    assert (await load(sessionmaker, deleted)).parsed_json == OLD
    assert (await load(sessionmaker, confirmed)).parsed_json == OLD
    async with sessionmaker() as db:
        audits = (await db.scalars(select(AuditLog).where(AuditLog.action == ACTION))).all()
    assert [a.entity for a in audits] == [f"resume:{plain}"]
    assert audits[0].details_json is not None
    assert audits[0].details_json["changed"] is True
    assert audits[0].details_json["kind"] == "pdf"


async def test_in3_reread_overwrites_a_confirmed_cv_only_when_asked(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: LocalEncryptedFileStore,
    gateway: ModelGateway,
    account: Account,
    fake_fixtures: Path,
) -> None:
    expected = json.loads((RESUMES / "date-column.json").read_text(encoding="utf-8"))
    set_extractor_output(fake_fixtures, "Resume", expected)
    confirmed = await stored_resume(sessionmaker, store, account, confirmed_at=datetime.now(UTC))

    summary = await reread_resumes(sessionmaker, store, gateway, include_confirmed=True)

    assert summary.outcomes == {"updated": 1}
    row = await load(sessionmaker, confirmed)
    assert row.parsed_json == expected
    assert row.confirmed_at is None  # the user sees "Check your CV" again


async def test_in3_reread_reports_a_broken_file_and_goes_on(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: LocalEncryptedFileStore,
    gateway: ModelGateway,
    account: Account,
    fake_fixtures: Path,
) -> None:
    expected = json.loads((RESUMES / "date-column.json").read_text(encoding="utf-8"))
    set_extractor_output(fake_fixtures, "Resume", expected)
    missing = await stored_resume(sessionmaker, store, account)
    good = await stored_resume(sessionmaker, store, account)
    await store.delete((await load(sessionmaker, missing)).file_ref or "")

    summary = await reread_resumes(sessionmaker, store, gateway)

    assert summary.outcomes == {"error": 1, "updated": 1}
    assert (await load(sessionmaker, good)).parsed_json == expected
