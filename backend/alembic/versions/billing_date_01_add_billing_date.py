"""A bill has one invoice date, and it is chosen, not inferred.

Corporate Billing used to ask for a billing PERIOD and printed the moment of saving
as the invoice date. It now asks for the billing date itself, and a new bill may not
be dated before the user's last bill for anyone — the order an invoice series has to
keep. That needs the date stored, so it can be compared against.

BACKFILLED FROM created_at
──────────────────────────
Every existing bill printed `created_at` as its Invoice Date, so that IS its billing
date; copying it across changes nothing any PDF shows. NOT NULL afterwards, with
CURRENT_DATE as the server default for any insert that does not name it — the ORM
sets it explicitly (models/billing.py).

Revision ID: billing_date_01
Revises: bank_statements_01
"""
from alembic import op
import sqlalchemy as sa


revision = "billing_date_01"
down_revision = "bank_statements_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billings", sa.Column("billing_date", sa.Date(), nullable=True))
    op.execute("UPDATE billings SET billing_date = created_at::date WHERE billing_date IS NULL")
    # A row with no created_at at all has no better answer than today.
    op.execute("UPDATE billings SET billing_date = CURRENT_DATE WHERE billing_date IS NULL")
    op.alter_column(
        "billings", "billing_date",
        nullable=False, server_default=sa.text("CURRENT_DATE"),
    )
    # The "last bill" lookup orders on it for one user.
    op.create_index("ix_billings_billing_date", "billings", ["billing_date"])


def downgrade() -> None:
    op.drop_index("ix_billings_billing_date", table_name="billings")
    op.drop_column("billings", "billing_date")
