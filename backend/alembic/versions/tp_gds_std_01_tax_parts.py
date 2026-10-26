"""Third Party GDS: YR and K3 taxes, and a derived Total Tax

The Third Party GDS mapping screen now maps every consolidator onto one standard set of
columns (services/flat_statement.py `_TP_GDS_COLUMNS`). Its tax block gained YR Tax and
K3 Tax beside YQ and Other Taxes, and Total Tax — the whole bill — is added up from them
when the file does not print it. So each line table gets:

* yr, k3            — the two taxes, NUMERIC like every other amount
* total_tax_source  — "derived" when Total Tax was added up rather than read

on third_party_gds and third_party_gds_left_out alike (models/statement_row._GdsLineFields).
Nothing is backfilled: no line saved before had a YR or K3 column to read.

Revision ID: tp_gds_std_01
Revises: tp_gds_left_out_01
Create Date: 2026-10-25 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_gds_std_01'
down_revision: Union[str, None] = 'tp_gds_left_out_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ('third_party_gds', 'third_party_gds_left_out')

# (column, `data` key, type) — as tp_gds_columns_01 lists its own.
_COLUMNS = [
    ('yr', 'yr', sa.Numeric()),
    ('k3', 'k3', sa.Numeric()),
    ('total_tax_source', 'total_tax_source', sa.String(20)),
]


def upgrade() -> None:
    for table in _TABLES:
        for name, _key, type_ in _COLUMNS:
            op.add_column(table, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        for name, _key, _type in reversed(_COLUMNS):
            op.drop_column(table, name)
