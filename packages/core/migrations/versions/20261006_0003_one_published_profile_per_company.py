"""one published profile per company

Adds a partial unique index on company_profiles (company_id) WHERE status = 'published'.
One company can have at most one Published profile version (AD-1). Publish already archives
the old version, so existing data has at most one Published row per company.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06 01:08:47.334756
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'uq_company_profiles_one_published',
        'company_profiles',
        ['company_id'],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )


def downgrade() -> None:
    op.drop_index('uq_company_profiles_one_published', table_name='company_profiles')
