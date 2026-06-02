"""Add deal_tag to deals, airline_deals, b2b_deals, deal_batches

Revision ID: x1y2z3a4b5c6
Revises: w7x8y9z0a1b2
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'x1y2z3a4b5c6'
down_revision: Union[str, None] = 'w7x8y9z0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('deals', 'airline_deals', 'b2b_deals', 'deal_batches'):
        op.add_column(table, sa.Column(
            'deal_tag',
            sa.String(length=50),
            nullable=False,
            server_default='standard',
        ))


def downgrade() -> None:
    for table in ('deals', 'airline_deals', 'b2b_deals', 'deal_batches'):
        op.drop_column(table, 'deal_tag')
