"""add ticket_reconciliation (BSP expected-vs-actual engine output)

One row per reconciled unit comparing an internal UploadedTicket (EXPECTED)
against its matched BSP settlement row (ACTUAL). Additive — touches nothing else.

Revision ID: recon0bsp0001
Revises: f3a4b5c6d7e8
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'recon0bsp0001'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Headline field pairs stored as explicit columns for summary/sorting.
_FIELDS = ["fare", "yq", "yr", "tax", "transaction", "commission", "balance"]


def upgrade() -> None:
    cols = [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('run_id', sa.String(100), nullable=False),
        sa.Column('statement_id', sa.String(100), nullable=True),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('uploaded_tickets.id', ondelete='CASCADE'), nullable=True),
        sa.Column('bsp_row_id', sa.Integer(), sa.ForeignKey('bsp_statement_rows.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ticket_number', sa.String(100), nullable=True),
        sa.Column('airline_name', sa.String(200), nullable=True),
        sa.Column('airline_code', sa.String(20), nullable=True),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('txn_type', sa.String(12), nullable=True),
        sa.Column('pax_name', sa.String(300), nullable=True),
        sa.Column('match_status', sa.String(16), nullable=False),
        sa.Column('severity', sa.String(10), nullable=False),
        sa.Column('match_method', sa.String(16), nullable=False, server_default='none'),
    ]
    for f in _FIELDS:
        cols += [
            sa.Column(f'expected_{f}', sa.Numeric(14, 2), nullable=True),
            sa.Column(f'actual_{f}', sa.Numeric(14, 2), nullable=True),
            sa.Column(f'{f}_variance', sa.Numeric(14, 2), nullable=True),
            sa.Column(f'{f}_match', sa.Boolean(), nullable=True),
        ]
    cols += [
        sa.Column('commission_source', sa.String(12), nullable=True),
        sa.Column('net_variance', sa.Numeric(14, 2), nullable=True),
        sa.Column('abs_variance', sa.Numeric(14, 2), nullable=True),
        sa.Column('field_diffs', postgresql.JSONB(), nullable=True),
        sa.Column('issues', postgresql.JSONB(), nullable=True),
        sa.Column('related_bsp', postgresql.JSONB(), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('reconciled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    ]
    op.create_table('ticket_reconciliation', *cols)

    for col in ('tenant_id', 'created_by_id', 'run_id', 'statement_id',
                'ticket_id', 'bsp_row_id', 'ticket_number', 'issue_date',
                'txn_type', 'match_status', 'severity', 'reconciled_at'):
        op.create_index(f'ix_ticket_reconciliation_{col}', 'ticket_reconciliation', [col])
    op.create_index('ix_ticket_reconciliation_scope', 'ticket_reconciliation', ['tenant_id', 'created_by_id'])
    op.create_index('ix_ticket_reconciliation_scope_status', 'ticket_reconciliation', ['tenant_id', 'created_by_id', 'match_status'])


def downgrade() -> None:
    op.drop_table('ticket_reconciliation')   # indexes drop with the table
