"""add_capped_incentive_amount

Revision ID: i9j0k1l2m3n4
Revises: h7i8j9k0l1m2
Create Date: 2026-06-16

The manual deal form's Fixed-path payout now sends two capped-incentive values
(percentage AND amount) for PLB/Super PLB/Transaction Fee/Marketing Fund/Frontend/
Backend/Push Action, but deal_incentives only had a single capped_incentive column,
silently dropping the amount variant. This adds the missing column.
"""

from alembic import op
import sqlalchemy as sa


revision = 'i9j0k1l2m3n4'
down_revision = 'h7i8j9k0l1m2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deal_incentives",
        sa.Column("capped_incentive_amount", sa.Numeric(18, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deal_incentives", "capped_incentive_amount")
