"""library names and soft delete

R1. Saved job descriptions and CVs get a name, a content hash and a soft delete:

- job_targets: name, text_hash (SHA-256 of the normalized posting text), deleted_at
- resumes: name, content_hash (SHA-256 of the file or pasted text), deleted_at

Deleting a saved job or CV now clears its content and sets deleted_at, so gap reports, sessions
and progress keep their rows. The foreign keys from gap_analyses, sessions and
progress_snapshots to job_targets and resumes stop cascading.

Backfill: every job target gets "<title> at <company>" (else the link's host, else
"Job description <date>") and the hash of its text. Existing resumes get "CV <date>": the
original file name was never stored, and the encrypted files are not read here, so their
content_hash stays NULL.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 06:00:00.000000
"""

import hashlib
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (constraint, table, column, referred table) of the keys that no longer cascade.
_FKS = (
    ('fk_gap_analyses_job_target_id_job_targets', 'gap_analyses', 'job_target_id', 'job_targets'),
    ('fk_gap_analyses_resume_id_resumes', 'gap_analyses', 'resume_id', 'resumes'),
    ('fk_sessions_job_target_id_job_targets', 'sessions', 'job_target_id', 'job_targets'),
    (
        'fk_progress_snapshots_job_target_id_job_targets',
        'progress_snapshots',
        'job_target_id',
        'job_targets',
    ),
)

# Copies of strong_core.library rules as of this revision. A migration must not change later.
_SPACE = re.compile(r"\s+")


def _clean(name: str) -> str:
    return _SPACE.sub(" ", name).strip()[:120].strip()


def _text_hash(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    normalized = _SPACE.sub(" ", text).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _job_name(parsed: Any, source_url: str | None, created: datetime | None) -> str:
    parsed = parsed if isinstance(parsed, dict) else {}
    title = str(parsed.get('title') or '').strip()
    company = str(parsed.get('company_name') or '').strip()
    if title and company:
        return _clean(f"{title} at {company}")
    if title or company:
        return _clean(title or company)
    host = (urlsplit(source_url).hostname or '').lower().removeprefix('www.') if source_url else ''
    if host:
        return _clean(host)
    day = (created or datetime.now()).date().isoformat()
    return f"Job description {day}"


def upgrade() -> None:
    op.add_column('job_targets', sa.Column('name', sa.String(length=120), nullable=True, comment='R1: name in the job library. NULL means the default name'))
    op.add_column('job_targets', sa.Column('text_hash', sa.String(length=64), nullable=True, comment='R1: SHA-256 of the normalized posting text'))
    op.add_column('job_targets', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='R1: soft delete. Content is cleared; reports, sessions and progress stay'))
    op.create_index(op.f('ix_job_targets_text_hash'), 'job_targets', ['text_hash'], unique=False)
    op.add_column('resumes', sa.Column('name', sa.String(length=120), nullable=True, comment='R1: name in the CV library. NULL after delete'))
    op.add_column('resumes', sa.Column('content_hash', sa.String(length=64), nullable=True, comment='R1: SHA-256 of the uploaded file or pasted text'))
    op.add_column('resumes', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='R1: soft delete. Content is cleared; gap reports that used it stay'))
    op.create_index(op.f('ix_resumes_content_hash'), 'resumes', ['content_hash'], unique=False)

    for name, table, column, referred in _FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, referred, [column], ['id'])

    bind = op.get_bind()
    jobs = bind.execute(
        sa.text('SELECT id, raw_text, parsed_json, source_url, created_at FROM job_targets')
    ).all()
    for row in jobs:
        bind.execute(
            sa.text('UPDATE job_targets SET name = :name, text_hash = :hash WHERE id = :id'),
            {
                'id': row.id,
                'name': _job_name(row.parsed_json, row.source_url, row.created_at),
                'hash': _text_hash(row.raw_text),
            },
        )
    resumes = bind.execute(sa.text('SELECT id, uploaded_at FROM resumes')).all()
    for row in resumes:
        day = (row.uploaded_at or datetime.now()).date().isoformat()
        bind.execute(
            sa.text('UPDATE resumes SET name = :name WHERE id = :id'),
            {'id': row.id, 'name': f"CV {day}"},
        )


def downgrade() -> None:
    # Soft-deleted rows stay, without content, so no report is lost by a downgrade.
    for name, table, column, referred in _FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, referred, [column], ['id'], ondelete='CASCADE')

    op.drop_index(op.f('ix_resumes_content_hash'), table_name='resumes')
    op.drop_column('resumes', 'deleted_at')
    op.drop_column('resumes', 'content_hash')
    op.drop_column('resumes', 'name')
    op.drop_index(op.f('ix_job_targets_text_hash'), table_name='job_targets')
    op.drop_column('job_targets', 'deleted_at')
    op.drop_column('job_targets', 'text_hash')
    op.drop_column('job_targets', 'name')
