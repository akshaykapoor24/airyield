"""users.verified_at / users.verified_by_id — when an account was verified, and by whom

Platform admin → Subscriptions can now verify a workspace owner's email by hand, which skips
the proof that they own the mailbox. The link path records only when; the manual path also
records which platform admin did it. See the comment on User.verified_at.

No backfill: accounts verified before this have no record of when, and saying "now" would
be inventing one.

Hand-written: autogenerate on this repo proposes ~240 unrelated drops.

Revision ID: user_verification_01
Revises: platform_invoice_01
Create Date: 2026-09-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "user_verification_01"
down_revision: Union[str, None] = "platform_invoice_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("verified_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_verified_by_id_users", "users", "users",
        ["verified_by_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_verified_by_id_users", "users", type_="foreignkey")
    op.drop_column("users", "verified_by_id")
    op.drop_column("users", "verified_at")
