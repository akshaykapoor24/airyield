"""Statements: remember the column mapping a vendor's statement was saved with

* statement_column_mappings — one row per (user, statement type, vendor, column layout):
  the file's columns and the {field: column} mapping the user saved the statement with,
  proposed again when that vendor's next file with that layout is read
  (models/statement_column_mapping.py, services/saved_mapping.py).

Nothing is backfilled: no mapping was kept before this, only the rows it produced.

Revision ID: stmt_mapping_01
Revises: tp_gds_std_01
Create Date: 2026-10-25 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'stmt_mapping_01'
down_revision: Union[str, None] = 'tp_gds_std_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_T = 'statement_column_mappings'


def upgrade() -> None:
    op.create_table(
        _T,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('slug', sa.String(40), nullable=False),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('suppliers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agency_id', sa.Integer(), sa.ForeignKey('agencies.id', ondelete='SET NULL'), nullable=True),
        sa.Column('vendor_name', sa.String(255), nullable=True),
        sa.Column('signature', sa.String(64), nullable=False),
        sa.Column('columns', postgresql.JSONB(), nullable=False),
        sa.Column('column_map', postgresql.JSONB(), nullable=False),
        sa.Column('source_file', sa.String(500), nullable=True),
        sa.Column('batch_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index(f'ix_{_T}_tenant_id', _T, ['tenant_id'])
    op.create_index(f'ix_{_T}_owner', _T, ['tenant_id', 'created_by_id', 'slug'])


def downgrade() -> None:
    op.drop_index(f'ix_{_T}_owner', table_name=_T)
    op.drop_index(f'ix_{_T}_tenant_id', table_name=_T)
    op.drop_table(_T)
