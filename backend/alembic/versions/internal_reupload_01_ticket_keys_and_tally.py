"""Internal Statement: a statement period uploaded again saves only the new tickets

* uploaded_tickets.dedup_key — which line a ticket is, as it was uploaded
  (services/ticket_reupload.py): stamped at upload so a later cell edit does not change
  it, and read when an overlapping period is uploaded again for the same customer. No
  backfill: a ticket uploaded before has its key worked out from its columns instead.
* ticket_statements.total_entries / duplicate_entries / duplicate_of — the upload's
  tally: ticket lines in the file, how many of them were already saved by an earlier
  statement (left out), and the statement most of those are in. NULL / 0 for statements
  made before this, which simply show their ticket count.

Added to BOTH tables of each pair — uploaded_tickets and internal_uploaded_tickets,
ticket_statements and internal_ticket_statements — because the internal models are mapped
from the customer tables' own metadata (models/internal_ticket.py) and so expect every
column the customer models have. Only Internal Statement writes them.

Revision ID: internal_reupload_01
Revises: tp_gds_period_01
Create Date: 2026-10-17 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'internal_reupload_01'
down_revision: Union[str, None] = 'tp_gds_period_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TICKETS = ('uploaded_tickets', 'internal_uploaded_tickets')
_STATEMENTS = ('ticket_statements', 'internal_ticket_statements')


def upgrade() -> None:
    for table in _TICKETS:
        op.add_column(table, sa.Column('dedup_key', sa.String(64), nullable=True))
    for table in _STATEMENTS:
        op.add_column(table, sa.Column('total_entries', sa.Integer(), nullable=True))
        op.add_column(table, sa.Column('duplicate_entries', sa.Integer(), nullable=False, server_default='0'))
        op.add_column(table, sa.Column('duplicate_of', sa.String(100), nullable=True))


def downgrade() -> None:
    for table in _STATEMENTS:
        op.drop_column(table, 'duplicate_of')
        op.drop_column(table, 'duplicate_entries')
        op.drop_column(table, 'total_entries')
    for table in _TICKETS:
        op.drop_column(table, 'dedup_key')
