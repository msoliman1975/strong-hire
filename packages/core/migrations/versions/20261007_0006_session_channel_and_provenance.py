"""session channel and provenance

P7 (PL-6, PL-7). Adds four columns to sessions: channel (voice, or text behind a dev flag),
and the provenance of the interviewer: model_profile, interviewer_model_id and prompt_version.
Existing rows become voice sessions with no provenance.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('channel', sa.Enum('voice', 'text', name='session_channel', native_enum=False, create_constraint=True, length=32), server_default='voice', nullable=False, comment='PL-7: voice, or text behind a dev flag'))
    op.add_column('sessions', sa.Column('model_profile', sa.String(length=20), nullable=True, comment='PL-6: MODEL_PROFILE the session ran on'))
    op.add_column('sessions', sa.Column('interviewer_model_id', sa.String(length=200), nullable=True, comment='PL-6: gateway alias that served the interviewer role'))
    op.add_column('sessions', sa.Column('prompt_version', sa.String(length=200), nullable=True, comment='PL-6: interviewer prompt refs, comma separated'))


def downgrade() -> None:
    op.drop_column('sessions', 'prompt_version')
    op.drop_column('sessions', 'interviewer_model_id')
    op.drop_column('sessions', 'model_profile')
    op.drop_column('sessions', 'channel')
