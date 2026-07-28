"""LCC DI (Deposit) Statement — dedicated normalized table

Adds ``lcc_di`` (same normalized shape as lcc_detailed): provenance + ``data`` JSONB
(canonical fields) + ``taxes``/``segments``/``ssr`` JSONB (unused for DI) + ``raw_data``
JSONB (original row) + ``source_format`` (deposit-ledger | agency-ledger).

Revision ID: lcc_di_stmt_01
Revises: a0b1c2d3e4f5
Create Date: 2026-07-17 03:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'lcc_di_stmt_01'
down_revision: Union[str, None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lcc_di',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.String(length=100), nullable=False),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('file_url', sa.String(length=1000), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('taxes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source_format', sa.String(length=40), nullable=True),
        sa.Column('segments', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ssr', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lcc_di_tenant_id', 'lcc_di', ['tenant_id'])
    op.create_index('ix_lcc_di_created_by_id', 'lcc_di', ['created_by_id'])
    op.create_index('ix_lcc_di_batch_id', 'lcc_di', ['batch_id'])
    op.create_index('ix_lcc_di_uploaded_at', 'lcc_di', ['uploaded_at'])


def downgrade() -> None:
    op.drop_index('ix_lcc_di_uploaded_at', table_name='lcc_di')
    op.drop_index('ix_lcc_di_batch_id', table_name='lcc_di')
    op.drop_index('ix_lcc_di_created_by_id', table_name='lcc_di')
    op.drop_index('ix_lcc_di_tenant_id', table_name='lcc_di')
    op.drop_table('lcc_di')
