"""Customer Statements — dedicated B2B statement repo (separate tables)

A customer statement is the B2B statement an agency issues for a sub-agency it onboards
in the Customer Directory. Adds ``customer_statements`` (batch metadata + directory
selection snapshots) and ``customer_statement_tickets`` (the parsed rows, B2B column
subset of ``uploaded_tickets``). Deliberately separate from the internal ``ticket_statements``
/ ``uploaded_tickets`` tables.

Revision ID: cust_stmt_01
Revises: tp_gds_lcc_01
Create Date: 2026-07-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'cust_stmt_01'
down_revision: Union[str, None] = 'tp_gds_lcc_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── customer_statements (batch metadata) ─────────────────────────────────
    op.create_table(
        'customer_statements',
        sa.Column('batch_id', sa.String(length=100), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('statement_type', sa.String(length=10), nullable=False, server_default='B2B'),
        sa.Column('statement_name', sa.String(length=500), nullable=True),
        sa.Column('agency', sa.String(length=200), nullable=False),
        sa.Column('agency_id', sa.Integer(), nullable=True),
        sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('login_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.Column('valid_to', sa.Date(), nullable=False),
        sa.Column('file_name', sa.String(length=500), nullable=False),
        sa.Column('file_url', sa.String(length=1000), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('batch_id'),
    )
    op.create_index('ix_customer_statements_tenant_id', 'customer_statements', ['tenant_id'])

    # ── customer_statement_tickets (parsed rows, B2B subset) ─────────────────
    op.create_table(
        'customer_statement_tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.String(length=100), nullable=False),
        sa.Column('file_name', sa.String(length=500), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('statement_type', sa.String(length=10), nullable=True),
        sa.Column('booking_ref', sa.String(length=100), nullable=True),
        sa.Column('segment_type', sa.String(length=50), nullable=True),
        sa.Column('invoice_type', sa.String(length=50), nullable=True),
        sa.Column('invoice_no', sa.String(length=100), nullable=True),
        sa.Column('ticket_date', sa.String(length=50), nullable=True),
        sa.Column('last_name', sa.String(length=200), nullable=True),
        sa.Column('first_name', sa.String(length=200), nullable=True),
        sa.Column('sector', sa.String(length=200), nullable=True),
        sa.Column('booking_class', sa.String(length=20), nullable=True),
        sa.Column('departure_datetime', sa.String(length=100), nullable=True),
        sa.Column('gds_pnr', sa.String(length=50), nullable=True),
        sa.Column('airlines_code', sa.String(length=20), nullable=True),
        sa.Column('ticket_number', sa.String(length=50), nullable=True),
        sa.Column('sell_fare', sa.Numeric(14, 2), nullable=True),
        sa.Column('sell_tax', sa.Numeric(14, 2), nullable=True),
        sa.Column('sell_tax_yq', sa.Numeric(14, 2), nullable=True),
        sa.Column('sale_yr', sa.Numeric(14, 2), nullable=True),
        sa.Column('sale_k3', sa.Numeric(14, 2), nullable=True),
        sa.Column('rei_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('seat_selection', sa.Numeric(14, 2), nullable=True),
        sa.Column('excess_baggage', sa.Numeric(14, 2), nullable=True),
        sa.Column('meals', sa.Numeric(14, 2), nullable=True),
        sa.Column('rfd_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('can_charge', sa.Numeric(14, 2), nullable=True),
        sa.Column('booking_fee_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('cgst_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('sgst_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('igst_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('comm_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('adm', sa.Numeric(14, 2), nullable=True),
        sa.Column('incentive_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('dis_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('tds_sell', sa.Numeric(14, 2), nullable=True),
        sa.Column('total_amt', sa.Numeric(14, 2), nullable=True),
        sa.Column('paid_by_credit_card', sa.Numeric(14, 2), nullable=True),
        sa.Column('net_amt', sa.Numeric(14, 2), nullable=True),
        sa.Column('cc', sa.String(length=20), nullable=True),
        sa.Column('acc_code', sa.String(length=100), nullable=True),
        sa.Column('sold_to', sa.String(length=20), nullable=True),
        sa.Column('customer_name', sa.String(length=300), nullable=True),
        sa.Column('tour_code', sa.String(length=100), nullable=True),
        sa.Column('tax_breakup', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('segments', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('airline_name', sa.String(length=200), nullable=True),
        sa.Column('ticket_status', sa.String(length=10), nullable=False, server_default='draft'),
        sa.Column('split_type', sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_customer_statement_tickets_tenant_id', 'customer_statement_tickets', ['tenant_id'])
    op.create_index('ix_customer_statement_tickets_batch_id', 'customer_statement_tickets', ['batch_id'])


def downgrade() -> None:
    op.drop_index('ix_customer_statement_tickets_batch_id', table_name='customer_statement_tickets')
    op.drop_index('ix_customer_statement_tickets_tenant_id', table_name='customer_statement_tickets')
    op.drop_table('customer_statement_tickets')
    op.drop_index('ix_customer_statements_tenant_id', table_name='customer_statements')
    op.drop_table('customer_statements')
