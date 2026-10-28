"""Third Party GDS: a Tour Code, and the tour code a commission was priced with

Deal rules can restrict a payout by tour code — the Tour Code field, and the Corporate /
Excursion / Tour fare types, which match a ticket whose tour code is one the deal names
(services/exclusion_evaluator). A consolidator's GDS statement had no column to carry it, so
those rules could never be judged. The standard columns (services/flat_statement.py
`_TP_GDS_COLUMNS`) gain one:

* tour_code — TEXT, on third_party_gds and third_party_gds_left_out alike
  (models/statement_row._GdsLineFields)

and the commission ledger's input snapshot gains what the match saw, so the diagnosis popup
judges a tour-code rule exactly as the run did:

* commission_calculations.tour_code       — the ticket's tour code, NULL when it had none
* commission_calculations.tour_code_known — False when the statement did not print the
                                            column at all (a blank is then "unknown", not
                                            "no tour code")

Nothing is backfilled: no line saved before had the column to read.

Revision ID: tp_gds_std_04
Revises: tp_gds_std_03
Create Date: 2026-10-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_gds_std_04'
down_revision: Union[str, None] = 'tp_gds_std_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ('third_party_gds', 'third_party_gds_left_out')

# (column, `data` key, type) — as tp_gds_columns_01 lists its own.
_COLUMNS = [
    ('tour_code', 'tour_code', sa.Text()),
]


def upgrade() -> None:
    for table in _TABLES:
        for name, _key, type_ in _COLUMNS:
            op.add_column(table, sa.Column(name, type_, nullable=True))
    op.add_column('commission_calculations',
                  sa.Column('tour_code', sa.String(100), nullable=True))
    op.add_column('commission_calculations',
                  sa.Column('tour_code_known', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('commission_calculations', 'tour_code_known')
    op.drop_column('commission_calculations', 'tour_code')
    for table in _TABLES:
        for name, _key, _type in reversed(_COLUMNS):
            op.drop_column(table, name)
