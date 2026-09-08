"""Record who moved a ticket between billing parties, and when.

A ticket's bill-to party was decided once — at upload from the customer picker,
or by the LCC resolver — and nothing could change it afterwards. Sold Tickets now
can, which means an invoice's worth of money moves from one party's list to
another's on a single click. `uploaded_tickets` carries only `created_by_id` /
`created_at`, so before this there was no way to answer "who moved this, and off
whose bill?" — a question finance asks the moment a total changes.

Two columns, following `lcc_detailed.resolved_at` / `resolved_by_id`, which the
LCC worklist already stamps for exactly this action. Denormalised onto the row
rather than a side table because this schema has no history table anywhere and
inventing one for a single feature would be the odd thing out.

Deliberately NOT a full before/after snapshot (the `original_payload` JSONB shape
the *_approval tables use). The previous party is recoverable from the ticket's
own history in `raw_data` for LCC rows, and the value here is attribution, not
reconstruction. If that changes, add the JSONB then.

Both nullable with no backfill: a NULL means "never re-tagged", which is the
truth for every row that exists today. Stamping them at upload would make the
columns mean "last touched" instead, which is not what they are for.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this
uses a descriptive one, matching the `<feature>_<NN>` convention of the recent
migrations.

Revision ID: ticket_retag_01
Revises: tenant_gst_scheme_01
"""
from alembic import op
import sqlalchemy as sa


revision = "ticket_retag_01"
down_revision = "tenant_gst_scheme_01"
branch_labels = None
depends_on = None


TABLE = "uploaded_tickets"

# (column, type) pairs, so upgrade and downgrade cannot drift apart.
_COLUMNS = (
    ("retagged_at", sa.DateTime()),
    ("retagged_by_id", sa.Integer()),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column(TABLE, sa.Column(name, type_, nullable=True))
    # SET NULL, not RESTRICT: losing the user who re-tagged a ticket must never
    # block deleting that user, and matches how every other actor FK on this
    # table's neighbours behaves.
    op.create_foreign_key(
        f"fk_{TABLE}_retagged_by_id", TABLE, "users",
        ["retagged_by_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(f"fk_{TABLE}_retagged_by_id", TABLE, type_="foreignkey")
    for name, _ in reversed(_COLUMNS):
        op.drop_column(TABLE, name)
