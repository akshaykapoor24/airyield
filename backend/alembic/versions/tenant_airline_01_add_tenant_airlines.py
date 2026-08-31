"""Airline Master (tenant_airlines) + airline columns on the LCC Detailed tables.

An LCC Detailed export identifies no carrier — no airline column, and bare flight
numbers in `segments` — so the airline has to be declared by the user at upload.
This adds the tenant-level airline master that holds the user's own id per airline,
and the columns that carry the chosen airline onto the batch and every row.

Every new column is nullable: batches uploaded before this existed have no airline
until PATCH /lcc-detailed/batches/{batch_id}/airline backfills them.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this uses
a descriptive one, matching the `<feature>_<NN>` convention the recent migrations use.

(An earlier version of this docstring claimed `r2s3t4u5v6w7` and `s3t4u5v6w7x8` were
orphaned heads that made `alembic upgrade head` fail. That was wrong — both are merged
by `23f7d53e7e14_merge_migration_heads.py`, `alembic heads` reports a single head, and
`upgrade head` works. Upgrading by name is still the safer habit here.)

Revision ID: tenant_airline_01
Revises: bsp_commission_04
"""
from alembic import op
import sqlalchemy as sa


revision = "tenant_airline_01"
down_revision = "bsp_commission_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_airlines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        # RESTRICT: deleting a platform airline a tenant has stamped onto statement rows
        # should fail loudly rather than silently orphan them.
        sa.Column("airline_id", sa.Integer(), sa.ForeignKey("airlines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ref_id", sa.String(length=100), nullable=False),
        # Snapshots of the master at add time, so a statement keeps saying what it said
        # even if an admin later renames the airline or corrects its numeric code.
        sa.Column("airline_name", sa.String(length=255), nullable=True),
        sa.Column("airline_code", sa.String(length=20), nullable=True),
        sa.Column("iata_numeric_code", sa.String(length=3), nullable=True),
        sa.Column("contract_year", sa.String(length=2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "ref_id", name="uq_tenant_airlines_tenant_ref"),
    )
    op.create_index("ix_tenant_airlines_tenant_id", "tenant_airlines", ["tenant_id"])
    op.create_index("ix_tenant_airlines_created_by_id", "tenant_airlines", ["created_by_id"])
    op.create_index("ix_tenant_airlines_airline_id", "tenant_airlines", ["airline_id"])
    op.create_index("ix_tenant_airlines_ref_id", "tenant_airlines", ["ref_id"])

    # ── The batch carries the declared airline ───────────────────────────────
    op.add_column("lcc_detailed_batch", sa.Column("tenant_airline_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("airline_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("airline_name", sa.String(length=255), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("airline_code", sa.String(length=20), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("airline_ref_id", sa.String(length=100), nullable=True))
    op.create_foreign_key(
        "fk_lcc_batch_tenant_airline", "lcc_detailed_batch", "tenant_airlines",
        ["tenant_airline_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_lcc_batch_airline", "lcc_detailed_batch", "airlines",
        ["airline_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_lcc_batch_tenant_airline_id", "lcc_detailed_batch", ["tenant_airline_id"])
    op.create_index("ix_lcc_batch_airline_id", "lcc_detailed_batch", ["airline_id"])

    # ── Every row carries it too, denormalised ───────────────────────────────
    # So commission matching and the PLB accrual board read one table instead of
    # joining back to the header. No FK on airline_id — same convention as
    # bsp_statement_rows.matched_deal_id — to keep the chunked bulk insert cheap.
    op.add_column("lcc_detailed", sa.Column("airline_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed", sa.Column("airline_name", sa.String(length=255), nullable=True))
    op.add_column("lcc_detailed", sa.Column("airline_code", sa.String(length=20), nullable=True))
    op.create_index("ix_lcc_detailed_airline_id", "lcc_detailed", ["airline_id"])
    op.create_index("ix_lcc_detailed_tenant_airline", "lcc_detailed", ["tenant_id", "airline_code"])


def downgrade() -> None:
    op.drop_index("ix_lcc_detailed_tenant_airline", table_name="lcc_detailed")
    op.drop_index("ix_lcc_detailed_airline_id", table_name="lcc_detailed")
    op.drop_column("lcc_detailed", "airline_code")
    op.drop_column("lcc_detailed", "airline_name")
    op.drop_column("lcc_detailed", "airline_id")

    op.drop_index("ix_lcc_batch_airline_id", table_name="lcc_detailed_batch")
    op.drop_index("ix_lcc_batch_tenant_airline_id", table_name="lcc_detailed_batch")
    op.drop_constraint("fk_lcc_batch_airline", "lcc_detailed_batch", type_="foreignkey")
    op.drop_constraint("fk_lcc_batch_tenant_airline", "lcc_detailed_batch", type_="foreignkey")
    op.drop_column("lcc_detailed_batch", "airline_ref_id")
    op.drop_column("lcc_detailed_batch", "airline_code")
    op.drop_column("lcc_detailed_batch", "airline_name")
    op.drop_column("lcc_detailed_batch", "airline_id")
    op.drop_column("lcc_detailed_batch", "tenant_airline_id")

    op.drop_index("ix_tenant_airlines_ref_id", table_name="tenant_airlines")
    op.drop_index("ix_tenant_airlines_airline_id", table_name="tenant_airlines")
    op.drop_index("ix_tenant_airlines_created_by_id", table_name="tenant_airlines")
    op.drop_index("ix_tenant_airlines_tenant_id", table_name="tenant_airlines")
    op.drop_table("tenant_airlines")
