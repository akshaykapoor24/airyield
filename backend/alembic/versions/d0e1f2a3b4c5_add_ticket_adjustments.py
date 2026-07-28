"""add ticket_adjustments (airline adjustments event log)

Phase 0 of the events-based ticket-ERP redesign. Additive table — one row per
ADM/ACM/Refund/RA/Debit Note/Credit Note event attached to a ticket. Does not
touch uploaded_tickets, upload, or matching.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ticket_adjustments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('uploaded_tickets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ticket_number', sa.String(length=100), nullable=True),
        sa.Column('type', sa.String(length=12), nullable=False),
        sa.Column('reference_no', sa.String(length=100), nullable=True),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('adjustment_date', sa.Date(), nullable=True),
        sa.Column('remarks', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='open'),
        sa.Column('source', sa.String(length=12), nullable=False, server_default='manual'),
        sa.Column('uploaded_statement_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_ticket_adjustments_tenant_id', 'ticket_adjustments', ['tenant_id'])
    op.create_index('ix_ticket_adjustments_created_by_id', 'ticket_adjustments', ['created_by_id'])
    op.create_index('ix_ticket_adjustments_ticket_id', 'ticket_adjustments', ['ticket_id'])
    op.create_index('ix_ticket_adjustments_ticket_number', 'ticket_adjustments', ['ticket_number'])


def downgrade() -> None:
    op.drop_index('ix_ticket_adjustments_ticket_number', table_name='ticket_adjustments')
    op.drop_index('ix_ticket_adjustments_ticket_id', table_name='ticket_adjustments')
    op.drop_index('ix_ticket_adjustments_created_by_id', table_name='ticket_adjustments')
    op.drop_index('ix_ticket_adjustments_tenant_id', table_name='ticket_adjustments')
    op.drop_table('ticket_adjustments')
