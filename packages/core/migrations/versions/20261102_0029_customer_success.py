"""The customer success role family (CS-2)

Adds customer_success to the waitlist role family check. The escalation call (CS-1) is a value of
the session config JSON, so no other check changes. Downgrade maps customer success waitlist
entries to other.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-02
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0029'
down_revision: str | None = '0028'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FAMILIES = (
    "'swe', 'data_ml', 'pm', 'design', 'tpm', 'other', 'infra_security', 'data_analytics', "
    "'eng_management', 'finance', 'consulting_strategy', 'project_program', 'sales'"
)
_CK = 'ck_waitlist_entries_role_family'


def upgrade() -> None:
    op.drop_constraint(op.f(_CK), 'waitlist_entries', type_='check')
    op.create_check_constraint(
        op.f(_CK), 'waitlist_entries', f"role_family IN ({_FAMILIES}, 'customer_success')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE waitlist_entries SET role_family = 'other' WHERE role_family = 'customer_success'"
    )
    op.drop_constraint(op.f(_CK), 'waitlist_entries', type_='check')
    op.create_check_constraint(op.f(_CK), 'waitlist_entries', f"role_family IN ({_FAMILIES})")
