"""An LCC Detailed upload can cover several of the tenant's airline ids.

A tenant holds several agent-portal ids per carrier, and one statement routinely
covers more than one of them. The upload wizard now takes a set; this is the table
that set lives in. See models/lcc_batch_airline_id.py for why every id in a batch's
set must belong to the same airline, and why that leaves the rest of the schema
(the batch's airline_* columns and the per-row stamping) untouched.

`lcc_detailed_batch.tenant_airline_id` / `airline_ref_id` are NOT dropped — they stay
as the primary (first-selected) id, which is what keeps already-uploaded batches, the
batches list and the id-usage count working unchanged. The backfill below gives every
existing batch a one-id set so nothing reads as unlinked.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this uses
a descriptive one, matching the `<feature>_<NN>` convention the recent migrations use.

Revision ID: lcc_batch_airlines_01
Revises: lcc_billing_01
"""
from alembic import op
import sqlalchemy as sa


revision = "lcc_batch_airlines_01"
down_revision = "lcc_billing_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lcc_batch_airline_ids",
        sa.Column("id", sa.Integer(), primary_key=True),
        # CASCADE on both sides — see the model for why RESTRICT on the airline id
        # would break workspace deletion. The user-facing protection against losing
        # an id a statement names is the in-use guard on DELETE /tenant-airlines/{pk}.
        sa.Column(
            "batch_id", sa.String(length=100),
            sa.ForeignKey("lcc_detailed_batch.batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_airline_id", sa.Integer(),
            sa.ForeignKey("tenant_airlines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("batch_id", "tenant_airline_id", name="uq_lcc_batch_airline_ids_pair"),
    )
    op.create_index("ix_lcc_batch_airline_ids_batch_id", "lcc_batch_airline_ids", ["batch_id"])
    op.create_index("ix_lcc_batch_airline_ids_tenant_airline_id", "lcc_batch_airline_ids", ["tenant_airline_id"])

    # Every batch uploaded before this arrives as a one-id set, so the new set is
    # never emptier than the column it supersedes.
    op.execute(
        """
        INSERT INTO lcc_batch_airline_ids (batch_id, tenant_airline_id)
        SELECT batch_id, tenant_airline_id
        FROM lcc_detailed_batch
        WHERE tenant_airline_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_lcc_batch_airline_ids_tenant_airline_id", table_name="lcc_batch_airline_ids")
    op.drop_index("ix_lcc_batch_airline_ids_batch_id", table_name="lcc_batch_airline_ids")
    op.drop_table("lcc_batch_airline_ids")
