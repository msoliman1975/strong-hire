"""Re-read stored CV files with the current reader and extractor, and update the parsed CV.

    python -m strong_worker.inputs.reread [--dry-run] [--include-confirmed] [--org ID]
                                          [--resume ID] [--limit N]

Run it once after a change to the file reader (documents.py) or the resume prompt, inside the
worker container (docs/hosting.md). For every CV that is not deleted (R1 deleted_at) and has a
stored file, it decrypts the file, reads its text with `document_text`, runs the extractor and
writes the result to resumes.parsed_json. Each update adds an audit_logs row with the action
"resume.reread".

A CV the user confirmed on the "Check your CV" screen (confirmed_at) is skipped: the user's
version wins. `--include-confirmed` overwrites those too and clears confirmed_at, so the user
sees the screen again. Use it only after you asked the users.

`--dry-run` reads and extracts but writes nothing. It still calls the model, so it costs the
same as a real run. Gap reports made before the run keep their numbers; the next gap analysis
uses the new data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import AuditLog
from strong_core.db.models import Resume as ResumeRow
from strong_core.gateway import ModelGateway, get_gateway
from strong_core.sim import gateway_for_org
from strong_worker.inputs.documents import DocumentError, document_text
from strong_worker.inputs.extract import ExtractionError, extract_resume
from strong_worker.inputs.settings import get_inputs_settings
from strong_worker.inputs.storage import FileStore, build_file_store

log = logging.getLogger(__name__)

ACTOR = "system:resume-reread"
ACTION = "resume.reread"


@dataclass
class RereadSummary:
    outcomes: Counter[str] = field(default_factory=Counter)
    details: list[dict[str, Any]] = field(default_factory=list)

    def add(self, resume_id: uuid.UUID, outcome: str, **extra: Any) -> None:
        self.outcomes[outcome] += 1
        self.details.append({"resume_id": str(resume_id), "outcome": outcome, **extra})

    def format(self) -> str:
        lines = [f"{name}: {count}" for name, count in sorted(self.outcomes.items())]
        return "\n".join(lines) or "no CVs to read"


async def reread_resumes(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: FileStore,
    gateway: ModelGateway,
    *,
    dry_run: bool = False,
    include_confirmed: bool = False,
    org_id: uuid.UUID | None = None,
    resume_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> RereadSummary:
    """Re-read every stored, not deleted CV. One CV failing never stops the others."""
    summary = RereadSummary()
    query = select(ResumeRow.id).where(
        ResumeRow.deleted_at.is_(None), ResumeRow.file_ref.is_not(None)
    )
    if org_id is not None:
        query = query.where(ResumeRow.org_id == org_id)
    if resume_id is not None:
        query = query.where(ResumeRow.id == resume_id)
    query = query.order_by(ResumeRow.uploaded_at)
    if limit is not None:
        query = query.limit(limit)
    async with sessionmaker() as db:
        ids = list((await db.scalars(query)).all())

    for rid in ids:
        try:
            await _reread_one(
                sessionmaker,
                store,
                gateway,
                rid,
                summary,
                dry_run=dry_run,
                include_confirmed=include_confirmed,
            )
        except Exception as exc:  # storage, database: report it and go on
            log.exception("re-read of resume %s failed", rid)
            summary.add(rid, "error", reason=f"{type(exc).__name__}: {exc}"[:300])
    return summary


async def _reread_one(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: FileStore,
    gateway: ModelGateway,
    rid: uuid.UUID,
    summary: RereadSummary,
    *,
    dry_run: bool,
    include_confirmed: bool,
) -> None:
    async with sessionmaker() as db:
        row = await db.get(ResumeRow, rid)
        if row is None or row.deleted_at is not None or row.file_ref is None:
            summary.add(rid, "skipped_deleted")
            return
        if row.confirmed_at is not None and not include_confirmed:
            summary.add(rid, "skipped_confirmed")
            return
        data = await store.get(row.file_ref)
        try:
            kind, text = document_text(data)
        except DocumentError as exc:
            summary.add(rid, "unreadable", reason=str(exc))
            return
        try:
            extraction = await extract_resume(await gateway_for_org(db, row.org_id, gateway), text)
        except ExtractionError as exc:
            summary.add(rid, "extraction_failed", reason=str(exc)[:300])
            return

        new = extraction.output.model_dump(mode="json")
        changed = new != row.parsed_json
        details = {
            "kind": kind,
            "changed": changed,
            "roles_before": len((row.parsed_json or {}).get("roles", [])),
            "roles_after": len(extraction.output.roles),
            "prompt_refs": list(extraction.prompt_refs),
            "flags": extraction.flags[:10],
            "was_confirmed": row.confirmed_at is not None,
        }
        if dry_run:
            summary.add(rid, "would_update" if changed else "unchanged", **details)
            return

        await db.refresh(row)
        if row.deleted_at is not None:  # deleted while it was read
            summary.add(rid, "skipped_deleted")
            return
        if row.confirmed_at is not None and not include_confirmed:  # confirmed meanwhile
            summary.add(rid, "skipped_confirmed")
            return
        row.parsed_json = new
        row.confirmed_at = None
        db.add(
            AuditLog(
                org_id=row.org_id,
                actor=ACTOR,
                action=ACTION,
                entity=f"resume:{row.id}",
                details_json=details,
            )
        )
        await db.commit()
        summary.add(rid, "updated" if changed else "unchanged", **details)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Read and extract; write nothing.")
    parser.add_argument(
        "--include-confirmed",
        action="store_true",
        help="Also overwrite CVs the user confirmed. Ask the users first.",
    )
    parser.add_argument("--org", type=uuid.UUID, help="Only CVs of this org.")
    parser.add_argument("--resume", type=uuid.UUID, help="Only this CV.")
    parser.add_argument("--limit", type=int, help="At most this many CVs, oldest first.")
    parser.add_argument("--verbose", action="store_true", help="Print one line per CV.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    summary = asyncio.run(
        reread_resumes(
            get_sessionmaker(),
            build_file_store(get_inputs_settings()),
            get_gateway(),
            dry_run=args.dry_run,
            include_confirmed=args.include_confirmed,
            org_id=args.org,
            resume_id=args.resume,
            limit=args.limit,
        )
    )
    if args.verbose:
        for item in summary.details:
            print(item)
    print(("Dry run. " if args.dry_run else "") + "CVs by outcome:")
    print(summary.format())


if __name__ == "__main__":
    main()
