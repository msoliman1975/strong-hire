"""turn order in the session

Adds turns.seq, the place of each turn in its session (strong_core.db.turns). Two turns can have
the same start_ms and end_ms and ids are random, so the transcript order was not stable. Existing
rows are numbered by start_ms, end_ms and id, which is the best order known for them.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'turns',
        sa.Column(
            'seq',
            sa.Integer(),
            nullable=True,
            comment='Order of the turn in its session, from 1 (strong_core.db.turns)',
        ),
    )
    op.execute(
        """
        UPDATE turns SET seq = numbered.n
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY session_id ORDER BY start_ms, end_ms, id
            ) AS n
            FROM turns
        ) AS numbered
        WHERE turns.id = numbered.id
        """
    )


def downgrade() -> None:
    op.drop_column('turns', 'seq')
