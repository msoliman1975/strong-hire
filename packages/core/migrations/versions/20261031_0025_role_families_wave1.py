"""Role families, wave 1 (RF-1)

Adds infra_security, data_analytics, eng_management, finance, consulting_strategy and
project_program to the role_family check. The waitlist is the only table with that column; job
targets keep the family in parsed_json. Downgrade maps the new values to 'other' first.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-31
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0025'
down_revision: str | None = '0024'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = 'waitlist_entries'
_CK = 'ck_waitlist_entries_role_family'
_OLD = "'swe', 'data_ml', 'pm', 'design', 'tpm', 'other'"
_NEW = (
    "'infra_security', 'data_analytics', 'eng_management', 'finance', 'consulting_strategy', "
    "'project_program'"
)


def upgrade() -> None:
    op.drop_constraint(op.f(_CK), _TABLE, type_='check')
    op.create_check_constraint(op.f(_CK), _TABLE, f"role_family IN ({_OLD}, {_NEW})")


def downgrade() -> None:
    op.execute(f"UPDATE {_TABLE} SET role_family = 'other' WHERE role_family IN ({_NEW})")
    op.drop_constraint(op.f(_CK), _TABLE, type_='check')
    op.create_check_constraint(op.f(_CK), _TABLE, f"role_family IN ({_OLD})")
