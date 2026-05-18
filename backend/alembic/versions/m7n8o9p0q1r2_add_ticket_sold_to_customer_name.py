"""Add sold_to and customer_name to uploaded_tickets

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'm7n8o9p0q1r2'
down_revision: Union[str, None] = 'l6m7n8o9p0q1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('uploaded_tickets', sa.Column('sold_to',       sa.String(20),  nullable=True))
    op.add_column('uploaded_tickets', sa.Column('customer_name', sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column('uploaded_tickets', 'customer_name')
    op.drop_column('uploaded_tickets', 'sold_to')
