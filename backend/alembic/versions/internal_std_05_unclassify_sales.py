"""Internal Statement: undo the ADM / ACM marking the ticket builder put on sales

The ticket builder marked any ticket whose document serial starts with 6 or 8 an ADM / ACM (and
400 an RA) and set its Invoice Type to "Credit Note" — a rule for BSP memo serials. On an OTA's
sales record the ticket numbers are tickets: Yatra's 6901466337 is a ₹28,472 sale, and as a
Credit Note it read as a refund in the duplicate check and the Payment Module's mapping. The
builder no longer does it for Internal Statement (tickets.py `INTERNAL_STANDARD`).

Internal Statement's standard format has no Invoice Type field, so on an internal ticket marked
ADM / ACM / RA the Credit Note can only have come from that rule: both are cleared, there only.
Customer data's tickets are untouched.

Revision ID: internal_std_05
Revises: internal_std_04
Create Date: 2026-10-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'internal_std_05'
down_revision: Union[str, None] = 'internal_std_04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE internal_uploaded_tickets
           SET invoice_type = CASE WHEN invoice_type = 'Credit Note' THEN NULL ELSE invoice_type END,
               adm_acm_ra = NULL
         WHERE adm_acm_ra IN ('ADM', 'ACM', 'RA')
    """)


def downgrade() -> None:
    # What was cleared was the builder's guess, not anything a file said: nothing to restore.
    pass
