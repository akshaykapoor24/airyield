"""Third Party GDS: a Refund amount

The standard Third Party GDS columns (services/flat_statement.py `_TP_GDS_COLUMNS`) gain a
Refund amount — what the vendor credits back on a refund line, printed by Brightsun as
RFD_SELL — so a vendor's refund column has a field of its own to map onto:

* refund_amount — NUMERIC like every other amount

on third_party_gds and third_party_gds_left_out alike (models/statement_row._GdsLineFields).
Nothing is backfilled: no line saved before had the column to read.

Revision ID: tp_gds_std_03
Revises: tp_gds_std_02
Create Date: 2026-10-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_gds_std_03'
down_revision: Union[str, None] = 'tp_gds_std_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ('third_party_gds', 'third_party_gds_left_out')

# (column, `data` key, type) — as tp_gds_columns_01 lists its own.
_COLUMNS = [
    ('refund_amount', 'refund_amount', sa.Numeric()),
]


def upgrade() -> None:
    for table in _TABLES:
        for name, _key, type_ in _COLUMNS:
            op.add_column(table, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        for name, _key, _type in reversed(_COLUMNS):
            op.drop_column(table, name)
