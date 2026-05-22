"""Add deal_lifecycle_status to deals, airline_deals, b2b_deals

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'n8o9p0q1r2s3'
down_revision: Union[str, None] = 'm7n8o9p0q1r2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('deals', 'airline_deals', 'b2b_deals'):
        op.add_column(table, sa.Column(
            'deal_lifecycle_status',
            sa.String(length=10),
            nullable=False,
            server_default='draft',
        ))
        # Back-fill: already-approved deals become active; everything else stays draft
        op.execute(
            f"UPDATE {table} SET deal_lifecycle_status = 'active' WHERE status = 'approved'"
        )


def downgrade() -> None:
    for table in ('deals', 'airline_deals', 'b2b_deals'):
        op.drop_column(table, 'deal_lifecycle_status')
