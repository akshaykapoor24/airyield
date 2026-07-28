"""NDC statement — dedicated table (same shape as tgq_hmpr)

Adds the ``ndc`` table: provenance + ``data`` JSONB (fixed columns) + ``taxes`` JSONB
(folded Tax_TypeN/TaxN pairs, unlimited). Same airline-ticket shape as TGQ HMPR.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-07-17 02:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f9a0b1c2d3e4'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ndc',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.String(length=100), nullable=False),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('file_url', sa.String(length=1000), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('taxes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ndc_tenant_id', 'ndc', ['tenant_id'])
    op.create_index('ix_ndc_created_by_id', 'ndc', ['created_by_id'])
    op.create_index('ix_ndc_batch_id', 'ndc', ['batch_id'])
    op.create_index('ix_ndc_uploaded_at', 'ndc', ['uploaded_at'])


def downgrade() -> None:
    op.drop_index('ix_ndc_uploaded_at', table_name='ndc')
    op.drop_index('ix_ndc_batch_id', table_name='ndc')
    op.drop_index('ix_ndc_created_by_id', table_name='ndc')
    op.drop_index('ix_ndc_tenant_id', table_name='ndc')
    op.drop_table('ndc')
