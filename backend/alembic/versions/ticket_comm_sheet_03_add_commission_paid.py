"""Commission paid to the client gets its own column.

ticket_comm_sheet_01 filed "commission paid" under the existing dis_sell. That was
wrong: on a consolidator statement the Discount column is what the SUPPLIER gives
the agency — it is deducted from the bill (BillAmount = fare − Discount + charges
+ GST + TDS) — so dis_sell is a RECEIVED figure. Commission passed on to the client
is a different number and now has its own home.

Recorded only, nullable, no backfill; both ticket tables, as in ticket_comm_sheet_01.

Revision ID: ticket_comm_sheet_03
Revises: ticket_comm_sheet_02
"""
from alembic import op
import sqlalchemy as sa


revision = "ticket_comm_sheet_03"
down_revision = "ticket_comm_sheet_02"
branch_labels = None
depends_on = None


_TABLES = ("uploaded_tickets", "internal_uploaded_tickets")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("comm_paid", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "comm_paid")
