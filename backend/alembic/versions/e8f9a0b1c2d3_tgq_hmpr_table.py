"""dedicated per-type statement table — replace generic statement_rows with tgq_hmpr

TGQ HMPR gets its own table (``tgq_hmpr``) so its data is easy to find, rather than a
shared ``statement_rows`` discriminated by slug. Same shape: provenance + ``data`` JSONB
(fixed columns) + ``taxes`` JSONB (folded Tax_TypeN/TaxN pairs, unlimited).

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-07-17 01:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_tgq_hmpr() -> None:
    op.create_table(
        'tgq_hmpr',
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
    op.create_index('ix_tgq_hmpr_tenant_id', 'tgq_hmpr', ['tenant_id'])
    op.create_index('ix_tgq_hmpr_created_by_id', 'tgq_hmpr', ['created_by_id'])
    op.create_index('ix_tgq_hmpr_batch_id', 'tgq_hmpr', ['batch_id'])
    op.create_index('ix_tgq_hmpr_uploaded_at', 'tgq_hmpr', ['uploaded_at'])


def _drop_statement_rows() -> None:
    for ix in (
        'ix_statement_rows_scope', 'ix_statement_rows_uploaded_at', 'ix_statement_rows_batch_id',
        'ix_statement_rows_statement_slug', 'ix_statement_rows_created_by_id', 'ix_statement_rows_tenant_id',
    ):
        op.drop_index(ix, table_name='statement_rows')
    op.drop_table('statement_rows')


def upgrade() -> None:
    _drop_statement_rows()
    _create_tgq_hmpr()


def downgrade() -> None:
    op.drop_index('ix_tgq_hmpr_uploaded_at', table_name='tgq_hmpr')
    op.drop_index('ix_tgq_hmpr_batch_id', table_name='tgq_hmpr')
    op.drop_index('ix_tgq_hmpr_created_by_id', table_name='tgq_hmpr')
    op.drop_index('ix_tgq_hmpr_tenant_id', table_name='tgq_hmpr')
    op.drop_table('tgq_hmpr')
    # recreate statement_rows (mirror of migration d7e8f9a0b1c2)
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
    op.create_index('ix_statement_rows_scope', 'statement_rows', ['tenant_id', 'statement_slug', 'batch_id'])
