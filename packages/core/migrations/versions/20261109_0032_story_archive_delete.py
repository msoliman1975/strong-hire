"""Story archive and soft delete (CS-13, CS-15)

Adds stories.archived_at and stories.deleted_at, both nullable with no backfill: NULL means the
story is not archived, or not deleted. deleted_at is indexed for the purge job (CS-16).

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0032'
down_revision: str | None = '0031'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('stories', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True, comment="CS-13: archived; left out of coverage, story-fit and Strova's picks (CS-14)"))
    op.add_column('stories', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='CS-15: soft delete; restorable for 30 days, then purged (CS-16)'))
    op.create_index(op.f('ix_stories_deleted_at'), 'stories', ['deleted_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stories_deleted_at'), table_name='stories')
    op.drop_column('stories', 'deleted_at')
    op.drop_column('stories', 'archived_at')
