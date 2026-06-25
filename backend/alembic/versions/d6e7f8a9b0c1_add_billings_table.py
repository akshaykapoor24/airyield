"""Add billings table

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'billings',
        sa.Column('id',                      sa.Integer(),      nullable=False),
        sa.Column('tenant_id',               sa.Integer(),      nullable=True),
        sa.Column('created_by_id',           sa.Integer(),      nullable=False),
        sa.Column('customer_id',             sa.Integer(),      nullable=False),
        sa.Column('billing_name',            sa.String(200),    nullable=False),
        sa.Column('period_from',             sa.Date(),         nullable=False),
        sa.Column('period_to',               sa.Date(),         nullable=False),
        sa.Column('billing_type',            sa.String(20),     nullable=True),
        sa.Column('total_base',              sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('total_markup',            sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('total_additional_markup', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('total_gst',               sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('grand_total',             sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('line_items',              postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at',              sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['customer_id'],   ['customers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_billings_tenant_id', 'billings', ['tenant_id'])
    op.create_index('ix_billings_created_by_id', 'billings', ['created_by_id'])
    op.create_index('ix_billings_customer_id', 'billings', ['customer_id'])


def downgrade() -> None:
    op.drop_index('ix_billings_customer_id', table_name='billings')
    op.drop_index('ix_billings_created_by_id', table_name='billings')
    op.drop_index('ix_billings_tenant_id', table_name='billings')
    op.drop_table('billings')
