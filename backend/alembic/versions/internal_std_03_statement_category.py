"""Statement Type of an Internal Statement: Booking / MO or Accounting

Internal Statement's upload asks which system's report the file is — a booking (mid-office)
statement or an accounting statement — and no longer asks for a period: a statement's
valid_from / valid_to are the first and last Booking Date of its tickets.

* statement_category — "booking" | "accounting"; NULL for Customer data, Create Ticket's
                       "Manual Entry" batches and anything that does not ask

Added to both statement tables: internal_ticket_statements is a copy of ticket_statements'
definition (models/internal_ticket.py), so a column on one must be on the other.

Internal Statement's uploaded statements so far were all booking reports — the default the
page now picks — and are backfilled as such.

Revision ID: internal_std_03
Revises: internal_std_02
Create Date: 2026-10-29 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'internal_std_03'
down_revision: Union[str, None] = 'internal_std_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('ticket_statements', 'internal_ticket_statements')


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column('statement_category', sa.String(20), nullable=True))
    op.execute(
        "UPDATE internal_ticket_statements SET statement_category = 'booking' "
        "WHERE file_name <> 'Manual Entry'"
    )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, 'statement_category')
