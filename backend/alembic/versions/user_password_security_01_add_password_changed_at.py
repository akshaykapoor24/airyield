"""Revoke live sessions when a password changes

Access tokens are stateless 24-hour JWTs with no jti and no blocklist, so until
now changing a password did nothing to a token already in an attacker's hands —
it stayed valid for the rest of the day. This column records the instant the
password last changed; get_current_user rejects any token whose `iat` predates
it, which turns both change-password and password-reset into a real
sign-out-everywhere.

It is deliberately nullable with no backfill and no server_default. NULL means
"we have never observed a password change for this user", and the check is
skipped entirely in that case — so deploying this signs nobody out. The column
only starts biting the first time someone actually changes their password, and
then only for their other sessions: the change-password response hands back a
freshly minted token so the acting tab keeps working.

The value is written truncated to whole seconds (microsecond=0) on purpose.
python-jose encodes `iat` as timegm(utctimetuple()), which floors to the second;
storing sub-second precision here would make a token minted microseconds AFTER
the change compare as older than it and log the user out of the very session
that performed the change.

Revision ID: user_password_security_01
Revises: master_approval_admin_edit_01
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "user_password_security_01"
down_revision: Union[str, None] = "master_approval_admin_edit_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Dropping this reverts to "a password change revokes nothing": tokens issued
    # before a change become valid again for the remainder of their 24h life.
    # Rotate SECRET_KEY if you are downgrading because of a compromise.
    op.drop_column("users", "password_changed_at")
