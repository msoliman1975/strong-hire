"""Plan reminder email kind (U11, PS-6)

Adds `plan_reminder` to the email_logs kind check, so the daily reminder job logs one row per
user and day (ref = the day) and never sends twice.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-30
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0024'
down_revision: str | None = '0023'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = 'ck_email_logs_email_kind'
_KINDS = (
    "'welcome', 'finish_setup', 'free_interview_nudge', 'debrief_ready', 'paywall_followup', "
    "'interview_countdown_7', 'interview_countdown_2', 'interview_day', 'after_interview', "
    "'minutes_low', 'winback'"
)


def upgrade() -> None:
    op.drop_constraint(op.f(_CK), 'email_logs', type_='check')
    op.create_check_constraint(
        op.f(_CK), 'email_logs', f"kind IN ({_KINDS}, 'plan_reminder')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM email_logs WHERE kind = 'plan_reminder'")
    op.drop_constraint(op.f(_CK), 'email_logs', type_='check')
    op.create_check_constraint(op.f(_CK), 'email_logs', f"kind IN ({_KINDS})")
