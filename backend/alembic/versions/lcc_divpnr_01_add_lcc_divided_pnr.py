"""LCC Divided PNR Statement — dedicated normalized table

Adds ``lcc_divided_pnr`` (same normalized shape as lcc_di / lcc_detailed):
provenance + ``data`` JSONB (canonical fields) + ``taxes``/``segments``/``ssr`` JSONB
(unused) + ``raw_data`` JSONB (original row) + ``source_format``.

Revision ID: lcc_divpnr_01
Revises: lcc_di_stmt_01
Create Date: 2026-07-17 03:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'lcc_divpnr_01'
down_revision: Union[str, None] = 'lcc_di_stmt_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lcc_divided_pnr',
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
    op.create_index('ix_lcc_divided_pnr_tenant_id', 'lcc_divided_pnr', ['tenant_id'])
    op.create_index('ix_lcc_divided_pnr_created_by_id', 'lcc_divided_pnr', ['created_by_id'])
    op.create_index('ix_lcc_divided_pnr_batch_id', 'lcc_divided_pnr', ['batch_id'])
    op.create_index('ix_lcc_divided_pnr_uploaded_at', 'lcc_divided_pnr', ['uploaded_at'])


def downgrade() -> None:
    op.drop_index('ix_lcc_divided_pnr_uploaded_at', table_name='lcc_divided_pnr')
    op.drop_index('ix_lcc_divided_pnr_batch_id', table_name='lcc_divided_pnr')
    op.drop_index('ix_lcc_divided_pnr_created_by_id', table_name='lcc_divided_pnr')
    op.drop_index('ix_lcc_divided_pnr_tenant_id', table_name='lcc_divided_pnr')
    op.drop_table('lcc_divided_pnr')
