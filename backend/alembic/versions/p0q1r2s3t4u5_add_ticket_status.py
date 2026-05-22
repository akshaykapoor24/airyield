"""Add ticket_status to uploaded_tickets

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'p0q1r2s3t4u5'
down_revision: Union[str, None] = 'o9p0q1r2s3t4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'uploaded_tickets',
        sa.Column('ticket_status', sa.String(length=10), nullable=False, server_default='draft'),
    )
    # Backfill: tickets that already have a matched deal were previously calculated
    op.execute(
        "UPDATE uploaded_tickets SET ticket_status = 'calculated' WHERE matched_deal_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column('uploaded_tickets', 'ticket_status')
