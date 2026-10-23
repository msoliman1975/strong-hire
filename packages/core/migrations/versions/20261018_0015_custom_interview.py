"""custom interview (docs/custom-interview-spec.md, C0)

Adds the 'custom' interview type (CU-1), sessions.custom_json for the candidate's setup, and
the user-owned saved_questions table (CU-8).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = 'ck_sessions_interview_type'
_STANDARD = "'behavioral', 'hiring_manager', 'technical_qa', 'case'"


def upgrade() -> None:
    op.drop_constraint(op.f(_CK), 'sessions', type_='check')
    op.create_check_constraint(op.f(_CK), 'sessions', f"type IN ({_STANDARD}, 'custom')")
    op.add_column(
        'sessions',
        sa.Column(
            'custom_json',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='CU-1: schemas.CustomSessionSpec. NULL for the four standard types',
        ),
    )
    op.create_table('saved_questions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False, comment='schemas.CustomQuestion.text'),
    sa.Column('category', sa.Enum('behavioral', 'hiring_manager', 'technical_qa', 'case', 'custom', name='saved_question_category', native_enum=False, create_constraint=True, length=32), nullable=False, comment='One of the four standard types, never custom'),
    sa.Column('competencies', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='list of schemas.Competency values'),
    sa.Column('bank_ref', sa.String(length=200), nullable=True, comment='Question bank id when added from the Questions page'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_saved_questions_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_saved_questions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_saved_questions'))
    )
    op.create_index(op.f('ix_saved_questions_org_id'), 'saved_questions', ['org_id'], unique=False)
    op.create_index(op.f('ix_saved_questions_user_id'), 'saved_questions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_saved_questions_user_id'), table_name='saved_questions')
    op.drop_index(op.f('ix_saved_questions_org_id'), table_name='saved_questions')
    op.drop_table('saved_questions')
    op.drop_column('sessions', 'custom_json')
    # Custom sessions cannot exist under the old constraint. Their transcripts and scorecards
    # cascade from the session row.
    op.execute("DELETE FROM sessions WHERE type = 'custom'")
    op.drop_constraint(op.f(_CK), 'sessions', type_='check')
    op.create_check_constraint(op.f(_CK), 'sessions', f"type IN ({_STANDARD})")
