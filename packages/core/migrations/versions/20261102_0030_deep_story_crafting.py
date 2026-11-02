"""Deep story crafting outline (SC-1, SC-2, RMAP-8)

Adds the story style and outline columns, the flow check and skill hint stores, and the coach
session's section in progress. Every new column is nullable. There is no backfill: classic stories
keep a null style and outline until the candidate organizes them (D-11).

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0030'
down_revision: str | None = '0029'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('coach_sessions', sa.Column('section', sa.Enum('situation', 'challenge', 'task', 'action', 'result', 'learning', name='story_section', native_enum=False, create_constraint=True, length=32), nullable=True, comment='SC-4: the outline section in progress'))
    op.add_column('stories', sa.Column('style', sa.Enum('star', 'carl', name='story_style', native_enum=False, create_constraint=True, length=32), nullable=True, comment='SC-1: star or carl; NULL for a classic story'))
    op.add_column('stories', sa.Column('outline_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='SC-2: schemas.StoryOutline; NULL for a classic story'))
    op.add_column('stories', sa.Column('flow_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='SC-9: the last schemas.FlowCheck and the dismissed flag keys'))
    op.add_column('stories', sa.Column('hints_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='SC-8: skill hints (schemas.SkillHint) with their state'))


def downgrade() -> None:
    op.drop_column('stories', 'hints_json')
    op.drop_column('stories', 'flow_json')
    op.drop_column('stories', 'outline_json')
    op.drop_column('stories', 'style')
    op.drop_column('coach_sessions', 'section')
