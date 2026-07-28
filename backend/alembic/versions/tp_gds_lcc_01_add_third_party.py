"""Third Party GDS + LCC Statements — dedicated normalized tables

A consolidator/big agency sends the sub-agency a GDS or LCC statement of the bookings it
made through them. Adds ``third_party_gds`` and ``third_party_lcc`` (same normalized shape
as the lcc_* tables): provenance + ``data`` JSONB (canonical fields) + ``taxes``/``segments``
/``ssr`` JSONB (unused) + ``raw_data`` JSONB (original row) + ``source_format``.

Revision ID: tp_gds_lcc_01
Revises: lcc_flown_01
Create Date: 2026-07-17 04:35:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'tp_gds_lcc_01'
down_revision: Union[str, None] = 'lcc_flown_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('third_party_gds', 'third_party_lcc')


def _create(table: str) -> None:
    op.create_table(
        table,
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
    op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
    op.create_index(f'ix_{table}_created_by_id', table, ['created_by_id'])
    op.create_index(f'ix_{table}_batch_id', table, ['batch_id'])
    op.create_index(f'ix_{table}_uploaded_at', table, ['uploaded_at'])


def upgrade() -> None:
    for t in _TABLES:
        _create(t)


def downgrade() -> None:
    for t in _TABLES:
        op.drop_index(f'ix_{t}_uploaded_at', table_name=t)
        op.drop_index(f'ix_{t}_batch_id', table_name=t)
        op.drop_index(f'ix_{t}_created_by_id', table_name=t)
        op.drop_index(f'ix_{t}_tenant_id', table_name=t)
        op.drop_table(t)
