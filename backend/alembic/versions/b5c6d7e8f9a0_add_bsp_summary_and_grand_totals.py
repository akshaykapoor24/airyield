"""add bsp summary statements/rows + summary↔detailed pairing & grand totals

Adds the **BSP Summary** (IATA FCAGBILLSUMNG "Agent Billing Summary") side of a BSP
statement and the reconciliation between the summary and its detailed counterpart:

  * bsp_statements gains ``group_id`` (links a detailed statement to its summary) and
    the printed grand-total columns (gt_*), accumulated while parsing so the summary
    can be reconciled line-by-line without re-reading the PDF.
  * bsp_summary_statements (NEW) — the summary header (agent/period from the PDF),
    its printed grand totals, and the reconciliation result (match_status/detail).
  * bsp_summary_rows (NEW) — the per-airline × category breakdown from the summary.

Additive and reversible.

Revision ID: b5c6d7e8f9a0
Revises: recon0bsp0001
Create Date: 2026-07-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, None] = 'recon0bsp0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GT = [
    'gt_issues', 'gt_refunds', 'gt_debit_memos', 'gt_credit_memos',
    'gt_std_comm', 'gt_sup_comm', 'gt_tax_on_comm', 'gt_balance_payable',
]


def upgrade() -> None:
    # ── bsp_statements: pairing + printed grand totals ──────────────────────
    op.add_column('bsp_statements', sa.Column('group_id', sa.String(length=100), nullable=True))
    op.create_index('ix_bsp_statements_group_id', 'bsp_statements', ['group_id'])
    for c in _GT:
        op.add_column('bsp_statements', sa.Column(c, sa.Numeric(16, 2), nullable=True))
    op.add_column('bsp_statements', sa.Column('gt_doc_count', sa.Integer(), nullable=True))

    # ── bsp_summary_statements ──────────────────────────────────────────────
    op.create_table(
        'bsp_summary_statements',
        sa.Column('batch_id', sa.String(length=100), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('group_id', sa.String(length=100), nullable=False),
        sa.Column('agent_code', sa.String(length=40), nullable=True),
        sa.Column('agent_name', sa.String(length=300), nullable=True),
        sa.Column('reference', sa.String(length=60), nullable=True),
        sa.Column('billing_period_code', sa.String(length=12), nullable=True),
        sa.Column('period_from', sa.Date(), nullable=True),
        sa.Column('period_to', sa.Date(), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('file_name', sa.String(length=500), nullable=True),
        sa.Column('file_url', sa.String(length=1000), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='pending'),
        sa.Column('total_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        *[sa.Column(c, sa.Numeric(16, 2), nullable=True) for c in _GT],
        sa.Column('gt_doc_count', sa.Integer(), nullable=True),
        sa.Column('match_status', sa.String(length=12), nullable=False, server_default='pending'),
        sa.Column('matched_at', sa.DateTime(), nullable=True),
        sa.Column('match_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_bsp_summary_statements_tenant_id', 'bsp_summary_statements', ['tenant_id'])
    op.create_index('ix_bsp_summary_statements_created_by_id', 'bsp_summary_statements', ['created_by_id'])
    op.create_index('ix_bsp_summary_statements_group_id', 'bsp_summary_statements', ['group_id'])
    op.create_index('ix_bsp_summary_statements_status', 'bsp_summary_statements', ['status'])

    # ── bsp_summary_rows ────────────────────────────────────────────────────
    op.create_table(
        'bsp_summary_rows',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('summary_id', sa.String(length=100), sa.ForeignKey('bsp_summary_statements.batch_id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=True),
        sa.Column('airline_code', sa.String(length=10), nullable=True),
        sa.Column('airline_iata', sa.String(length=10), nullable=True),
        sa.Column('airline_name', sa.String(length=200), nullable=True),
        sa.Column('fop', sa.String(length=10), nullable=True),
        sa.Column('issues', sa.Numeric(16, 2), nullable=True),
        sa.Column('refunds', sa.Numeric(16, 2), nullable=True),
        sa.Column('debit_memos', sa.Numeric(16, 2), nullable=True),
        sa.Column('credit_memos', sa.Numeric(16, 2), nullable=True),
        sa.Column('std_comm', sa.Numeric(16, 2), nullable=True),
        sa.Column('sup_comm', sa.Numeric(16, 2), nullable=True),
        sa.Column('tax_on_comm', sa.Numeric(16, 2), nullable=True),
        sa.Column('balance_payable', sa.Numeric(16, 2), nullable=True),
        sa.Column('doc_count', sa.Integer(), nullable=True),
    )
    op.create_index('ix_bsp_summary_rows_summary_id', 'bsp_summary_rows', ['summary_id'])
    op.create_index('ix_bsp_summary_rows_tenant_id', 'bsp_summary_rows', ['tenant_id'])
    op.create_index('ix_bsp_summary_rows_created_by_id', 'bsp_summary_rows', ['created_by_id'])


def downgrade() -> None:
    op.drop_table('bsp_summary_rows')
    op.drop_table('bsp_summary_statements')
    op.drop_index('ix_bsp_statements_group_id', table_name='bsp_statements')
    op.drop_column('bsp_statements', 'gt_doc_count')
    for c in _GT:
        op.drop_column('bsp_statements', c)
    op.drop_column('bsp_statements', 'group_id')
