"""generic spec-driven statement rows (TGQ HMPR, later NDC/LCC/GDS)

Creates ``statement_rows`` — one table for every spec-driven statement type,
discriminated by ``statement_slug``. Fixed columns live in ``data`` JSONB; the
repeating Tax_TypeN/TaxN pairs fold into the ``taxes`` JSONB array (unlimited taxes).

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-07-17 01:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'statement_rows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('statement_slug', sa.String(length=50), nullable=False),
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
    op.create_index('ix_statement_rows_tenant_id', 'statement_rows', ['tenant_id'])
    op.create_index('ix_statement_rows_created_by_id', 'statement_rows', ['created_by_id'])
    op.create_index('ix_statement_rows_statement_slug', 'statement_rows', ['statement_slug'])
    op.create_index('ix_statement_rows_batch_id', 'statement_rows', ['batch_id'])
    op.create_index('ix_statement_rows_uploaded_at', 'statement_rows', ['uploaded_at'])
    # Common access path: a type's uploads for a tenant/user.
    op.create_index('ix_statement_rows_scope', 'statement_rows', ['tenant_id', 'statement_slug', 'batch_id'])


def downgrade() -> None:
    op.drop_index('ix_statement_rows_scope', table_name='statement_rows')
    op.drop_index('ix_statement_rows_uploaded_at', table_name='statement_rows')
    op.drop_index('ix_statement_rows_batch_id', table_name='statement_rows')
    op.drop_index('ix_statement_rows_statement_slug', table_name='statement_rows')
    op.drop_index('ix_statement_rows_created_by_id', table_name='statement_rows')
    op.drop_index('ix_statement_rows_tenant_id', table_name='statement_rows')
    op.drop_table('statement_rows')
