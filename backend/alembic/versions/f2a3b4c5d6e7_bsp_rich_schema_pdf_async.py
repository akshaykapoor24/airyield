"""enrich bsp rows, add async status/progress, tax breakups + parse errors

Phase 1 of BSP PDF ingestion. BSP settlement statements now arrive as large PDFs
(1000-2000 pages) parsed asynchronously by a Celery worker, so:

  * bsp_statements gains async processing state: status + total/processed page and
    row counters + an error message. The frontend polls these for a progress bar.
  * bsp_statement_rows gains the full BSP transaction column set (document number,
    accounting code, issue date, cpui, nr code, stat, form of payment, and the
    settlement financials). The legacy gross/adm/acm/refund/net_due columns from
    the Excel path are kept (nullable) and dropped in a later migration.
  * bsp_tax_breakups (NEW) stores each fare component as a row — a generic model so
    a new airline tax/fee code never needs a schema change.
  * bsp_parse_errors (NEW) captures per-page parse failures so one bad page never
    fails the whole statement.

Additive and reversible. Safe to apply whether or not e1f2a3b4c5d6 already ran.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── bsp_statements: async processing state ──────────────────────────────
    op.add_column('bsp_statements', sa.Column('status', sa.String(length=12), nullable=False, server_default='pending'))
    op.add_column('bsp_statements', sa.Column('total_pages', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('bsp_statements', sa.Column('processed_pages', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('bsp_statements', sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('bsp_statements', sa.Column('processed_rows', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('bsp_statements', sa.Column('error', sa.Text(), nullable=True))
    op.create_index('ix_bsp_statements_status', 'bsp_statements', ['status'])

    # ── bsp_statement_rows: rich BSP transaction columns ────────────────────
    op.add_column('bsp_statement_rows', sa.Column('document_number', sa.String(length=100), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('airline_accounting_code', sa.String(length=10), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('issue_date', sa.Date(), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('cpui', sa.String(length=20), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('nr_code', sa.String(length=20), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('stat', sa.String(length=4), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('form_of_payment', sa.String(length=20), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('transaction_amount', sa.Numeric(14, 2), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('fare_amount', sa.Numeric(14, 2), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('penalty_amount', sa.Numeric(14, 2), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('net_sales', sa.Numeric(14, 2), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('standard_commission_rate', sa.Numeric(8, 4), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('standard_commission_amount', sa.Numeric(14, 2), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('supplier_discount_rate', sa.Numeric(8, 4), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('supplier_discount_amount', sa.Numeric(14, 2), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('tax_on_commission', sa.Numeric(14, 2), nullable=True))
    op.add_column('bsp_statement_rows', sa.Column('balance_payable', sa.Numeric(14, 2), nullable=True))

    # ── bsp_tax_breakups: one fare component per row ────────────────────────
    op.create_table(
        'bsp_tax_breakups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bsp_row_id', sa.Integer(), sa.ForeignKey('bsp_statement_rows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('component_type', sa.String(length=20), nullable=True),
        sa.Column('component_code', sa.String(length=20), nullable=True),
        sa.Column('amount', sa.Numeric(14, 2), nullable=True),
    )
    op.create_index('ix_bsp_tax_breakups_bsp_row_id', 'bsp_tax_breakups', ['bsp_row_id'])
    op.create_index('ix_bsp_tax_breakups_tenant_id', 'bsp_tax_breakups', ['tenant_id'])

    # ── bsp_parse_errors: per-page failures ─────────────────────────────────
    op.create_table(
        'bsp_parse_errors',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('statement_id', sa.String(length=100), sa.ForeignKey('bsp_statements.batch_id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('raw_snippet', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_bsp_parse_errors_statement_id', 'bsp_parse_errors', ['statement_id'])


def downgrade() -> None:
    op.drop_table('bsp_parse_errors')
    op.drop_index('ix_bsp_tax_breakups_tenant_id', table_name='bsp_tax_breakups')
    op.drop_index('ix_bsp_tax_breakups_bsp_row_id', table_name='bsp_tax_breakups')
    op.drop_table('bsp_tax_breakups')

    for col in (
        'balance_payable', 'tax_on_commission', 'supplier_discount_amount', 'supplier_discount_rate',
        'standard_commission_amount', 'standard_commission_rate', 'net_sales', 'penalty_amount',
        'fare_amount', 'transaction_amount', 'form_of_payment', 'stat', 'nr_code', 'cpui',
        'issue_date', 'airline_accounting_code', 'document_number',
    ):
        op.drop_column('bsp_statement_rows', col)

    op.drop_index('ix_bsp_statements_status', table_name='bsp_statements')
    for col in ('error', 'processed_rows', 'total_rows', 'processed_pages', 'total_pages', 'status'):
        op.drop_column('bsp_statements', col)
