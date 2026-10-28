"""resume accepted issues

resumes.accepted_issues: the CV check issues the user marked as fine, a JSON list of
schemas.AcceptedIssue ({key, accepted_at}). NULL until the user accepts one.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-28 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0022'
down_revision: str | None = '0021'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('resumes', sa.Column('accepted_issues', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='schemas.AcceptedIssues: CV check issues the user accepted. NULL: none yet'))


def downgrade() -> None:
    op.drop_column('resumes', 'accepted_issues')
