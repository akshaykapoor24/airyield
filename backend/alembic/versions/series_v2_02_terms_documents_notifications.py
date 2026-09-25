"""Series contracts: priced terms, source documents, and in-app notifications

WHAT THIS ADDS AND WHY

  series_terms       Every clause that prices a change — Air France's date-banded total and
                     partial cancellation tables, Air India's 20% free release, name
                     replacement quota and 4000/6000/9000 per-cabin grids. Until now the
                     contract could say when money was due but not what backing out costs,
                     which is the number an agency most needs before a departure goes soft.
  series_documents   The PDF a contract was read from, stored in GCS. Uploaded before the
                     contract exists (the AI reads it to fill the form), so contract_id is
                     nullable and set when the reviewed form is saved.
  notifications      The header bell. Contract reminders are broadcast to the workspace
  notification_reads (user_id NULL); read state is per person, so it cannot be a column.

  series_contracts gains option_expires_on, supplier_ref, materialization_floor_pct,
  foc_per_paid, baggage_allowance and event_name. The 80% floor was a constant in the
  router; it is Air India's figure, not everybody's.

  series_payment_schedule gains is_refundable and due_offset_days ("final payment 8 days
  before departure" when no date is printed).

  The deadline type CHECK widens to OPTION_EXPIRY and PENALTY_STEP.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "series_v2_02"
down_revision: Union[str, None] = "series_v2_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Literals, not model imports — see series_v2_01.
OLD_DEADLINE_TYPES = (
    "ADVANCE_DEPOSIT", "DEPOSIT", "NAME_LIST", "SEAT_RELEASE", "FINAL_PAYMENT",
    "TICKETING", "NO_SHOW_CUTOFF", "DEVIATION_CUTOFF", "DEPARTURE",
)
DEADLINE_TYPES = OLD_DEADLINE_TYPES + ("OPTION_EXPIRY", "PENALTY_STEP")
TERM_RULE_TYPES = (
    "CANCELLATION", "SEAT_RELEASE", "NAME_CHANGE", "DEVIATION", "REISSUE", "NO_SHOW",
    "REFUND", "MATERIALIZATION",
)
TERM_SCOPES = ("GROUP", "PARTIAL", "PER_PAX")
TERM_PHASES = (
    "ANY", "BEFORE_DEPOSIT", "AFTER_DEPOSIT_BEFORE_FINAL", "AFTER_FINAL_PAYMENT",
    "BEFORE_TICKETING", "AFTER_TICKETING",
)
TERM_CHARGE_TYPES = (
    "FREE", "PCT_OF_BASIS", "FIXED_PER_PAX", "FIXED_TOTAL", "DEPOSIT_FORFEIT",
    "NON_REFUNDABLE", "TAXES_ONLY_REFUNDABLE", "FARE_DIFFERENCE", "NOT_PERMITTED",
)
DOCUMENT_KINDS = ("QUOTATION", "CONTRACT", "AMENDMENT", "NAME_LIST", "OTHER")
EXTRACTION_STATUSES = ("stored", "processing", "done", "failed", "skipped")
SEVERITIES = ("info", "success", "warning", "critical")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _tenant_fk():
    return sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)


def upgrade() -> None:
    # ── series_contracts ──────────────────────────────────────────────────────
    op.add_column("series_contracts", sa.Column("option_expires_on", sa.Date(), nullable=True))
    op.add_column("series_contracts", sa.Column("supplier_ref", sa.String(length=80), nullable=True))
    op.add_column("series_contracts", sa.Column("materialization_floor_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("series_contracts", sa.Column("foc_per_paid", sa.Integer(), nullable=True))
    op.add_column("series_contracts", sa.Column("baggage_allowance", sa.String(length=100), nullable=True))
    op.add_column("series_contracts", sa.Column("event_name", sa.String(length=200), nullable=True))

    # ── series_payment_schedule ───────────────────────────────────────────────
    op.add_column("series_payment_schedule", sa.Column("is_refundable", sa.Boolean(), nullable=True))
    op.add_column("series_payment_schedule", sa.Column("due_offset_days", sa.Integer(), nullable=True))

    # ── deadline vocabulary ───────────────────────────────────────────────────
    op.drop_constraint("ck_series_deadlines_type", "series_deadlines", type_="check")
    op.create_check_constraint("ck_series_deadlines_type", "series_deadlines", _in("deadline_type", DEADLINE_TYPES))

    # ── series_terms ──────────────────────────────────────────────────────────
    op.create_table(
        "series_terms",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("allocation_id", sa.Integer(), sa.ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("rule_type", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=True),
        sa.Column("phase", sa.String(length=30), server_default="ANY", nullable=False),
        sa.Column("days_before_max", sa.Integer(), nullable=True),
        sa.Column("days_before_min", sa.Integer(), nullable=True),
        sa.Column("share_min_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("share_max_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("charge_type", sa.String(length=30), nullable=False),
        sa.Column("charge_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("charge_basis", sa.String(length=30), nullable=True),
        sa.Column("cabin", sa.String(length=20), nullable=True),
        sa.Column("plus_gst", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("source_text", sa.String(length=1000), nullable=True),
        sa.Column("source_page", sa.SmallInteger(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("rule_type", TERM_RULE_TYPES), name="ck_series_terms_rule_type"),
        sa.CheckConstraint(_in("scope", TERM_SCOPES), name="ck_series_terms_scope"),
        sa.CheckConstraint(_in("phase", TERM_PHASES), name="ck_series_terms_phase"),
        sa.CheckConstraint(_in("charge_type", TERM_CHARGE_TYPES), name="ck_series_terms_charge_type"),
    )
    op.create_index("ix_series_terms_tenant_id", "series_terms", ["tenant_id"])
    op.create_index("ix_series_terms_tenant_contract", "series_terms", ["tenant_id", "contract_id"])

    # ── series_documents ──────────────────────────────────────────────────────
    op.create_table(
        "series_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("doc_kind", sa.String(length=20), server_default="CONTRACT", nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_url", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("page_count", sa.SmallInteger(), nullable=True),
        sa.Column("scanned_pages", sa.SmallInteger(), nullable=True),
        sa.Column("extraction_status", sa.String(length=20), server_default="stored", nullable=False),
        sa.Column("extraction_error", sa.String(length=1000), nullable=True),
        sa.Column("extraction_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extraction_model", sa.String(length=60), nullable=True),
        sa.Column("extraction_ms", sa.Integer(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("doc_kind", DOCUMENT_KINDS), name="ck_series_documents_kind"),
        sa.CheckConstraint(_in("extraction_status", EXTRACTION_STATUSES), name="ck_series_documents_status"),
    )
    op.create_index("ix_series_documents_tenant_id", "series_documents", ["tenant_id"])
    op.create_index("ix_series_documents_created_by_id", "series_documents", ["created_by_id"])
    op.create_index("ix_series_documents_sha256", "series_documents", ["sha256"])
    op.create_index("ix_series_documents_tenant_contract", "series_documents", ["tenant_id", "contract_id"])
    op.create_index("ix_series_documents_tenant_created", "series_documents", ["tenant_id", "created_at"])

    # ── notifications ─────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=10), server_default="info", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=True),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("severity", SEVERITIES), name="ck_notifications_severity"),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_notifications_tenant_dedupe"),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_tenant_created", "notifications", ["tenant_id", "created_at"])

    op.create_table(
        "notification_reads",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_user"),
    )
    op.create_index("ix_notification_reads_tenant_id", "notification_reads", ["tenant_id"])
    op.create_index("ix_notification_reads_user", "notification_reads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_reads_user", table_name="notification_reads")
    op.drop_index("ix_notification_reads_tenant_id", table_name="notification_reads")
    op.drop_table("notification_reads")
    op.drop_index("ix_notifications_tenant_created", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_index("ix_notifications_tenant_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_series_documents_tenant_created", table_name="series_documents")
    op.drop_index("ix_series_documents_tenant_contract", table_name="series_documents")
    op.drop_index("ix_series_documents_sha256", table_name="series_documents")
    op.drop_index("ix_series_documents_created_by_id", table_name="series_documents")
    op.drop_index("ix_series_documents_tenant_id", table_name="series_documents")
    op.drop_table("series_documents")

    op.drop_index("ix_series_terms_tenant_contract", table_name="series_terms")
    op.drop_index("ix_series_terms_tenant_id", table_name="series_terms")
    op.drop_table("series_terms")

    # Rows of the two new types would violate the narrower CHECK.
    op.execute("DELETE FROM series_deadlines WHERE deadline_type IN ('OPTION_EXPIRY', 'PENALTY_STEP')")
    op.drop_constraint("ck_series_deadlines_type", "series_deadlines", type_="check")
    op.create_check_constraint("ck_series_deadlines_type", "series_deadlines", _in("deadline_type", OLD_DEADLINE_TYPES))

    op.drop_column("series_payment_schedule", "due_offset_days")
    op.drop_column("series_payment_schedule", "is_refundable")

    for column in ("event_name", "baggage_allowance", "foc_per_paid",
                   "materialization_floor_pct", "supplier_ref", "option_expires_on"):
        op.drop_column("series_contracts", column)
