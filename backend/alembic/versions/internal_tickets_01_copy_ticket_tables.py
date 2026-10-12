"""Internal Statement gets its own ticket tables

`internal_ticket_statements` and `internal_uploaded_tickets` — exact structural copies of
`ticket_statements` and `uploaded_tickets` (which stay with Customer data → Statement).

LIKE ... INCLUDING ALL copies columns, defaults, NOT NULL / CHECK constraints, the primary
key and every index (under new names). The column defaults are copied too, so the ids
draw from the SAME sequences as the customer tables — an internal and a customer row never
share an id. Foreign keys are not copied by LIKE, so they are re-created from the source
tables' own definitions, read from the catalog.

No data is moved: Internal Statement starts empty. Everything saved before this revision
stays where it was, in the customer tables.

Revision ID: internal_tickets_01
Revises: tp_agency_01
Create Date: 2026-10-11 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'internal_tickets_01'
down_revision: Union[str, None] = 'tp_agency_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAIRS = (("ticket_statements", "internal_ticket_statements"),
         ("uploaded_tickets", "internal_uploaded_tickets"))


def upgrade() -> None:
    conn = op.get_bind()
    for src, dst in PAIRS:
        op.execute(f"CREATE TABLE {dst} (LIKE {src} INCLUDING ALL)")
        fks = conn.execute(sa.text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = CAST(:t AS regclass) AND contype = 'f'"
        ), {"t": src}).all()
        for name, definition in fks:
            new_name = name.replace(src, dst) if src in name else f"{dst}_{name}"
            op.execute(f'ALTER TABLE {dst} ADD CONSTRAINT "{new_name[:63]}" {definition}')


def downgrade() -> None:
    for _src, dst in reversed(PAIRS):
        op.execute(f"DROP TABLE IF EXISTS {dst}")
