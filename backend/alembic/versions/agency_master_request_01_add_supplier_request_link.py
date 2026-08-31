"""Link an agency to the supplier-master request it was typed in under

Adding an agency used to require picking it out of the shared `suppliers` master.
That master holds a couple of thousand rows and the trade has lakhs, so the common
case — "my agency is not in the list" — had no path at all.

It now does: the agency is created immediately and a supplier-master request is
filed alongside it, through the same queue the Suppliers page already uses. This
column is the link between the two. It is what shows the pending/approved/rejected
chip on the agency row, and what the approve endpoint matches on to back-fill
`agencies.supplier_id` once the vendor exists in the master.

Nullable and SET NULL rather than CASCADE: an agency outlives its request. The row
is already trading — deals, entities, login ids, billing — and deleting the
request must never take it, nor the history hanging off it, with it.

Additive only; nothing is backfilled. Agencies created before this, and any
created by XLS upload, keep both ids NULL and are offered a "Request master entry"
action instead.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_master_request_01"
down_revision: Union[str, None] = "plb_accrual_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agencies",
        sa.Column("supplier_request_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_agencies_supplier_request_id",
        "agencies", "supplier_approvals",
        ["supplier_request_id"], ["id"],
        ondelete="SET NULL",
    )
    # The approve endpoint's back-link selects agencies BY this column, and the
    # list endpoint loads the linked approvals per page — both want the index.
    op.create_index(
        "ix_agencies_supplier_request_id", "agencies", ["supplier_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agencies_supplier_request_id", table_name="agencies")
    op.drop_constraint("fk_agencies_supplier_request_id", "agencies", type_="foreignkey")
    op.drop_column("agencies", "supplier_request_id")
