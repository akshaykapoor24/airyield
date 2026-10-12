"""A punched ticket records the supplier's GST on its charges separately.

Create Ticket shows each side of the sheet with its charge and its GST apart: the
client side already had cgst/sgst/igst (OUR GST to the client), but the supplier's
service charge was stored gross, its tax folded in. `supp_serv_gst` holds the GST
the supplier charges on its service and card charges, so supp_serv_charge_1 can
hold the charge alone.

Recorded only, nullable, no backfill — same rule as ticket_comm_sheet_01. Added to
both ticket tables for the reason given there.

Revision ID: ticket_comm_sheet_02
Revises: ticket_comm_sheet_01
"""
from alembic import op
import sqlalchemy as sa


revision = "ticket_comm_sheet_02"
down_revision = "ticket_comm_sheet_01"
branch_labels = None
depends_on = None


_TABLES = ("uploaded_tickets", "internal_uploaded_tickets")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("supp_serv_gst", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "supp_serv_gst")
