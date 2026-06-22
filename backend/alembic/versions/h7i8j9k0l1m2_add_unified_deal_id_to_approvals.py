"""add_unified_deal_id_to_deal_approvals

Revision ID: h7i8j9k0l1m2
Revises: g6h7i8j9k0l1
Create Date: 2026-06-15

Phase 4: Add a proper FK column unified_deal_id → deals.id alongside the legacy
polymorphic (deal_type, deal_id) pair.  When deal_type='unified', unified_deal_id
mirrors deal_id so queries can optionally join directly to deals without the
polymorphic union. Full cutover (drop deal_type + deal_id) happens after all legacy
deals are backfilled.
"""

from alembic import op
import sqlalchemy as sa


revision = 'h7i8j9k0l1m2'
down_revision = 'g6h7i8j9k0l1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable FK column
    op.add_column(
        "deal_approvals",
        sa.Column("unified_deal_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_deal_approvals_unified_deal_id",
        "deal_approvals",
        "deals",
        ["unified_deal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_deal_approvals_unified_deal_id",
        "deal_approvals",
        ["unified_deal_id"],
        unique=False,
    )

    # 2. Backfill: for any existing rows where deal_type='unified', copy deal_id
    op.execute(
        """
        UPDATE deal_approvals
        SET unified_deal_id = deal_id
        WHERE deal_type = 'unified'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_deal_approvals_unified_deal_id", table_name="deal_approvals")
    op.drop_constraint("fk_deal_approvals_unified_deal_id", "deal_approvals", type_="foreignkey")
    op.drop_column("deal_approvals", "unified_deal_id")
