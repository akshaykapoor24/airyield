"""Add deal_category to airline_deals and b2b_deals

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'y2z3a4b5c6d7'
down_revision: Union[str, None] = 'x1y2z3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('airline_deals', 'b2b_deals'):
        op.add_column(table, sa.Column(
            'deal_category',
            sa.String(length=50),
            nullable=False,
            server_default='enterprise',
        ))


def downgrade() -> None:
    for table in ('airline_deals', 'b2b_deals'):
        op.drop_column(table, 'deal_category')
