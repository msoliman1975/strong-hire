"""v2 part 1 (C1)

The tone the user picked on sessions (TN-1); old rows read as as_company. The
company_auto_profiles table for companies outside the curated list (AP-1). The v2_enabled
runtime setting (FL-1) needs no migration: a missing row means its default, off.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-27 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0019'
down_revision: str | None = '0018'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('company_auto_profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_name', sa.String(length=200), nullable=False, comment='As the job posting wrote it'),
    sa.Column('normalized_name', sa.String(length=200), nullable=False, comment='Lowercase, punctuation and legal suffixes removed'),
    sa.Column('source_host', sa.String(length=255), nullable=False, comment="The job posting's domain the pages came from"),
    sa.Column('summary', sa.Text(), nullable=False, comment='AutoProfileSummary.summary'),
    sa.Column('summary_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.AutoProfileSummary'),
    sa.Column('sources_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='URLs of the pages used'),
    sa.Column('status', sa.Enum('pending', 'approved', 'retired', name='auto_profile_status', native_enum=False, create_constraint=True, length=32), server_default='pending', nullable=False),
    sa.Column('reviewed_by', sa.String(length=320), nullable=True, comment='Admin email'),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('model_profile', sa.String(length=20), nullable=False, comment='PL-6: MODEL_PROFILE the job ran on'),
    sa.Column('model_id', sa.String(length=200), nullable=False, comment='PL-6: gateway alias that served the extractor role'),
    sa.Column('prompt_version', sa.String(length=200), nullable=False, comment='PL-6: extractor prompt refs, comma separated'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_auto_profiles'))
    )
    op.create_index(op.f('ix_company_auto_profiles_normalized_name'), 'company_auto_profiles', ['normalized_name'], unique=False)
    op.create_index(
        'uq_company_auto_profiles_one_live',
        'company_auto_profiles',
        ['normalized_name'],
        unique=True,
        postgresql_where=sa.text("status <> 'retired'"),
        sqlite_where=sa.text("status <> 'retired'"),
    )

    op.add_column('sessions', sa.Column('tone', sa.Enum('as_company', 'warm', 'neutral', 'direct', name='tone', native_enum=False, create_constraint=True, length=32), server_default='as_company', nullable=False, comment='TN-1: the tone the user picked; as_company uses the profile persona'))


def downgrade() -> None:
    op.drop_column('sessions', 'tone')
    op.drop_index('uq_company_auto_profiles_one_live', table_name='company_auto_profiles')
    op.drop_index(op.f('ix_company_auto_profiles_normalized_name'), table_name='company_auto_profiles')
    op.drop_table('company_auto_profiles')
