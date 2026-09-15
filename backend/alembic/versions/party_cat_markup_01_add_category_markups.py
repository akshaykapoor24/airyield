"""Per-category markup on Employee Master and Corporate Master

A party has had ONE markup (`markup_type` + `markup_value`) applied to every ticket. An
agency that also sells hotel nights, train berths, buses, cars and MICE needs a different
rate per line of business. `category_markups` holds an override per category slug —
`{"hotel": {"type": "percentage", "value": 5}}` — and services/party_markup.markup_for picks
the one a billable line belongs to, falling back to the two columns above.

NOTHING CHANGES FOR ANY EXISTING PARTY. The column is added NULL and nothing is backfilled,
so `markup_for(party, …)` returns literally `(party.markup_type, party.markup_value)` — the
same two expressions the four billing call sites pass today — until a human types an
override. No raised invoice can move either way: api/v1/{customers,corporates}.py's
update_billing re-prices from the `line_items` JSONB snapshot and never re-reads the party.

NO `server_default='{}'`, AND NO `default=` ON THE MODEL. NULL and `{}` must not become two
spellings of one state, or `party_inherit.is_blank`, `markup_for` and the browser each have
to handle two empties. NULL is honest for the rows that have never been asked — the same
call customer_state_01 made for `customers.state`.

JSONB rather than a child table: `services/party_inherit` copies an employee's terms down
from their corporate as a flat dict of COLUMN NAMES, and a child table has no attribute to
copy. One JSONB column joins that mechanism as one more entry; see the module docstring.

Revision ID: party_cat_markup_01
Revises: tp_api_billing_01
Create Date: 2026-09-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'party_cat_markup_01'
down_revision: Union[str, None] = 'tp_api_billing_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Employee Master and Corporate Master. NOT `agencies`: an agency carries no default markup
# at all (api/v1/agency_billing.py hardcodes 0.0, deliberately), so a category override there
# would be introducing markup rather than qualifying it.
_TABLES = ('customers', 'corporates')


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column('category_markups', postgresql.JSONB(astext_type=sa.Text()),
                      nullable=True),
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_column(table, 'category_markups')
