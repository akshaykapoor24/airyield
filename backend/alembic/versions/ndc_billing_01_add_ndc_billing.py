"""NDC statements → billable: per-row party + roll-up verdict, and a per-batch billing header.

An NDC export names no customer — only a passenger per row — so before its rows can be
billed they have to be resolved to a Customer/Corporate and projected into
`uploaded_tickets`, the one table the billing screens read. It also writes ancillaries
(PAID_SEAT / REFUND_SEAT) as their own document-less lines, which have to be latched onto
the ticket they belong to first. This adds:

  * `ndc`                      — the party resolution, the roll-up verdict, the row's own
                                 parsed amount, and the projection back-link
  * `statement_batch_billing`  — the per-upload billing header the spec-driven types have
                                 nowhere else to keep: counters, the batch-level fallback
                                 party, and the stable `ticket_statements.batch_id` the
                                 upload projects into

Everything is additive and nullable/defaulted; there is no backfill. An NDC upload made
before this migration simply reads as `bill_status = 'unresolved'` until someone opens its
Billing screen.

ONLY `ndc` GETS THE COLUMNS. Eight tables share `_StatementBase` (tgq_hmpr, ndc, lcc_di,
lcc_divided_pnr, lcc_flown_report, lcc_cta_bta, third_party_gds, third_party_lcc). NDC is
the one that opts into billing — `statement_spec.supports_billing` — and the model layer
says so through `_BillingMixin` on `Ndc` alone rather than through the shared base.

NOTE on `uploaded_tickets`: this migration adds NO indexes there. `lcc_billing_01` already
created `ix_uploaded_tickets_bill_customer`, `ix_uploaded_tickets_bill_corporate` and
`ix_uploaded_tickets_untagged`, and the NDC projection is read back through the identical
"link wins, name is the fallback" predicate. `downgrade()` must NOT drop them — they belong
to `lcc_billing_01`, the same trap that file documents for `ix_uploaded_tickets_party`.

Revision ID: ndc_billing_01
Revises: tenant_phone_01
"""
from alembic import op
import sqlalchemy as sa


revision = "ndc_billing_01"
down_revision = "tenant_phone_01"
branch_labels = None
depends_on = None


# Same vocabulary as ck_uploaded_tickets_customer_type (cust_party_01), so a value resolved
# here is always writable onto the projected ticket.
_PARTY_TYPES = "('agency','corporate','direct')"

# See services/ndc_billing_projection.py: `anchor` carries a document number and becomes the
# ticket; `latched` rolls into an anchor's ticket; the last three are ancillary lines that
# could not be attached to one and are awaiting a decision.
_LATCH_STATUSES = "('anchor','latched','orphan','ambiguous','unidentified')"

_NDC_COLUMNS = (
    ("bill_kind", sa.String(length=12), True, None),
    ("bill_status", sa.String(length=16), False, "unresolved"),
    ("bill_customer_type", sa.String(length=12), True, None),
    ("bill_customer_id", sa.Integer(), True, None),
    ("bill_corporate_id", sa.Integer(), True, None),
    ("bill_match_reason", sa.String(length=300), True, None),
    ("bill_group_key", sa.String(length=64), True, None),
    ("bill_is_anchor", sa.Boolean(), False, "false"),
    ("bill_latch_status", sa.String(length=12), True, None),
    ("bill_amount", sa.Numeric(14, 2), True, None),
    ("projected_ticket_id", sa.Integer(), True, None),
    ("resolved_at", sa.DateTime(), True, None),
    ("resolved_by_id", sa.Integer(), True, None),
)


