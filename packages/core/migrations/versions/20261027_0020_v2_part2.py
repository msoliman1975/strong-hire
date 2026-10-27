"""v2 part 2 (C2)

The user-owned stories table for the story library (ST-1). Story fields and delivery metrics
on scorecards (ST-6, DM-1) live inside per_question_json, so they need no column.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-27 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0020'
down_revision: str | None = '0019'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('stories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('context', sa.Text(), nullable=True),
    sa.Column('stakes', sa.Text(), nullable=True),
    sa.Column('action', sa.Text(), nullable=True),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('reflection', sa.Text(), nullable=True),
    sa.Column('skills', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False, comment='list of schemas.Competency values'),
    sa.Column('status', sa.Enum('draft', 'proven', name='story_status', native_enum=False, create_constraint=True, length=32), server_default='draft', nullable=False),
    sa.Column('source', sa.Enum('debrief_answer', 'manual', 'coach', name='story_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source_session_id', sa.Uuid(), nullable=True, comment='ST-2: session of the debrief answer it came from'),
    sa.Column('source_question_ref', sa.String(length=200), nullable=True, comment='ST-2: QuestionScore.question_ref of that answer'),
    sa.Column('notes_json', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False, comment='schemas.StoryNote list (ST-6 fix notes)'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_stories_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_session_id'], ['sessions.id'], name=op.f('fk_stories_source_session_id_sessions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_stories_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stories'))
    )
    op.create_index(op.f('ix_stories_org_id'), 'stories', ['org_id'], unique=False)
    op.create_index(op.f('ix_stories_source_session_id'), 'stories', ['source_session_id'], unique=False)
    op.create_index(op.f('ix_stories_user_id'), 'stories', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stories_user_id'), table_name='stories')
    op.drop_index(op.f('ix_stories_source_session_id'), table_name='stories')
    op.drop_index(op.f('ix_stories_org_id'), table_name='stories')
    op.drop_table('stories')
