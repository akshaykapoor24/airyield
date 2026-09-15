"""Pax count on billing lines: a fixed markup is charged per passenger

An aggregator booking covers one or more passengers — MakeMyTrip ships a `Pax count` column
and TBO writes it onto the name ("GARIMA GUPTA X 6") — and a party's FIXED markup is agreed
per passenger. Billing charged it once per line regardless. Three columns:

  uploaded_tickets.pax_count      How many passengers this billing line covers. A fixed
                                  markup is multiplied by it (services/party_markup.line_markup);
                                  a percentage markup is not, because the base already covers
                                  every passenger.
  third_party_api.bill_pax_count  The pax this statement row will bill with — read from the file
                                  at resolve time, or corrected by hand on the worklist.
  third_party_api.bill_pax_source 'file' | 'default' | 'user'. A 'user' figure survives a
                                  Re-match, exactly as an overridden party does.

NOT NULL WITH server_default 1, AND THAT IS THE BACKFILL. Every existing line — LCC, NDC,
manual, and the API lines already sent — was billed as one passenger's worth of markup, so 1
reproduces exactly what they have always cost. Issued invoices are snapshots in
billings.line_items and are not touched either way.

Revision ID: tp_api_pax_01
Revises: tp_api_all_categories_01
Create Date: 2026-09-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'tp_api_pax_01'
down_revision: Union[str, None] = 'tp_api_all_categories_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'uploaded_tickets',
        sa.Column('pax_count', sa.SmallInteger(), nullable=False, server_default='1'),
    )
    op.add_column('third_party_api', sa.Column('bill_pax_count', sa.SmallInteger(), nullable=True))
    op.add_column('third_party_api', sa.Column('bill_pax_source', sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column('third_party_api', 'bill_pax_source')
    op.drop_column('third_party_api', 'bill_pax_count')
    op.drop_column('uploaded_tickets', 'pax_count')
