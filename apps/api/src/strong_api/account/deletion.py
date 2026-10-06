"""Full account delete (AC-1): every user-owned row now, the resume files by a worker job.

Rows: every table in USER_OWNED_TABLES is cleared for the org, children first, then the org.
New user-owned tables are covered once they are added to USER_OWNED_TABLES (a core test makes
that list complete). AuditLog rows stay, with the email replaced by the user id, and a new
entry records the deletion.

Files: the original resume files live in the worker's encrypted file store, so the API sends
their refs to the `delete_account_files` worker job (retried by Arq on failure).

Backups: database backups are not changed. They expire on their normal rotation, 30 days at
most (spec: Privacy, security and compliance). BACKUP_RETENTION_DAYS records that promise.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Table, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import USER_OWNED_TABLES, AuditLog, Base, Org, Resume

BACKUP_RETENTION_DAYS = 30
DELETE_DEADLINE_HOURS = 24


@dataclass(frozen=True)
class DeletionResult:
    rows: dict[str, int]
    file_refs: list[str]

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())


def user_owned_tables_children_first() -> list[Table]:
    """User-owned tables in foreign key order, so each delete removes children first."""
    names = set(USER_OWNED_TABLES)
    return [t for t in reversed(Base.metadata.sorted_tables) if t.name in names]


async def resume_file_refs(db: AsyncSession, org_id: uuid.UUID) -> list[str]:
    refs = await db.scalars(
        select(Resume.file_ref).where(Resume.org_id == org_id, Resume.file_ref.is_not(None))
    )
    return [r for r in refs if r]


async def delete_org_rows(db: AsyncSession, org_id: uuid.UUID) -> DeletionResult:
    """Delete every row of the org. The caller commits."""
    refs = await resume_file_refs(db, org_id)
    rows: dict[str, int] = {}
    for table in user_owned_tables_children_first():
        result = await db.execute(delete(table).where(table.c.org_id == org_id))
        rows[table.name] = int(getattr(result, "rowcount", 0) or 0)
    result = await db.execute(delete(Org).where(Org.id == org_id))
    rows["orgs"] = int(getattr(result, "rowcount", 0) or 0)
    return DeletionResult(rows=rows, file_refs=refs)


async def redact_audit_actor(db: AsyncSession, org_id: uuid.UUID, email: str, actor: str) -> None:
    """Keep the audit trail but drop the email from it."""
    await db.execute(
        update(AuditLog)
        .where(AuditLog.org_id == org_id, AuditLog.actor == email)
        .values(actor=actor)
    )
