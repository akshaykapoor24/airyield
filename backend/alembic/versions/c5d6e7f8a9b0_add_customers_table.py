"""Add customers table

Revision ID: c5d6e7f8a9b0
Revises: k1l2m3n4o5p6
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'customers',
        sa.Column('id',            sa.Integer(),      nullable=False),
        sa.Column('tenant_id',     sa.Integer(),      nullable=True),
        sa.Column('created_by_id', sa.Integer(),      nullable=False),
        sa.Column('first_name',    sa.String(200),    nullable=False),
        sa.Column('last_name',     sa.String(200),    nullable=True),
        sa.Column('company',       sa.String(255),    nullable=True),
        sa.Column('title',         sa.String(100),    nullable=True),
        sa.Column('phone',         sa.String(50),     nullable=True),
        sa.Column('email',         sa.String(255),    nullable=True),
        sa.Column('gst_no',        sa.String(30),     nullable=True),
        sa.Column('markup_type',   sa.String(20),     nullable=True),
        sa.Column('markup_value',  sa.Numeric(14, 2), nullable=True),
        sa.Column('billing_type',  sa.String(20),     nullable=True),
        sa.Column('is_active',     sa.Boolean(),      nullable=True),
        sa.Column('created_at',    sa.DateTime(),     nullable=True),
        sa.Column('updated_at',    sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_customers_tenant_id', 'customers', ['tenant_id'])
    op.create_index('ix_customers_created_by_id', 'customers', ['created_by_id'])


def downgrade() -> None:
    op.drop_index('ix_customers_created_by_id', table_name='customers')
    op.drop_index('ix_customers_tenant_id', table_name='customers')
    op.drop_table('customers')
