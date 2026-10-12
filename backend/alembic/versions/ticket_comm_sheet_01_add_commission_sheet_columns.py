"""A punched ticket carries the desk software's full commission sheet.

Internal Statement → Create Ticket is laid out like the "INT. Sales" screen agencies
already punch into, and that screen separates what was RECEIVED from the supplier
from what was PAID on to the client, keeps two recalls, and has client- and
supplier-side charges. The ticket tables had one column for each of only some of
those, so nine amounts are added:

    plb_recd            PLB received from the supplier
    incentive_paid      incentive passed on to the client
    plb_paid            PLB passed on to the client
    disc_recall         discount recalled from the client
    serv_charge_2/_3    client service charges 2 and 3 (serv_charge is charge 1)
    supp_serv_charge_1  supplier service charges #1 and #2
    supp_serv_charge_2
    card_charge         supplier card charges

Commission paid is the existing dis_sell, recall (supplier) the existing adm.

All RECORDED, never calculated on — deal_matching reads none of them. Nullable
with no backfill: an older ticket did not record these, and a zero would claim it did.

Added to BOTH uploaded_tickets and its structural copy internal_uploaded_tickets
(internal_tickets_01), because the internal model is mapped from the customer
table's own metadata and so expects every column the customer model has.

Revision ID: ticket_comm_sheet_01
Revises: internal_tickets_01
"""
from alembic import op
import sqlalchemy as sa


revision = "ticket_comm_sheet_01"
down_revision = "internal_tickets_01"
branch_labels = None
depends_on = None


_TABLES = ("uploaded_tickets", "internal_uploaded_tickets")
_COLUMNS = (
    "plb_recd", "incentive_paid", "plb_paid", "disc_recall",
    "serv_charge_2", "serv_charge_3", "supp_serv_charge_1", "supp_serv_charge_2",
    "card_charge",
)


def upgrade() -> None:
    for table in _TABLES:
        for name in _COLUMNS:
            op.add_column(table, sa.Column(name, sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        for name in reversed(_COLUMNS):
            op.drop_column(table, name)
