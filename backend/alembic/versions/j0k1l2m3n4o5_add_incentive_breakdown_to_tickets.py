"""add_incentive_breakdown_to_tickets

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-06-18

Adds a JSONB column to uploaded_tickets to store per-incentive-type calculated
amounts (e.g. {"PLB": 500.0, "Transaction Fee": 200.0}) produced by the updated
deal-matching service which now queries the unified deals table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uploaded_tickets",
        sa.Column("incentive_breakdown", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("uploaded_tickets", "incentive_breakdown")
