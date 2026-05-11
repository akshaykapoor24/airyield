"""add airline_name and deal matching columns to uploaded_tickets

Revision ID: i3j4k5l6m7n8
Revises: g1h2i3j4k5l6
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'i3j4k5l6m7n8'
down_revision: Union[str, None] = 'h2i3j4k5l6m7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('uploaded_tickets', sa.Column('airline_name',      sa.String(200), nullable=True))
    op.add_column('uploaded_tickets', sa.Column('matched_deal_id',   sa.Integer(),   nullable=True))
    op.add_column('uploaded_tickets', sa.Column('matched_deal_name', sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column('uploaded_tickets', 'matched_deal_name')
    op.drop_column('uploaded_tickets', 'matched_deal_id')
    op.drop_column('uploaded_tickets', 'airline_name')