def upgrade() -> None:
    # ── ndc: per-row party, roll-up verdict, projection back-link ─────────────
    for name, type_, nullable, default in _NDC_COLUMNS:
        op.add_column("ndc", sa.Column(name, type_, nullable=nullable, server_default=default))

    op.create_foreign_key("fk_ndc_bill_customer", "ndc", "customers",
                          ["bill_customer_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_ndc_bill_corporate", "ndc", "corporates",
                          ["bill_corporate_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_ndc_projected_ticket", "ndc", "uploaded_tickets",
                          ["projected_ticket_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_ndc_resolved_by", "ndc", "users",
                          ["resolved_by_id"], ["id"])
    op.create_check_constraint(
        "ck_ndc_bill_customer_type", "ndc",
        f"bill_customer_type IS NULL OR bill_customer_type IN {_PARTY_TYPES}",
    )
    op.create_check_constraint(
        "ck_ndc_bill_latch_status", "ndc",
        f"bill_latch_status IS NULL OR bill_latch_status IN {_LATCH_STATUSES}",
    )

    # Worklist buckets are always (this batch, this status).
    op.create_index("ix_ndc_bill", "ndc", ["batch_id", "bill_status"])
    # The roll-up reads and writes a whole group at a time.
    op.create_index("ix_ndc_bill_group", "ndc", ["batch_id", "bill_group_key"])
    # Partial: only projected rows are ever looked up this way.
    op.create_index("ix_ndc_projected", "ndc", ["projected_ticket_id"],
                    postgresql_where=sa.text("projected_ticket_id IS NOT NULL"))

    # ── statement_batch_billing: the per-upload billing header ───────────────
    op.create_table(
        "statement_batch_billing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        # Not on statement_batch_suppliers, and load-bearing here: `ndc` rows are scoped
        # (tenant_id, created_by_id), so a header keyed on the tenant alone would let one
        # user's batch-default party rewrite another user's rows.
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),

        sa.Column("billable_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unresolved_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("projected_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("projected_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("group_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latched_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unlatched_rows", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("default_customer_type", sa.String(length=12), nullable=True),
        sa.Column("default_customer_id", sa.Integer(), nullable=True),
        sa.Column("default_corporate_id", sa.Integer(), nullable=True),

        sa.Column("resolution_status", sa.String(length=12), nullable=False, server_default="none"),
        sa.Column("billing_batch_id", sa.String(length=100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("projected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),

        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["default_customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["default_corporate_id"], ["corporates.id"], ondelete="SET NULL"),
        # One billing header per upload, and one ticket_statements row per upload — the
        # second is what keeps re-projecting a batch refreshing that header instead of
        # leaving a new one behind each run.
        sa.UniqueConstraint("slug", "batch_id", name="uq_statement_batch_billing_batch"),
        sa.UniqueConstraint("billing_batch_id", name="uq_statement_batch_billing_target"),
        sa.CheckConstraint(
            f"default_customer_type IS NULL OR default_customer_type IN {_PARTY_TYPES}",
            name="ck_statement_batch_billing_party",
        ),
    )
    op.create_index("ix_statement_batch_billing_tenant_id", "statement_batch_billing", ["tenant_id"])
    op.create_index("ix_statement_batch_billing_created_by_id", "statement_batch_billing", ["created_by_id"])
    op.create_index("ix_statement_batch_billing_batch", "statement_batch_billing", ["slug", "batch_id"])
    op.create_index("ix_statement_batch_billing_status", "statement_batch_billing", ["slug", "resolution_status"])


def downgrade() -> None:
    # NOT the three ix_uploaded_tickets_bill_* / _untagged indexes — those belong to
    # lcc_billing_01 and LCC still reads through them.
    op.drop_index("ix_statement_batch_billing_status", table_name="statement_batch_billing")
    op.drop_index("ix_statement_batch_billing_batch", table_name="statement_batch_billing")
    op.drop_index("ix_statement_batch_billing_created_by_id", table_name="statement_batch_billing")
    op.drop_index("ix_statement_batch_billing_tenant_id", table_name="statement_batch_billing")
    op.drop_table("statement_batch_billing")

    op.drop_index("ix_ndc_projected", table_name="ndc")
    op.drop_index("ix_ndc_bill_group", table_name="ndc")
    op.drop_index("ix_ndc_bill", table_name="ndc")
    op.drop_constraint("ck_ndc_bill_latch_status", "ndc", type_="check")
    op.drop_constraint("ck_ndc_bill_customer_type", "ndc", type_="check")
    op.drop_constraint("fk_ndc_resolved_by", "ndc", type_="foreignkey")
    op.drop_constraint("fk_ndc_projected_ticket", "ndc", type_="foreignkey")
    op.drop_constraint("fk_ndc_bill_corporate", "ndc", type_="foreignkey")
    op.drop_constraint("fk_ndc_bill_customer", "ndc", type_="foreignkey")
    for name, _type, _nullable, _default in reversed(_NDC_COLUMNS):
        op.drop_column("ndc", name)
