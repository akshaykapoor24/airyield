"""Third Party GDS: SSR and GST in parts, ADM, Discount, UATP and Card Type

The standard Third Party GDS columns (services/flat_statement.py `_TP_GDS_COLUMNS`) gain
what consolidators print beyond the first set — Brightsun's statement prints every one:

* seat_selection, excess_baggage, meals — the SSR, in parts. SSR Amount stays the total
  and is added up from them when the file does not print it (`ssr_source` = "derived").
* cgst, sgst, igst — GST on the service fee, in parts. GST On SF stays the total, added up
  likewise (`gst_source` = "derived").
* adm         — an Agency Debit Memo billed on the line
* discount    — the vendor's discount (DIS_Sell)
* uatp_amount — paid by card straight to the airline (UATP / PaidByCreditCard)
* card_type   — the card it was paid with, as printed

on third_party_gds and third_party_gds_left_out alike (models/statement_row._GdsLineFields).
Nothing is backfilled: no line saved before had these columns to read.

Revision ID: tp_gds_std_02
Revises: stmt_mapping_01
Create Date: 2026-10-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_gds_std_02'
down_revision: Union[str, None] = 'stmt_mapping_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ('third_party_gds', 'third_party_gds_left_out')

# (column, `data` key, type) — as tp_gds_columns_01 lists its own.
_COLUMNS = [
    ('seat_selection', 'seat_selection', sa.Numeric()),
    ('excess_baggage', 'excess_baggage', sa.Numeric()),
    ('meals', 'meals', sa.Numeric()),
    ('cgst', 'cgst', sa.Numeric()),
    ('sgst', 'sgst', sa.Numeric()),
    ('igst', 'igst', sa.Numeric()),
    ('adm', 'adm', sa.Numeric()),
    ('discount', 'discount', sa.Numeric()),
    ('uatp_amount', 'uatp_amount', sa.Numeric()),
    ('card_type', 'card_type', sa.Text()),
    ('ssr_source', 'ssr_source', sa.String(20)),
    ('gst_source', 'gst_source', sa.String(20)),
]


def upgrade() -> None:
    for table in _TABLES:
        for name, _key, type_ in _COLUMNS:
            op.add_column(table, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        for name, _key, _type in reversed(_COLUMNS):
            op.drop_column(table, name)
