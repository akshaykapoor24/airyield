"""An incoming B2B deal is picked from Agency Master, and remembers which agency

The Supplier Name on an incoming B2B deal used to be picked from the platform-admin
`suppliers` master. It is now picked from the user's own Agency Master (User master →
Agency Master), because that is where they onboard the agencies they actually trade with —
along with each one's branch, channel, entities, login ids and, since agency_service_fee_01,
the service charge that agency levies on us as a vendor. A name from the global master
carries none of that.

THIS DOES NOT UNDO tp_supplier_link_01, and the difference is the whole design. That
migration moved `deals.supplier_id` from `agencies` to `suppliers` because a third-party
statement is attributed to a SUPPLIER row, and the commission matcher compares the two ids
(services/deal_matching.py::_supplier_guard). That stays exactly as it is:

    deals.supplier_id       → suppliers.id   what the deal is MATCHED by — unchanged
    deals.vendor_agency_id  → agencies.id    which Agency Master row it was PICKED from — new

Every agency already records the supplier row it was copied from (`agencies.supplier_id`),
so picking an agency yields both ids at once: the API copies `supplier_id` through from the
agency, and the matcher never learns that the form changed. Nothing about pricing moves.

WHY A SECOND COLUMN AND NOT JUST THE NAME. `agencies` is split by branch AND channel —
Lords Delhi GDS and Lords Delhi LCC are two rows with one name and one supplier_id, and
each carries its own terms and its own vendor service charge. The name cannot say which of
the two a deal was signed with; only the row's id can.

`vendor_`, NOT `supplier_agency_id`. That was this schema's name for a DIFFERENT link —
deal_supplier_agency_01 added it, tp_supplier_link_01 renamed it to `supplier_id` and
repointed it at `suppliers`, and its downgrade renames it back. Reusing the name would make
the history read as if that decision had been reversed. `vendor_` also matches the vendor
side of `agencies.vendor_service_charge_*`, which this link is what will eventually price.
And it is NOT `deals.agency_id`: that is the OUTGOING scope ("we sell TO them"), pinned to
scope_type='agency' by ck_deals_scope_agency, while every inbound deal is scope_type='all'.

ON DELETE RESTRICT, like `deals.agency_id`. An agency named on incoming deals cannot be
deleted out from under them; DELETE /agencies/{id} counts them and answers with a readable
409 ("mark it inactive instead"). SET NULL would quietly detach a live contract from the
agency whose terms it was agreed on — the same reason `deals.supplier_id` is RESTRICT.

NOT BACKFILLED. An existing deal names a supplier-master name, and a vendor onboarded on
both channels matches two agencies with nothing to choose between them. Those deals keep
working exactly as before on `supplier_name` + `supplier_id`; the edit form preselects the
agency when exactly one matches, and saving then links it.

Revision ID: deal_vendor_agency_01
Revises: agency_service_fee_01
Create Date: 2026-09-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "deal_vendor_agency_01"
down_revision: Union[str, None] = "agency_service_fee_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Integer, not BigInteger: `agencies.id` is a bare mapped_column(primary_key=True),
    # the same note cust_scope_01 makes for `deals.agency_id`.
    op.add_column("deals", sa.Column("vendor_agency_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_deals_vendor_agency_id", "deals", "agencies",
        ["vendor_agency_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_deals_vendor_agency_id", "deals", ["vendor_agency_id"])
    # The same shape as ck_deals_supplier: an agency we BUY from exists only on a deal we
    # RECEIVE. Both enum columns are native_enum=False with values_callable, so the stored
    # values really are these lowercase strings.
    op.create_check_constraint(
        "ck_deals_vendor_agency", "deals",
        "vendor_agency_id IS NULL OR (deal_type = 'b2b' AND direction = 'inbound')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_deals_vendor_agency", "deals", type_="check")
    op.drop_index("ix_deals_vendor_agency_id", table_name="deals")
    op.drop_constraint("fk_deals_vendor_agency_id", "deals", type_="foreignkey")
    op.drop_column("deals", "vendor_agency_id")
