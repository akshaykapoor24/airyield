"""An invoice has to say WHICH GST it charged, not just how much.

`billings` carried a single `total_gst`, and the PDF printed it under a
hardcoded "GST (18%)". That is not a tax invoice. CGST + SGST and IGST are
different taxes going to different governments, and a return filed from these
rows needs to know which — the total alone cannot be split back afterwards,
because whether a sale was intra-state or inter-state is a fact about the two
parties at the moment of sale, not about the number.

WHY THE PLACE OF SUPPLY IS SNAPSHOTTED TOO
──────────────────────────────────────────
`supplier_state_code` and `place_of_supply_code` record the two states that were
compared, and `gst_treatment` records the answer. Without them, editing a raised
billing would re-decide the heads from the party's CURRENT address: a customer
who adds a GSTIN next month would silently move an already-issued invoice from
CGST + SGST to IGST, changing a filed return with no record that it happened.
The billing already snapshots `billing_type` and `line_items` for the same
reason — a bill is a statement about a moment.

NOTHING IS BACKFILLED, AND THE TOTALS START AT ZERO
───────────────────────────────────────────────────
Existing billings were raised before any place of supply was known. Guessing one
now would attribute real tax to a head nobody chose. A NULL `gst_treatment`
therefore means "raised before the split existed" — for those rows `total_gst`
stays the authoritative figure and the screens show it as they always have.
That is distinct from the string 'unsplit', which means a billing raised AFTER
this change whose place of supply could not be decided.

Revision ID: billing_gst_split_01
Revises: customer_state_01
"""
from alembic import op
import sqlalchemy as sa


revision = "billing_gst_split_01"
down_revision = "customer_state_01"
branch_labels = None
depends_on = None


# (column, type, nullable, server_default) — one list so upgrade and downgrade
# cannot drift apart. The three money columns are NOT NULL with a zero default,
# matching total_gst beside them: a tax of "unknown" is not a thing, and every
# caller sums them.
_COLUMNS = (
    ("total_cgst", sa.Numeric(14, 2), False, "0"),
    ("total_sgst", sa.Numeric(14, 2), False, "0"),
    ("total_igst", sa.Numeric(14, 2), False, "0"),
    # 'cgst_sgst' | 'igst' | 'unsplit'; NULL = raised before this migration.
    ("gst_treatment", sa.String(length=16), True, None),
    # The two GSTIN state codes that were compared, e.g. '07' and '27'. Two
    # characters because that is what a state code is.
    ("supplier_state_code", sa.String(length=2), True, None),
    ("place_of_supply_code", sa.String(length=2), True, None),
)


def upgrade() -> None:
    for name, type_, nullable, default in _COLUMNS:
        op.add_column(
            "billings",
            sa.Column(name, type_, nullable=nullable, server_default=default),
        )


def downgrade() -> None:
    for name, _type, _nullable, _default in reversed(_COLUMNS):
        op.drop_column("billings", name)
