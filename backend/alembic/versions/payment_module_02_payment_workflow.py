"""Payment Module: checks, decisions, payments and carry-forward (the full 13-step process)

  statement_batch_controls  One row per tp-gds / mo-gds upload: rows read and saved, the
                            OLD/BALANCE balances, optional expected totals (steps 2, 5).
  vendor_accounts           Your customer ID at each vendor, confirmed once (step 3).
  mo_vendor_corrections     An MO ticket filed under the vendor that billed it (step 6C).
  vendor_payments           Payments recorded to vendors (step 12).
  payment_items             One per billed vendor ticket per upload: the latest
                            reconciliation's snapshot, Operations' decision (step 10) and
                            the payment that settled it (step 12). Unpaid = carried
                            forward (step 13).

  payment_reconciliations   + ticket_key, booking_id, not_billed, is_duplicate,
                            duplicate_info, mo_vendor_status, mo_vendor_info, enrichment.

DATA: the statement's own OLD/BALANCE lines are now stamped `data.row_kind` at ingest
(services/statement_balance.py). Existing third_party_gds / mid_office_gds rows are stamped
here so their entry counts and totals stop counting the BALANCE line as a ticket; the
downgrade removes the stamp again.

Hand-written: autogenerate on this repo proposes ~240 unrelated drops.

Revision ID: payment_module_02
Revises: payment_module_01
Create Date: 2026-10-04 12:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "payment_module_02"
down_revision: Union[str, None] = "payment_module_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAMPED_TABLES = ("third_party_gds", "mid_office_gds")


def _owner_cols():
    return [
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
    ]


def _owner_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_created_by_id", table, ["created_by_id"])


def upgrade() -> None:
    op.create_table(
        "statement_batch_controls",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_owner_cols(),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        sa.Column("file_rows", sa.Integer(), nullable=True),
        sa.Column("loaded_rows", sa.Integer(), nullable=True),
        sa.Column("header_row", sa.Integer(), nullable=True),
        sa.Column("opening_balance", sa.Numeric(20, 4), nullable=True),
        sa.Column("opening_source", sa.String(length=8), nullable=True),
        sa.Column("closing_balance", sa.Numeric(20, 4), nullable=True),
        sa.Column("expected_count", sa.Integer(), nullable=True),
        sa.Column("expected_amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("slug", "batch_id", name="uq_statement_batch_controls_batch"),
    )
    _owner_indexes("statement_batch_controls")
    op.create_index("ix_statement_batch_controls_batch", "statement_batch_controls",
                    ["slug", "batch_id"])

    op.create_table(
        "vendor_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_owner_cols(),
        sa.Column("supplier_id", sa.Integer(),
                  sa.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "created_by_id", "supplier_id", "account_id",
                            name="uq_vendor_accounts_account"),
    )
    _owner_indexes("vendor_accounts")
    op.create_index("ix_vendor_accounts_supplier_id", "vendor_accounts", ["supplier_id"])

    op.create_table(
        "mo_vendor_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_owner_cols(),
        sa.Column("mo_batch_id", sa.String(length=100), nullable=False),
        sa.Column("ticket_key", sa.String(length=160), nullable=False),
        sa.Column("ticket_number", sa.String(length=100), nullable=True),
        sa.Column("from_supplier_id", sa.Integer(),
                  sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("from_supplier_name", sa.String(length=255), nullable=True),
        sa.Column("to_supplier_id", sa.Integer(),
                  sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_supplier_name", sa.String(length=255), nullable=True),
        sa.Column("to_supplier_code", sa.String(length=50), nullable=True),
        sa.Column("vendor_batch_id", sa.String(length=100), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "created_by_id", "mo_batch_id", "ticket_key",
                            name="uq_mo_vendor_corrections_ticket"),
    )
    _owner_indexes("mo_vendor_corrections")
    op.create_index("ix_mo_vendor_corrections_mo_batch_id", "mo_vendor_corrections",
                    ["mo_batch_id"])
    op.create_index("ix_mo_vendor_corrections_to_supplier_id", "mo_vendor_corrections",
                    ["to_supplier_id"])

    op.create_table(
        "vendor_payments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        *_owner_cols(),
        sa.Column("supplier_id", sa.Integer(),
                  sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("vendor_batch_id", sa.String(length=100), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("items_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="completed"),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("voided_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    _owner_indexes("vendor_payments")
    op.create_index("ix_vendor_payments_vendor_batch_id", "vendor_payments", ["vendor_batch_id"])
    op.create_index("ix_vendor_payments_supplier", "vendor_payments",
                    ["tenant_id", "created_by_id", "supplier_id"])

    money = ("vendor_net", "mo_net", "net_variance", "calc_commission",
             "commission_shortfall", "suggested_payable")
    op.create_table(
        "payment_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        *_owner_cols(),
        sa.Column("supplier_id", sa.Integer(),
                  sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("vendor_batch_id", sa.String(length=100), nullable=False),
        sa.Column("vendor_source_file", sa.String(length=255), nullable=True),
        sa.Column("statement_uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("ticket_key", sa.String(length=160), nullable=False),
        sa.Column("mo_batch_id", sa.String(length=100), nullable=True),
        sa.Column("ticket_number", sa.String(length=100), nullable=True),
        sa.Column("ticket_prefix", sa.String(length=4), nullable=True),
        sa.Column("pax_name", sa.String(length=300), nullable=True),
        sa.Column("airline_name", sa.String(length=200), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("sector", sa.String(length=200), nullable=True),
        sa.Column("booking_id", sa.String(length=100), nullable=True),
        sa.Column("vendor_row_ids", JSONB(), nullable=True),
        sa.Column("match_status", sa.String(length=16), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("not_billed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mo_vendor_status", sa.String(length=16), nullable=True),
        sa.Column("commission_status", sa.String(length=12), nullable=True),
        sa.Column("income_needs_data", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("commission_ran", sa.Boolean(), nullable=False, server_default="false"),
        *[sa.Column(c, sa.Numeric(14, 2), nullable=True) for c in money],
        sa.Column("decision_status", sa.String(length=12), nullable=False,
                  server_default="pending"),
        sa.Column("decision_source", sa.String(length=8), nullable=False, server_default="auto"),
        sa.Column("decision_action", sa.String(length=20), nullable=True),
        sa.Column("approved_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("ops_reference", sa.String(length=150), nullable=True),
        sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("payment_id", sa.BigInteger(),
                  sa.ForeignKey("vendor_payments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("paid_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "created_by_id", "vendor_batch_id", "ticket_key",
                            name="uq_payment_items_ticket"),
    )
    _owner_indexes("payment_items")
    op.create_index("ix_payment_items_decision_status", "payment_items", ["decision_status"])
    op.create_index("ix_payment_items_payment_id", "payment_items", ["payment_id"])
    op.create_index("ix_payment_items_supplier", "payment_items",
                    ["tenant_id", "created_by_id", "supplier_id"])
    op.create_index("ix_payment_items_batch", "payment_items",
                    ["tenant_id", "created_by_id", "vendor_batch_id"])

    # ── reconciliation rows: the process-check columns ───────────────────────
    op.add_column("payment_reconciliations",
                  sa.Column("ticket_key", sa.String(length=160), nullable=True))
    op.add_column("payment_reconciliations",
                  sa.Column("booking_id", sa.String(length=100), nullable=True))
    op.add_column("payment_reconciliations",
                  sa.Column("not_billed", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("payment_reconciliations",
                  sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("payment_reconciliations", sa.Column("duplicate_info", JSONB(), nullable=True))
    op.add_column("payment_reconciliations",
                  sa.Column("mo_vendor_status", sa.String(length=16), nullable=False,
                            server_default="none"))
    op.add_column("payment_reconciliations", sa.Column("mo_vendor_info", JSONB(), nullable=True))
    op.add_column("payment_reconciliations", sa.Column("enrichment", JSONB(), nullable=True))
    op.create_index("ix_payment_reconciliations_ticket_key", "payment_reconciliations",
                    ["ticket_key"])

    # ── stamp the statement balance lines already loaded ─────────────────────
    from app.services import statement_balance

    bind = op.get_bind()
    for table in _STAMPED_TABLES:
        rows = bind.execute(sa.text(
            f"SELECT id, data FROM {table} "
            "WHERE coalesce(data->>'ticket_number', '') = '' "
            "AND coalesce(data->>'pnr', '') = '' AND coalesce(data->>'airline_pnr', '') = '' "
            "AND coalesce(data->>'gds_pnr', '') = '' "
            "AND coalesce(data->>'passenger_name', '') = ''"
        )).all()
        for rid, data in rows:
            data = dict(data or {})
            before = (data.get(statement_balance.ROW_KIND_KEY), data.get(statement_balance.ROW_LABEL_KEY))
            statement_balance.tag(data)
            after = (data.get(statement_balance.ROW_KIND_KEY), data.get(statement_balance.ROW_LABEL_KEY))
            if before != after:
                bind.execute(sa.text(f"UPDATE {table} SET data = CAST(:d AS jsonb) WHERE id = :i"),
                             {"d": json.dumps(data), "i": rid})


def downgrade() -> None:
    bind = op.get_bind()
    for table in _STAMPED_TABLES:
        bind.execute(sa.text(
            f"UPDATE {table} SET data = data - 'row_kind' - 'row_label' WHERE data ? 'row_kind'"))

    op.drop_index("ix_payment_reconciliations_ticket_key", table_name="payment_reconciliations")
    for col in ("enrichment", "mo_vendor_info", "mo_vendor_status", "duplicate_info",
                "is_duplicate", "not_billed", "booking_id", "ticket_key"):
        op.drop_column("payment_reconciliations", col)

    for name in ("ix_payment_items_batch", "ix_payment_items_supplier",
                 "ix_payment_items_payment_id", "ix_payment_items_decision_status",
                 "ix_payment_items_created_by_id", "ix_payment_items_tenant_id"):
        op.drop_index(name, table_name="payment_items")
    op.drop_table("payment_items")

    for name in ("ix_vendor_payments_supplier", "ix_vendor_payments_vendor_batch_id",
                 "ix_vendor_payments_created_by_id", "ix_vendor_payments_tenant_id"):
        op.drop_index(name, table_name="vendor_payments")
    op.drop_table("vendor_payments")

    for name in ("ix_mo_vendor_corrections_to_supplier_id", "ix_mo_vendor_corrections_mo_batch_id",
                 "ix_mo_vendor_corrections_created_by_id", "ix_mo_vendor_corrections_tenant_id"):
        op.drop_index(name, table_name="mo_vendor_corrections")
    op.drop_table("mo_vendor_corrections")

    for name in ("ix_vendor_accounts_supplier_id", "ix_vendor_accounts_created_by_id",
                 "ix_vendor_accounts_tenant_id"):
        op.drop_index(name, table_name="vendor_accounts")
    op.drop_table("vendor_accounts")

    for name in ("ix_statement_batch_controls_batch", "ix_statement_batch_controls_created_by_id",
                 "ix_statement_batch_controls_tenant_id"):
        op.drop_index(name, table_name="statement_batch_controls")
    op.drop_table("statement_batch_controls")
