"""The AC-1 data export bundle: a zip with data.json and the original resume files.

data.json holds every row of every user-owned table for the org (USER_OWNED_TABLES, so new
tables are included once listed there), the org row, and the org's audit log entries. Resume
files are decrypted from the file store and added under resumes/.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import USER_OWNED_TABLES, AuditLog, Base, Org, Resume
from strong_worker.inputs.storage import FileStore, StorageError

FORMAT = "strong-hire-export"
FORMAT_VERSION = 1

README = """Strong Hire data export

data.json     Every record we keep about you, one list per table.
resumes/      The original resume files you uploaded.

Audio is never stored, so it is not in this export.
"""


class ExportTooLargeError(RuntimeError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value  # enums
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row._mapping.items()}


async def collect_rows(db: AsyncSession, org_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """Every user-owned row of the org, by table name, plus the org and its audit log."""
    tables: dict[str, list[dict[str, Any]]] = {}
    org_table = Org.__table__
    tables["orgs"] = [
        _row_dict(r) for r in await db.execute(select(org_table).where(org_table.c.id == org_id))
    ]
    names = set(USER_OWNED_TABLES)
    for table in Base.metadata.sorted_tables:
        if table.name not in names:
            continue
        result = await db.execute(select(table).where(table.c.org_id == org_id))
        tables[table.name] = [_row_dict(r) for r in result]
    audit = AuditLog.__table__
    result = await db.execute(select(audit).where(audit.c.org_id == org_id).order_by(audit.c.at))
    tables["audit_logs"] = [_row_dict(r) for r in result]
    return tables


def _file_name(resume_id: str, ref: str) -> str:
    suffix = PurePosixPath(ref).suffix or ".bin"
    return f"resumes/{resume_id}{suffix}"


async def build_bundle(
    db: AsyncSession,
    store: FileStore,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    max_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    """Return the zip bytes and a short summary."""
    tables = await collect_rows(db, org_id)
    files: list[dict[str, Any]] = []
    blobs: list[tuple[str, bytes]] = []
    total = 0
    resumes = await db.scalars(
        select(Resume).where(Resume.org_id == org_id, Resume.file_ref.is_not(None))
    )
    for resume in resumes:
        assert resume.file_ref is not None
        name = _file_name(str(resume.id), resume.file_ref)
        try:
            data = await store.get(resume.file_ref)
        except (OSError, StorageError) as exc:
            files.append({"resume_id": str(resume.id), "path": None, "error": str(exc)})
            continue
        total += len(data)
        if total > max_bytes:
            raise ExportTooLargeError(f"The export is larger than {max_bytes} bytes")
        blobs.append((name, data))
        files.append(
            {
                "resume_id": str(resume.id),
                "path": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    document = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "user_id": str(user_id),
        "org_id": str(org_id),
        "tables": tables,
        "files": files,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", README)
        zf.writestr("data.json", json.dumps(document, indent=2, ensure_ascii=False))
        for name, data in blobs:
            zf.writestr(name, data)
    bundle = buffer.getvalue()
    if len(bundle) > max_bytes:
        raise ExportTooLargeError(f"The export is larger than {max_bytes} bytes")
    summary = {
        "bytes": len(bundle),
        "files": len(blobs),
        "rows": {name: len(rows) for name, rows in tables.items()},
    }
    return bundle, summary
