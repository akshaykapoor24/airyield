"""An uploaded ticket carries what a consolidator's own statement prints.

Until now `uploaded_tickets` could hold our template's columns and a BSP export's,
but not an Indian consolidator's — Globe, Akbar, Riya, TSI and the rest issue a
weekly statement with a vocabulary of its own. Uploading one meant either losing
four money columns or forcing them into fields that mean something else, and the
near-misses were the dangerous option: a service charge landing in
`booking_fee_sell` is an ancillary incentive base, so it would have changed a
payout rather than merely been filed in the wrong place.

The four amounts:

    oc_tax       a carrier-imposed misc fee, printed as its own column
    raf          refund administration fee — charged on the credit note, not the sale
    serv_charge  the agency's own service / management fee
    gst_sell     GST as ONE figure. Not sale_k3, which is GST on the air fare, and
                 not the cgst/sgst/igst triple — this is the tax on the service
                 charge printed beside it, and it lands on a different line of a return.

And four identifiers:

    doc_no       the consolidator's voucher, "IS26/ 1067" — deliberately not
    doc_date     invoice_no / ticket_date, which belong to the airline's document.
                 On a credit note ("IR26/ 358") the consolidator's date is the
                 credit date, so folding it into ticket_date would misdate refunds.
    reference    free text the statement carries per row
    narration

All eight are RECORDED, never calculated on. `deal_matching._calc_base` reads
sell_fare, sell_tax_yq and sale_yr; the ancillary bases are seat_selection,
excess_baggage and meals. Nothing here is one of those, and nothing here should
ever be added to them without a deliberate decision about payouts.

Nullable with no backfill: a ticket imported before this simply did not record
these, and inventing a zero would claim the statement said something it did not.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this
uses a descriptive one, matching the `<feature>_<NN>` convention of the recent
migrations.

Revision ID: ticket_stmt_cols_01
Revises: tenant_profile_01
"""
from alembic import op
import sqlalchemy as sa


revision = "ticket_stmt_cols_01"
down_revision = "tenant_profile_01"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("oc_tax", sa.Numeric(14, 2)),
    ("raf", sa.Numeric(14, 2)),
    ("serv_charge", sa.Numeric(14, 2)),
    ("gst_sell", sa.Numeric(14, 2)),
    ("doc_no", sa.String(length=100)),
    ("doc_date", sa.String(length=50)),
    ("reference", sa.String(length=200)),
    ("narration", sa.String(length=500)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("uploaded_tickets", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("uploaded_tickets", name)
