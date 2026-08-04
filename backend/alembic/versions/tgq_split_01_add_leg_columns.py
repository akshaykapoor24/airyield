"""Per-sector leg columns on the airline-ticket statement tables

A TGQ HMPR / NDC line covers a whole ticket, but `Sectors` lists every flown sector.
Ingest now expands one source line into one row per sector, allocating the money across
the legs, and marks the export's own grand-total line so it stops behaving like a ticket.

These columns carry that: which leg a row is (`sector_index`/`sector_count`), which source
line it came from (`row_seq`, so legs sort under their parent), how confident the split was
(`split_status`), whether the row is the declared total (`is_total`), and the pre-split row
verbatim (`orig_data`/`orig_taxes`) so a batch can be re-split later without re-upload.

Deliberately NO data backfill: existing rows keep `sector_count NULL`, which the API reads
as "never processed" and surfaces as a one-click Re-process in the UI. That keeps the
migration instant and reversible, and makes the split observable rather than silent.

Revision ID: tgq_split_01
Revises: user_entity_access_01
Create Date: 2026-07-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "tgq_split_01"
down_revision: Union[str, None] = "user_entity_access_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The ticket-shaped statement tables (models/statement_row.py::_SplitMixin). The
# ledger-shaped ones (lcc_di, lcc_divided_pnr, …) have no sectors and are untouched.
_TABLES = ("tgq_hmpr", "ndc")

_COLUMNS = (
    ("row_seq",      lambda: sa.Column("row_seq", sa.Integer(), nullable=True)),
    ("sector_index", lambda: sa.Column("sector_index", sa.Integer(), nullable=True)),
    ("sector_count", lambda: sa.Column("sector_count", sa.Integer(), nullable=True)),
    ("split_status", lambda: sa.Column("split_status", sa.String(length=20), nullable=True)),
    # server_default so plain INSERTs (and the pre-existing rows) get false, not NULL.
    ("is_total",     lambda: sa.Column("is_total", sa.Boolean(), nullable=False,
                                       server_default=sa.text("false"))),
    ("orig_data",    lambda: sa.Column("orig_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True)),
    ("orig_taxes",   lambda: sa.Column("orig_taxes", postgresql.JSONB(astext_type=sa.Text()), nullable=True)),
)


def upgrade() -> None:
    for table in _TABLES:
        for _, make_col in _COLUMNS:
            op.add_column(table, make_col())


def downgrade() -> None:
    for table in _TABLES:
        for name, _ in reversed(_COLUMNS):
            op.drop_column(table, name)
