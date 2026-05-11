"""Add matched_deal_type and calculated_incentive to uploaded_tickets

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'l6m7n8o9p0q1'
down_revision: Union[str, None] = 'k5l6m7n8o9p0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('uploaded_tickets', sa.Column('matched_deal_type',   sa.String(20),     nullable=True))
    op.add_column('uploaded_tickets', sa.Column('calculated_incentive', sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('uploaded_tickets', 'calculated_incentive')
    op.drop_column('uploaded_tickets', 'matched_deal_type')
