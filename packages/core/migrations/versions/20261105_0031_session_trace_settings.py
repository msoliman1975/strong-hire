"""Session trace settings for LLM tracing (LT-14)

Adds sessions.trace_json: how a sim user's session is traced (schemas.SessionTraceSettings).
Nullable, no backfill: NULL means the session is not a traced sim session.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0031'
down_revision: str | None = '0030'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('trace_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="LT-14: schemas.SessionTraceSettings for a sim user's session; NULL otherwise"))


def downgrade() -> None:
    op.drop_column('sessions', 'trace_json')
