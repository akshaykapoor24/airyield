"""Internal Statement standard format: the columns an OTA's sales record carries

The user's standard set for an Internal Statement record, first read off Yatra's fortnightly
B2B sales report. Most of it lands in fields the ticket already has (Booking Ref, Doc No,
Basic Fare, Total Tax, Fare Basis, Flight No, Net Fare …); these had no home:

* adt_ref             — the online booking reference; present = an Online sale
* booking_status      — TIX ISSUED, PART TIX, REFUNDED …, as printed
* sales_channel       — Online | Offline
* supplier_can_charge — the airline's (supplier's) cancellation fee
* reschedule_charge   — rebooking / reschedule charges
* supplier_name       — who the ticket was bought from, as printed (resolved to Payable To)
* iata_no             — the supplier account's IATA number
* customer_code       — the customer's code in the OTA's system
* vendor_code         — the supplier's code in the OTA's system
* booked_by           — "Created By": the OTA's booking agent
* iata_comm_amt       — the IATA commission as printed (not the run's iata_commission)
* plb_amount          — the PLB as printed
* payment_mode        — CASH, card …, as printed
* segment_count       — how many flown segments
* cabin_class         — Economy / Premium Economy / Business / First

Added to BOTH ticket tables: internal_uploaded_tickets copies the uploaded_tickets definition
(models/internal_ticket.py), so the two must keep the same columns. All nullable; nothing is
backfilled — no ticket saved before had these to read.

Revision ID: internal_std_01
Revises: tp_gds_std_04
Create Date: 2026-10-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'internal_std_01'
down_revision: Union[str, None] = 'tp_gds_std_04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TICKETS = ('uploaded_tickets', 'internal_uploaded_tickets')

_COLUMNS = [
    ('adt_ref', sa.String(100)),
    ('booking_status', sa.String(50)),
    ('sales_channel', sa.String(20)),
    ('supplier_can_charge', sa.Numeric(14, 2)),
    ('reschedule_charge', sa.Numeric(14, 2)),
    ('supplier_name', sa.String(300)),
    ('iata_no', sa.String(50)),
    ('customer_code', sa.String(50)),
    ('vendor_code', sa.String(50)),
    ('booked_by', sa.String(200)),
    ('iata_comm_amt', sa.Numeric(14, 2)),
    ('plb_amount', sa.Numeric(14, 2)),
    ('payment_mode', sa.String(200)),
    ('segment_count', sa.Integer()),
    ('cabin_class', sa.String(30)),
]


def upgrade() -> None:
    for table in _TICKETS:
        for name, type_ in _COLUMNS:
            op.add_column(table, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for table in _TICKETS:
        for name, _type in reversed(_COLUMNS):
            op.drop_column(table, name)
