"""Service charge (as vendor) and service fee (as customer) on an agency

AN AGENCY IS READ FROM BOTH SIDES OF THE BUSINESS, and the two sides mean opposite
things by the same money:

    Vendors data   `deals.supplier_agency_id`   we BUY FROM them
                   -> their SERVICE CHARGE is a COST to us
    Customer data  `deals.agency_id`            we SELL TO them
                   -> our SERVICE FEE on them is INCOME

`deal_supplier_agency_01` already records that opposition in this schema ("It also
means the opposite thing — 'we sell TO them' rather than 'we buy FROM them'"). ONE
pair of columns would therefore be read as a cost on the Vendors screens and as
income on the Customer ones, with nothing on either saying which was meant — and the
rate we pay Lords is not the rate we charge Lords. So each direction gets its own
triple, and services/service_fee.py is the only thing that resolves them.

THREE COLUMNS PER DIRECTION, because inclusive/exclusive is not cosmetic. For an
amount A at 18%: exclusive is ₹A taxable with ₹A×0.18 on top; inclusive is ₹A/1.18
taxable with the rest already inside. A ₹1,000 fee differs by ₹180 between the two on
every line, so the flag is stored beside the value and is never inferred from it.

ON `agencies`, NOT `agency_terms`. A terms period may only be closed and reopened at
a cycle boundary with a settled, zero balance (services/agency_account.switch_blockers)
— correct for a credit limit, absurd for a fee rate, which must be editable any
Tuesday. And ONE AGENCY ROW IS ALREADY ONE BRANCH ON ONE CHANNEL (models/agency.py),
so a column here is per-channel for free: Lords Delhi GDS and Lords Delhi LCC each
carry their own rates with no extra modelling. The precedent is `customers.markup_type`
/ `markup_value`, flat columns on the party.

NOTHING CHANGES FOR ANY EXISTING AGENCY. All six are added NULL with no server_default
and nothing is backfilled, so every stored row keeps behaving exactly as it does now
and `service_fee._resolve` answers (None, None, 'exclusive') for it. This is the call
`party_cat_markup_01` made and stated: "NULL is honest for the rows that have never
been asked." No raised invoice can move either way, because nothing bills from these
columns yet — api/v1/agency_billing.py still hardcodes its markup at 0.0.

WHY `party_cat_markup_01` SKIPPED `agencies` AND THIS DOES NOT. That migration added
per-category markup and excluded agencies because "an agency carries no default markup
at all … so a category override there would be introducing markup rather than
qualifying it." Correct then, and still correct: this does not add a markup. A service
charge is a separately negotiated line that an agency quotes and an invoice shows on
its own, which is why it is its own columns rather than a markup default.

Revision ID: agency_service_fee_01
Revises: tkt_prefix_01
Create Date: 2026-09-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_service_fee_01"
down_revision: Union[str, None] = "tkt_prefix_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (column prefix, what it means). The suffixes are the same three for both, so
# services/service_fee.py can resolve either direction by prefix alone.
_PREFIXES = (
    "vendor_service_charge",    # they charge us  — a cost   (Vendors data)
    "customer_service_fee",     # we charge them  — income   (Customer data)
)

# String(20) for both choice columns, matching every other choice column in this
# schema (`agency_terms.agency_type`, `customers.markup_type`) — plain lowercase
# slugs, never a DB Enum, so a third treatment is a code change and not a migration.
# Numeric(14, 2) for the value, matching `customers.markup_value`: the same column
# holds a percentage and a rupee amount, and `*_type` says which it is.
def upgrade() -> None:
    for prefix in _PREFIXES:
        op.add_column("agencies", sa.Column(f"{prefix}_type", sa.String(length=20), nullable=True))
        op.add_column("agencies", sa.Column(f"{prefix}_value", sa.Numeric(14, 2), nullable=True))
        op.add_column("agencies", sa.Column(f"{prefix}_gst", sa.String(length=20), nullable=True))


def downgrade() -> None:
    for prefix in reversed(_PREFIXES):
        op.drop_column("agencies", f"{prefix}_gst")
        op.drop_column("agencies", f"{prefix}_value")
        op.drop_column("agencies", f"{prefix}_type")
