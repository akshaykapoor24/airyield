"""LCC statements → billable: per-row party resolution + projection state.

An LCC Detailed export names no customer — only a passenger per row — so before its
rows can be billed they have to be resolved to a Customer/Corporate and projected into
`uploaded_tickets`, the one table the billing screens read. This adds:

  * `lcc_detailed`       — the per-row resolution result and the projection back-link
  * `lcc_detailed_batch` — counters, the batch-level fallback party, and the stable
                           `ticket_statements.batch_id` the batch projects into
  * `uploaded_tickets`   — partial indexes for the new "link wins, name is the
                           fallback" billing predicate

Everything is additive and nullable/defaulted; there is no backfill.

NOTE on the uploaded_tickets indexes: `ix_uploaded_tickets_party` already exists from
`cust_party_01`, but it leads on (tenant_id, customer_type, …) so it cannot serve a
lookup on customer_id or corporate_id alone. The two partial indexes below do. The
third narrows to the untagged set, which is the half of the predicate that still falls
back to passenger-name matching — those name conditions (lower(first_name)=… and
pax_name ILIKE '%…%') cannot use a btree at all, so pre-filtering is the whole win.
`downgrade()` must NOT drop ix_uploaded_tickets_party; it belongs to cust_party_01.

Revision ID: lcc_billing_01
Revises: tenant_airline_01
"""
from alembic import op
import sqlalchemy as sa


revision = "lcc_billing_01"
down_revision = "tenant_airline_01"
branch_labels = None
depends_on = None


# Same vocabulary as ck_uploaded_tickets_customer_type (cust_party_01), so a value
# resolved here is always writable onto the projected ticket.
_PARTY_TYPES = "('agency','corporate','direct')"


