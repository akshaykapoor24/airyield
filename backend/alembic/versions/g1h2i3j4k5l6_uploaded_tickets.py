"""add uploaded_tickets table

Revision ID: g1h2i3j4k5l6
Revises: b1c2d3e4f5a6
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'uploaded_tickets',
        sa.Column('id',              sa.Integer(),     nullable=False),
        sa.Column('batch_id',        sa.String(100),   nullable=False),
        sa.Column('file_name',       sa.String(500),   nullable=False),
        sa.Column('tenant_id',       sa.Integer(),     nullable=False),
        sa.Column('created_by_id',   sa.Integer(),     nullable=False),
        sa.Column('created_at',      sa.DateTime(),    nullable=False),
        # Text columns
        sa.Column('booking_ref',         sa.String(100),  nullable=True),
        sa.Column('segment_type',        sa.String(50),   nullable=True),
        sa.Column('invoice_type',        sa.String(50),   nullable=True),
        sa.Column('invoice_no',          sa.String(100),  nullable=True),
        sa.Column('ticket_date',         sa.String(50),   nullable=True),
        sa.Column('last_name',           sa.String(200),  nullable=True),
        sa.Column('first_name',          sa.String(200),  nullable=True),
        sa.Column('sector',              sa.String(200),  nullable=True),
        sa.Column('booking_class',       sa.String(20),   nullable=True),
        sa.Column('departure_datetime',  sa.String(100),  nullable=True),
        sa.Column('gds_pnr',             sa.String(50),   nullable=True),
        sa.Column('airlines_code',       sa.String(20),   nullable=True),
        sa.Column('ticket_number',       sa.String(50),   nullable=True),
        sa.Column('cc',                  sa.String(20),   nullable=True),
        sa.Column('acc_code',            sa.String(100),  nullable=True),
        # Numeric columns
        sa.Column('sell_fare',           sa.Numeric(14, 2), nullable=True),
        sa.Column('sell_tax',            sa.Numeric(14, 2), nullable=True),
        sa.Column('sell_tax_yq',         sa.Numeric(14, 2), nullable=True),
        sa.Column('sale_yr',             sa.Numeric(14, 2), nullable=True),
        sa.Column('sale_k3',             sa.Numeric(14, 2), nullable=True),
        sa.Column('rei_sell',            sa.Numeric(14, 2), nullable=True),
        sa.Column('seat_selection',      sa.Numeric(14, 2), nullable=True),
        sa.Column('excess_baggage',      sa.Numeric(14, 2), nullable=True),
        sa.Column('meals',               sa.Numeric(14, 2), nullable=True),
        sa.Column('rfd_sell',            sa.Numeric(14, 2), nullable=True),
        sa.Column('can_charge',          sa.Numeric(14, 2), nullable=True),
        sa.Column('booking_fee_sell',    sa.Numeric(14, 2), nullable=True),
        sa.Column('cgst_sell',           sa.Numeric(14, 2), nullable=True),
        sa.Column('sgst_sell',           sa.Numeric(14, 2), nullable=True),
        sa.Column('igst_sell',           sa.Numeric(14, 2), nullable=True),
        sa.Column('comm_sell',           sa.Numeric(14, 2), nullable=True),
        sa.Column('adm',                 sa.Numeric(14, 2), nullable=True),
        sa.Column('incentive_sell',      sa.Numeric(14, 2), nullable=True),
        sa.Column('dis_sell',            sa.Numeric(14, 2), nullable=True),
        sa.Column('tds_sell',            sa.Numeric(14, 2), nullable=True),
        sa.Column('total_amt',           sa.Numeric(14, 2), nullable=True),
        sa.Column('paid_by_credit_card', sa.Numeric(14, 2), nullable=True),
        sa.Column('net_amt',             sa.Numeric(14, 2), nullable=True),
        # Constraints
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'],  ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_uploaded_tickets_batch_id',  'uploaded_tickets', ['batch_id'])
    op.create_index('ix_uploaded_tickets_tenant_id', 'uploaded_tickets', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_uploaded_tickets_tenant_id', table_name='uploaded_tickets')
    op.drop_index('ix_uploaded_tickets_batch_id',  table_name='uploaded_tickets')
    op.drop_table('uploaded_tickets')
