"""Third Party API Statements — the aggregator booking export table

An aggregator (MakeMyTrip, TBO) sends the agency one statement covering EVERY product it
booked — hotel, flight, train, bus and car on adjacent lines of the same sheet. Adds
``third_party_api`` in the same normalized shape as ``third_party_gds`` / ``third_party_lcc``:
provenance + ``data`` JSONB (canonical fields) + ``taxes``/``segments``/``ssr`` JSONB (unused)
+ ``raw_data`` JSONB (the original row) + ``source_format``.

ONE TABLE, NOT ONE PER PRODUCT. ``data`` is JSONB, so a train row simply carries no
``no_of_rooms`` key and pays nothing for the hotel fields it does not have — the usual reason
to split a wide sparse table does not apply here. Splitting would instead make this the only
place on this router where one uploaded batch is not one table's rows, turning every total,
filter, facet, export and delete into a five-way UNION. ``data->>'product_type'`` separates
the products, and it is a declared `select` filter so the drill-in can show one at a time.

``source_format`` carries the vendor (``mmt-bookings-v1`` / ``tbo-statement-v1``), detected
from the header row — the same use ``lcc_di`` already makes of it for its two deposit formats.

Revision ID: tp_api_01
Revises: lcc_ix_merge_01
Create Date: 2026-09-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'tp_api_01'
down_revision: Union[str, None] = 'lcc_ix_merge_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'third_party_api'


def upgrade() -> None:
    op.create_table(
        _TABLE,
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
    op.create_index(f'ix_{_TABLE}_tenant_id', _TABLE, ['tenant_id'])
    op.create_index(f'ix_{_TABLE}_created_by_id', _TABLE, ['created_by_id'])
    op.create_index(f'ix_{_TABLE}_batch_id', _TABLE, ['batch_id'])
    op.create_index(f'ix_{_TABLE}_uploaded_at', _TABLE, ['uploaded_at'])


def downgrade() -> None:
    op.drop_index(f'ix_{_TABLE}_uploaded_at', table_name=_TABLE)
    op.drop_index(f'ix_{_TABLE}_batch_id', table_name=_TABLE)
    op.drop_index(f'ix_{_TABLE}_created_by_id', table_name=_TABLE)
    op.drop_index(f'ix_{_TABLE}_tenant_id', table_name=_TABLE)
    op.drop_table(_TABLE)
