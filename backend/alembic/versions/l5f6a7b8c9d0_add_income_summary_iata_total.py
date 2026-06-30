"""add income_summaries.iata_commission_total

Aggregated IATA commission saved with an income statement (sum of the
statement's tickets' iata_commission).

Revision ID: l5f6a7b8c9d0
Revises: k4e5f6a7b8c9
Create Date: 2026-06-28 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l5f6a7b8c9d0'
down_revision: Union[str, None] = 'k4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "income_summaries",
        sa.Column("iata_commission_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("income_summaries", "iata_commission_total")
