"""Internal Statement standard format: Date of Cancellation and Net Cancellation Amount

Two more columns of the user's standard set, read off Yatra's refund report
(date_of_cancellation, NettRefundableAmount):

* cancellation_date       — the day the ticket was cancelled, read in the Booking Date's format
* net_cancellation_amount — the net amount refunded

Either one filled marks the line a refund (services/ticket_duplicates.py `kind`) — as does a
negative Base Fare or Tax now, besides a negative Amount: the refund report prints its refunds
with a positive BSP Amount.

Added to BOTH ticket tables: internal_uploaded_tickets copies the uploaded_tickets definition
(models/internal_ticket.py), so the two must keep the same columns. Nullable; nothing is
backfilled.

Revision ID: internal_std_04
Revises: internal_imp_01
Create Date: 2026-10-30 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'internal_std_04'
down_revision: Union[str, None] = 'internal_imp_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TICKETS = ('uploaded_tickets', 'internal_uploaded_tickets')

_COLUMNS = [
    ('cancellation_date', sa.String(50)),
    ('net_cancellation_amount', sa.Numeric(14, 2)),
]


def upgrade() -> None:
    for table in _TICKETS:
        for name, type_ in _COLUMNS:
            op.add_column(table, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for table in _TICKETS:
        for name, _type in reversed(_COLUMNS):
            op.drop_column(table, name)
