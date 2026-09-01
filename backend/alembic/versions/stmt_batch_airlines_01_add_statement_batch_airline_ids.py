"""The LCC DI / Divided PNR / Flown Report / CTA/BTA uploads declare their airline ids.

Those four exports name no carrier, exactly like LCC Detailed, so the uploader now
declares which of their Airline Master ids the file covers — and may name several for
that carrier. See models/statement_batch_airline_id.py for why this cannot reuse
`lcc_batch_airline_ids` (those types have no batch header table to hang an FK on).

Nothing is backfilled: uploads made before this exist without a declared airline, and
guessing one would be inventing data. They read as "—" until re-uploaded.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this uses
a descriptive one, matching the `<feature>_<NN>` convention the recent migrations use.

Revision ID: stmt_batch_airlines_01
Revises: lcc_batch_airlines_01
"""
from alembic import op
import sqlalchemy as sa


revision = "stmt_batch_airlines_01"
down_revision = "lcc_batch_airlines_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_batch_airline_ids",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        ),
        # The statement type; batch_id has no FK because these types keep no batch
        # header row — a batch is a shared batch_id across the type's rows table.
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        # CASCADE, not RESTRICT — see the model. The in-use guard on
        # DELETE /tenant-airlines/{pk} is what actually protects the user.
        sa.Column(
            "tenant_airline_id", sa.Integer(),
            sa.ForeignKey("tenant_airlines.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.UniqueConstraint("slug", "batch_id", "tenant_airline_id",
                            name="uq_statement_batch_airline_ids_triple"),
    )
    op.create_index("ix_statement_batch_airline_ids_tenant_id", "statement_batch_airline_ids", ["tenant_id"])
    op.create_index("ix_statement_batch_airline_ids_tenant_airline_id", "statement_batch_airline_ids", ["tenant_airline_id"])
    op.create_index("ix_statement_batch_airline_ids_batch", "statement_batch_airline_ids", ["slug", "batch_id"])


def downgrade() -> None:
    op.drop_index("ix_statement_batch_airline_ids_batch", table_name="statement_batch_airline_ids")
    op.drop_index("ix_statement_batch_airline_ids_tenant_airline_id", table_name="statement_batch_airline_ids")
    op.drop_index("ix_statement_batch_airline_ids_tenant_id", table_name="statement_batch_airline_ids")
    op.drop_table("statement_batch_airline_ids")