def upgrade() -> None:
    # ── lcc_detailed: per-row resolution + projection back-link ───────────────
    op.add_column("lcc_detailed", sa.Column("bill_kind", sa.String(length=12), nullable=True))
    op.add_column("lcc_detailed", sa.Column("bill_status", sa.String(length=16), nullable=False, server_default="unresolved"))
    op.add_column("lcc_detailed", sa.Column("bill_customer_type", sa.String(length=12), nullable=True))
    op.add_column("lcc_detailed", sa.Column("bill_customer_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed", sa.Column("bill_corporate_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed", sa.Column("bill_match_reason", sa.String(length=300), nullable=True))
    op.add_column("lcc_detailed", sa.Column("projected_ticket_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.add_column("lcc_detailed", sa.Column("resolved_by_id", sa.Integer(), nullable=True))

    op.create_foreign_key("fk_lcc_detailed_bill_customer", "lcc_detailed", "customers",
                          ["bill_customer_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_lcc_detailed_bill_corporate", "lcc_detailed", "corporates",
                          ["bill_corporate_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_lcc_detailed_projected_ticket", "lcc_detailed", "uploaded_tickets",
                          ["projected_ticket_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_lcc_detailed_resolved_by", "lcc_detailed", "users",
                          ["resolved_by_id"], ["id"])
    op.create_check_constraint(
        "ck_lcc_detailed_bill_customer_type", "lcc_detailed",
        f"bill_customer_type IS NULL OR bill_customer_type IN {_PARTY_TYPES}",
    )

    # Worklist buckets are always (this batch, this status).
    op.create_index("ix_lcc_detailed_bill", "lcc_detailed", ["batch_id", "bill_status"])
    # Partial: only projected rows are ever looked up this way.
    op.create_index("ix_lcc_detailed_projected", "lcc_detailed", ["projected_ticket_id"],
                    postgresql_where=sa.text("projected_ticket_id IS NOT NULL"))

    # ── lcc_detailed_batch: counters, batch default, projection target ────────
    for col in ("billable_rows", "resolved_rows", "unresolved_rows", "projected_rows"):
        op.add_column("lcc_detailed_batch", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))

    op.add_column("lcc_detailed_batch", sa.Column("default_customer_type", sa.String(length=12), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("default_customer_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("default_corporate_id", sa.Integer(), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("resolution_status", sa.String(length=12), nullable=False, server_default="none"))
    op.add_column("lcc_detailed_batch", sa.Column("billing_batch_id", sa.String(length=100), nullable=True))
    op.add_column("lcc_detailed_batch", sa.Column("projected_at", sa.DateTime(), nullable=True))

    op.create_foreign_key("fk_lcc_batch_default_customer", "lcc_detailed_batch", "customers",
                          ["default_customer_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_lcc_batch_default_corporate", "lcc_detailed_batch", "corporates",
                          ["default_corporate_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint(
        "ck_lcc_batch_default_customer_type", "lcc_detailed_batch",
        f"default_customer_type IS NULL OR default_customer_type IN {_PARTY_TYPES}",
    )
    # One batch projects into exactly one statement header, for the life of the batch.
    op.create_unique_constraint("uq_lcc_batch_billing_batch_id", "lcc_detailed_batch", ["billing_batch_id"])
    op.create_index("ix_lcc_batch_resolution_status", "lcc_detailed_batch", ["resolution_status"])

    # ── uploaded_tickets: indexes for "link wins, name is the fallback" ───────
    op.create_index(
        "ix_uploaded_tickets_bill_customer", "uploaded_tickets",
        ["tenant_id", "created_by_id", "customer_id"],
        postgresql_where=sa.text("customer_id IS NOT NULL"),
    )
    op.create_index(
        "ix_uploaded_tickets_bill_corporate", "uploaded_tickets",
        ["tenant_id", "created_by_id", "corporate_id"],
        postgresql_where=sa.text("corporate_id IS NOT NULL"),
    )
    op.create_index(
        "ix_uploaded_tickets_untagged", "uploaded_tickets",
        ["tenant_id", "created_by_id"],
        postgresql_where=sa.text(
            "customer_type IS NULL AND customer_id IS NULL "
            "AND corporate_id IS NULL AND customer_agency_id IS NULL"
        ),
    )


def downgrade() -> None:
    # NOT ix_uploaded_tickets_party — that belongs to cust_party_01.
    op.drop_index("ix_uploaded_tickets_untagged", table_name="uploaded_tickets")
    op.drop_index("ix_uploaded_tickets_bill_corporate", table_name="uploaded_tickets")
    op.drop_index("ix_uploaded_tickets_bill_customer", table_name="uploaded_tickets")

    op.drop_index("ix_lcc_batch_resolution_status", table_name="lcc_detailed_batch")
    op.drop_constraint("uq_lcc_batch_billing_batch_id", "lcc_detailed_batch", type_="unique")
    op.drop_constraint("ck_lcc_batch_default_customer_type", "lcc_detailed_batch", type_="check")
    op.drop_constraint("fk_lcc_batch_default_corporate", "lcc_detailed_batch", type_="foreignkey")
    op.drop_constraint("fk_lcc_batch_default_customer", "lcc_detailed_batch", type_="foreignkey")
    for col in ("projected_at", "billing_batch_id", "resolution_status",
                "default_corporate_id", "default_customer_id", "default_customer_type",
                "projected_rows", "unresolved_rows", "resolved_rows", "billable_rows"):
        op.drop_column("lcc_detailed_batch", col)

    op.drop_index("ix_lcc_detailed_projected", table_name="lcc_detailed")
    op.drop_index("ix_lcc_detailed_bill", table_name="lcc_detailed")
    op.drop_constraint("ck_lcc_detailed_bill_customer_type", "lcc_detailed", type_="check")
    op.drop_constraint("fk_lcc_detailed_resolved_by", "lcc_detailed", type_="foreignkey")
    op.drop_constraint("fk_lcc_detailed_projected_ticket", "lcc_detailed", type_="foreignkey")
    op.drop_constraint("fk_lcc_detailed_bill_corporate", "lcc_detailed", type_="foreignkey")
    op.drop_constraint("fk_lcc_detailed_bill_customer", "lcc_detailed", type_="foreignkey")
    for col in ("resolved_by_id", "resolved_at", "projected_ticket_id", "bill_match_reason",
                "bill_corporate_id", "bill_customer_id", "bill_customer_type",
                "bill_status", "bill_kind"):
        op.drop_column("lcc_detailed", col)
