"""LCC Detailed Statement — dedicated normalized table

Adds ``lcc_detailed``: provenance + ``data`` JSONB (canonical common fields) +
``taxes`` / ``segments`` / ``ssr`` JSONB arrays (folded, unlimited) + ``raw_data`` JSONB
(original row verbatim) + ``source_format`` (detected export format).

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-07-17 02:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a0b1c2d3e4f5'
down_revision: Union[str, None] = 'f9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lcc_detailed',
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
    op.create_index('ix_lcc_detailed_tenant_id', 'lcc_detailed', ['tenant_id'])
    op.create_index('ix_lcc_detailed_created_by_id', 'lcc_detailed', ['created_by_id'])
    op.create_index('ix_lcc_detailed_batch_id', 'lcc_detailed', ['batch_id'])
    op.create_index('ix_lcc_detailed_uploaded_at', 'lcc_detailed', ['uploaded_at'])


def downgrade() -> None:
    op.drop_index('ix_lcc_detailed_uploaded_at', table_name='lcc_detailed')
    op.drop_index('ix_lcc_detailed_batch_id', table_name='lcc_detailed')
    op.drop_index('ix_lcc_detailed_created_by_id', table_name='lcc_detailed')
    op.drop_index('ix_lcc_detailed_tenant_id', table_name='lcc_detailed')
    op.drop_table('lcc_detailed')
