"""add bsp_statements + bsp_statement_rows

Phase 1 of the ticket-ERP redesign. BSP settlement statements as a separate
document set that references uploaded_tickets (not a ticket itself). Additive —
does not touch uploaded_tickets, upload, or matching.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bsp_statements',
        sa.Column('batch_id', sa.String(length=100), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('statement_name', sa.String(length=500), nullable=True),
        sa.Column('airline_code', sa.String(length=20), nullable=True),
        sa.Column('airline_name', sa.String(length=200), nullable=True),
        sa.Column('period_from', sa.Date(), nullable=True),
        sa.Column('period_to', sa.Date(), nullable=True),
        sa.Column('file_name', sa.String(length=500), nullable=True),
        sa.Column('file_url', sa.String(length=1000), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_bsp_statements_tenant_id', 'bsp_statements', ['tenant_id'])
    op.create_index('ix_bsp_statements_created_by_id', 'bsp_statements', ['created_by_id'])

    op.create_table(
        'bsp_statement_rows',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('statement_id', sa.String(length=100), sa.ForeignKey('bsp_statements.batch_id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ticket_number', sa.String(length=100), nullable=True),
        sa.Column('airline_code', sa.String(length=20), nullable=True),
        sa.Column('gross', sa.Numeric(14, 2), nullable=True),
        sa.Column('commission', sa.Numeric(14, 2), nullable=True),
        sa.Column('adm', sa.Numeric(14, 2), nullable=True),
        sa.Column('acm', sa.Numeric(14, 2), nullable=True),
        sa.Column('refund', sa.Numeric(14, 2), nullable=True),
        sa.Column('net_due', sa.Numeric(14, 2), nullable=True),
        sa.Column('transaction_type', sa.String(length=10), nullable=True),
        sa.Column('matched_ticket_id', sa.Integer(), sa.ForeignKey('uploaded_tickets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('match_status', sa.String(length=12), nullable=False, server_default='unmatched'),
        sa.Column('raw_data', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_bsp_statement_rows_statement_id', 'bsp_statement_rows', ['statement_id'])
    op.create_index('ix_bsp_statement_rows_tenant_id', 'bsp_statement_rows', ['tenant_id'])
    op.create_index('ix_bsp_statement_rows_created_by_id', 'bsp_statement_rows', ['created_by_id'])
    op.create_index('ix_bsp_statement_rows_ticket_number', 'bsp_statement_rows', ['ticket_number'])
    op.create_index('ix_bsp_statement_rows_matched_ticket_id', 'bsp_statement_rows', ['matched_ticket_id'])


def downgrade() -> None:
    op.drop_table('bsp_statement_rows')
    op.drop_table('bsp_statements')
