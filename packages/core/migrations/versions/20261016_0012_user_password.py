"""email and password sign-in (AC-4)

Adds users.password_hash and users.email_verified_at, and the 'password' auth provider.
Existing users signed up with a magic link, Google or the dev login, so they already proved
they own the email: email_verified_at is backfilled from created_at. They have no password
until they set one with "Forgot password".

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = 'ck_users_auth_provider'


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'password_hash',
            sa.String(length=255),
            nullable=True,
            comment='AC-4: Argon2id hash. NULL: no password set',
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'email_verified_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='AC-4: when the user proved they own the email. NULL: not confirmed yet',
        ),
    )
    op.execute('UPDATE users SET email_verified_at = created_at')
    op.drop_constraint(op.f(_CK), 'users', type_='check')
    op.create_check_constraint(
        op.f(_CK), 'users', "auth_provider IN ('google', 'email', 'password', 'dev')"
    )


def downgrade() -> None:
    # Password-only accounts cannot exist without the new columns. Keep them as email accounts:
    # they can still sign in with a magic link.
    op.execute("UPDATE users SET auth_provider = 'email' WHERE auth_provider = 'password'")
    op.drop_constraint(op.f(_CK), 'users', type_='check')
    op.create_check_constraint(
        op.f(_CK), 'users', "auth_provider IN ('google', 'email', 'dev')"
    )
    op.drop_column('users', 'email_verified_at')
    op.drop_column('users', 'password_hash')
