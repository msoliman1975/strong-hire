"""resume confirmed by the user

Adds resumes.confirmed_at, the time the user checked and saved the extracted CV on the
"Check your CV" screen (PUT /resumes/{id}). A later re-read of the stored file
(strong_worker.inputs.reread) does not overwrite a confirmed CV unless asked to.
Existing rows stay NULL: nobody has confirmed them yet.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'resumes',
        sa.Column(
            'confirmed_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='When the user checked and saved the extracted CV. NULL: not confirmed',
        ),
    )


def downgrade() -> None:
    op.drop_column('resumes', 'confirmed_at')
