"""LCC Detailed: bill a fixed markup per passenger, like Third Party API statements

`lcc_detailed.pax_count` is the booking's passenger count, and it is repeated on every
transaction row of the PNR — the sale, its refund, a change fee — rather than being one row
per passenger. So a fixed markup multiplied by it on each row is charged once per passenger
per transaction, and a refund reverses exactly what its sale charged.

  lcc_detailed.bill_pax_count   A human's correction of the pax, from the LCC billing worklist.
                                NULL means "what the statement says" — unlike third_party_api,
                                the file's own figure is a real column here, so nothing needs
                                stamping and a NULL is never ambiguous.

THE BACKFILL. Every LCC row already in billing was projected before `uploaded_tickets.pax_count`
existed, so its ticket reads 1. Tickets NOT yet on an invoice are brought up to the row's pax,
which is what applying the rule means — their Sold Tickets preview reprices on the next load.
Tickets ALREADY on an invoice are left at 1: the invoice is a snapshot in billings.line_items and
does not move, and the ticket must keep agreeing with what was billed.

Revision ID: lcc_pax_01
Revises: tp_api_pax_01
Create Date: 2026-09-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'lcc_pax_01'
down_revision: Union[str, None] = 'tp_api_pax_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lcc_detailed', sa.Column('bill_pax_count', sa.SmallInteger(), nullable=True))
    # Same guard as lcc_billing_projection.file_pax: a blank, zero or absurd figure is 1.
    op.execute("""
        UPDATE uploaded_tickets t
           SET pax_count = CASE WHEN l.pax_count BETWEEN 1 AND 99 THEN l.pax_count ELSE 1 END
          FROM lcc_detailed l
         WHERE l.projected_ticket_id = t.id
           AND t.billing_id IS NULL
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE uploaded_tickets t
           SET pax_count = 1
          FROM lcc_detailed l
         WHERE l.projected_ticket_id = t.id
           AND t.billing_id IS NULL
    """)
    op.drop_column('lcc_detailed', 'bill_pax_count')
