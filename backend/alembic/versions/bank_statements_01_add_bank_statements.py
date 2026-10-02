"""Bank statements and their lines (Accounting → Bank Statement)

The tenant's own bank statement, uploaded as the bank's Excel export: one
`bank_statements` row per file, one `bank_statement_rows` row per transaction. A deposit
linked to a corporate, employee or agency is money received from them; see
models/bank_statement.py for the dedupe key and the agency-ledger rule.

Revision ID: bank_statements_01
Revises: customer_codes_01
Create Date: 2026-09-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bank_statements_01'
down_revision: Union[str, None] = 'customer_codes_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bank_statements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('account_name', sa.String(length=255), nullable=True),
        sa.Column('account_no', sa.String(length=50), nullable=True),
        sa.Column('ifsc', sa.String(length=20), nullable=True),
        sa.Column('branch', sa.String(length=255), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('period_from', sa.Date(), nullable=True),
        sa.Column('period_to', sa.Date(), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duplicate_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_deposits', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('total_withdrawals', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_bank_statements_tenant_id', 'bank_statements', ['tenant_id'])
    op.create_index('ix_bank_statements_created_by_id', 'bank_statements', ['created_by_id'])

    op.create_table(
        'bank_statement_rows',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('statement_id', sa.Integer(), sa.ForeignKey('bank_statements.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=True),
        sa.Column('tran_id', sa.String(length=50), nullable=True),
        sa.Column('value_date', sa.Date(), nullable=True),
        sa.Column('txn_date', sa.Date(), nullable=True),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('cheque_ref', sa.String(length=100), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=False, server_default=''),
        sa.Column('withdrawal', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('deposit', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('balance', sa.Numeric(14, 2), nullable=True),
        sa.Column('direction', sa.String(length=3), nullable=False),
        sa.Column('counterparty', sa.String(length=255), nullable=True),
        sa.Column('payment_mode', sa.String(length=20), nullable=True),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('party_type', sa.String(length=12), nullable=True),
        sa.Column('corporate_id', sa.Integer(), sa.ForeignKey('corporates.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agency_id', sa.Integer(), sa.ForeignKey('agencies.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agency_ledger_id', sa.Integer(), sa.ForeignKey('agency_ledger.id', ondelete='SET NULL'), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('linked_at', sa.DateTime(), nullable=True),
    )
    for col in ('statement_id', 'tenant_id', 'created_by_id', 'txn_date', 'corporate_id', 'customer_id', 'agency_id'):
        op.create_index(f'ix_bank_statement_rows_{col}', 'bank_statement_rows', [col])
    op.create_index('uq_bank_statement_rows_dedupe', 'bank_statement_rows', ['created_by_id', 'dedupe_key'], unique=True)


def downgrade() -> None:
    op.drop_table('bank_statement_rows')
    op.drop_table('bank_statements')
