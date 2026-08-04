"""TGQ HMPR enrichment columns on BSP settlement rows

A BSP settlement statement prints no cabin class, no sector and no travel date, so the
commission engine had to skip every deal criterion that depends on them. The TGQ HMPR
statement prints all three and joins on (airline accounting code, document number).

These columns persist what the join resolved — the whole journey folded from the ticket's
flown sectors, the distinct cabin classes, the first leg's travel date — so the results grid
can show what a match was actually based on and a past run stays auditable.

Deliberately NO backfill: existing rows keep `enrichment_source` NULL, which the engine
reads as "no TGQ counterpart" and which reproduces today's behaviour exactly. Re-running a
statement fills them in.

Revision ID: bsp_commission_03
Revises: tgq_split_01
Create Date: 2026-07-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bsp_commission_03"
# The revision id encodes the domain; down_revision encodes the actual graph. `tgq_split_01`
# is the live head (via user_entity_access_01), so chaining here keeps it single-headed.
down_revision: Union[str, None] = "tgq_split_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ROW_COLS = [
    ("enriched_sector",             lambda: sa.Column("enriched_sector", sa.String(length=200), nullable=True)),
    ("enriched_booking_class",      lambda: sa.Column("enriched_booking_class", sa.String(length=60), nullable=True)),
    ("enriched_travel_date",        lambda: sa.Column("enriched_travel_date", sa.Date(), nullable=True)),
    ("enriched_travel_date_source", lambda: sa.Column("enriched_travel_date_source", sa.String(length=12), nullable=True)),
    ("enriched_leg_count",          lambda: sa.Column("enriched_leg_count", sa.Integer(), nullable=True)),
    ("enrichment_source",           lambda: sa.Column("enrichment_source", sa.String(length=20), nullable=True)),
    ("enrichment_ref",              lambda: sa.Column("enrichment_ref", sa.String(length=100), nullable=True)),
]

_STMT_COLS = [
    ("commission_enriched_rows", lambda: sa.Column("commission_enriched_rows", sa.Integer(),
                                                   nullable=False, server_default="0")),
]


def upgrade() -> None:
    for _, make_col in _ROW_COLS:
        op.add_column("bsp_statement_rows", make_col())
    for _, make_col in _STMT_COLS:
        op.add_column("bsp_statements", make_col())


def downgrade() -> None:
    for name, _ in reversed(_STMT_COLS):
        op.drop_column("bsp_statements", name)
    for name, _ in reversed(_ROW_COLS):
        op.drop_column("bsp_statement_rows", name)
