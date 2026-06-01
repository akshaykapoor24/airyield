"""Add deal_batches table and batch_id to airline/b2b deals

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'r2s3t4u5v6w7'
down_revision: Union[str, None] = 'q1r2s3t4u5v6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'deal_batches',
        sa.Column('id',             sa.Integer(),    nullable=False),
        sa.Column('batch_id',       sa.String(100),  nullable=False),
        sa.Column('tenant_id',      sa.Integer(),    nullable=True),
        sa.Column('deal_type',      sa.String(50),   nullable=False),
        sa.Column('supplier_name',  sa.String(300),  nullable=True),
        sa.Column('file_name',      sa.String(500),  nullable=True),
        sa.Column('file_type',      sa.String(50),   nullable=True),
        sa.Column('incentive_types', sa.JSON(),       nullable=True),
        sa.Column('valid_from',     sa.Date(),       nullable=True),
        sa.Column('valid_to',       sa.Date(),       nullable=True),
        sa.Column('created_by_id',  sa.Integer(),    nullable=False),
        sa.Column('created_at',     sa.DateTime(),   nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_id'),
    )
    op.create_index('ix_deal_batches_batch_id',  'deal_batches', ['batch_id'])
    op.create_index('ix_deal_batches_tenant_id', 'deal_batches', ['tenant_id'])

    op.add_column('airline_deals', sa.Column('batch_id', sa.String(100), nullable=True))
    op.create_index('ix_airline_deals_batch_id', 'airline_deals', ['batch_id'])

    op.add_column('b2b_deals', sa.Column('batch_id', sa.String(100), nullable=True))
    op.create_index('ix_b2b_deals_batch_id', 'b2b_deals', ['batch_id'])


def downgrade() -> None:
    op.drop_index('ix_b2b_deals_batch_id', table_name='b2b_deals')
    op.drop_column('b2b_deals', 'batch_id')
    op.drop_index('ix_airline_deals_batch_id', table_name='airline_deals')
    op.drop_column('airline_deals', 'batch_id')
    op.drop_index('ix_deal_batches_tenant_id', table_name='deal_batches')
    op.drop_index('ix_deal_batches_batch_id',  table_name='deal_batches')
    op.drop_table('deal_batches')
