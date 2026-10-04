"""Vendors data → Payment Module: what is owed, what was decided, and what was paid.

The reconciliation (models/payment_reconciliation.py) is a REPORT — recomputed wholesale on
every run. Everything a person decides, and every payment made, lives here instead and
survives any number of re-runs:

  vendor_accounts         Your customer ID at each vendor (the "Customer ID" column of a TP
                          GDS statement), confirmed once per vendor. What the step-3 vendor
                          check compares a new statement against. Not Agency Master's
                          Customer Code — that is your own reference in your own books.
  mo_vendor_corrections   "This MO ticket belongs to vendor X, not the vendor whose MO file
                          it sits in" (step 6C). Keyed by (MO upload, ticket); the next
                          reconciliation pairs the ticket with the right vendor's statement.
  payment_items           One per billed vendor ticket per vendor upload — the payment
                          ledger. A snapshot of the latest reconciliation plus the DECISION
                          (step 10) and the PAYMENT (step 12). Unpaid items of earlier
                          statements are what is carried forward (step 13).
  vendor_payments         A payment made to a vendor: date, mode, UTR/reference, amount, the
                          items it settled. Voiding one returns its items to unpaid.

Everything is scoped (tenant, created_by) like every statement and reconciliation table:
the person reconciling records Operations' decision, with an `ops_reference`.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# ── decisions ────────────────────────────────────────────────────────────────
DECISION_APPROVED = "approved"   # payable at `approved_amount`
DECISION_PENDING = "pending"     # needs Operations — not payable yet
DECISION_HELD = "held"           # disputed / on hold — carried forward
DECISION_EXCLUDED = "excluded"   # not payable (a duplicate, or removed from the statement)
DECISION_STATUSES = (DECISION_APPROVED, DECISION_PENDING, DECISION_HELD, DECISION_EXCLUDED)

SOURCE_AUTO = "auto"
SOURCE_USER = "user"

ACTION_AUTO_CLEAN = "auto_clean"           # matched, nothing to resolve
ACTION_AUTO_DUPLICATE = "auto_duplicate"   # billed before — ignored for payout (6B)
ACTION_PAY_SUGGESTED = "pay_suggested"     # vendor net − commission shortfall
ACTION_PAY_VENDOR = "pay_vendor"           # the vendor's net, as billed
ACTION_PAY_MO = "pay_mo"                   # our MO record's net
ACTION_PAY_CUSTOM = "pay_custom"           # an amount Operations agreed
ACTION_HOLD = "hold"
ACTION_EXCLUDE = "exclude"
USER_ACTIONS = (ACTION_PAY_SUGGESTED, ACTION_PAY_VENDOR, ACTION_PAY_MO, ACTION_PAY_CUSTOM,
                ACTION_HOLD, ACTION_EXCLUDE)

PAYMENT_COMPLETED = "completed"
PAYMENT_VOIDED = "voided"
PAYMENT_MODES = ("NEFT", "RTGS", "IMPS", "UPI", "Cheque", "Cash", "Other")


class VendorAccount(Base):
    __tablename__ = "vendor_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "created_by_id", "supplier_id", "account_id",
                         name="uq_vendor_accounts_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    # Normalised: trimmed, upper-cased, a spreadsheet's trailing ".0" dropped.
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MoVendorCorrection(Base):
    __tablename__ = "mo_vendor_corrections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "created_by_id", "mo_batch_id", "ticket_key",
                         name="uq_mo_vendor_corrections_ticket"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    # The MO upload the ticket sits in, and the ticket (the reconciliation's group key).
    mo_batch_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    ticket_key: Mapped[str] = mapped_column(String(160), nullable=False)
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    from_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    from_supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    to_supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_supplier_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # The vendor statement whose reconciliation revealed it.
    vendor_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VendorPayment(Base):
    __tablename__ = "vendor_payments"
    __table_args__ = (
        Index("ix_vendor_payments_supplier", "tenant_id", "created_by_id", "supplier_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)
    supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The statement this payment settles; NULL = a release of outstanding items on its own.
    vendor_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)   # UTR / cheque
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default=PAYMENT_COMPLETED)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaymentItem(Base):
    __tablename__ = "payment_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "created_by_id", "vendor_batch_id", "ticket_key",
                         name="uq_payment_items_ticket"),
        Index("ix_payment_items_supplier", "tenant_id", "created_by_id", "supplier_id"),
        Index("ix_payment_items_batch", "tenant_id", "created_by_id", "vendor_batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    vendor_source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    statement_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The reconciliation group key ("k:<serial>", "p:<pnr|pax>", "r:<row id>").
    ticket_key: Mapped[str] = mapped_column(String(160), nullable=False)
    mo_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── snapshot of the latest reconciliation ────────────────────────────────
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ticket_prefix: Mapped[str | None] = mapped_column(String(4), nullable=True)
    pax_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    airline_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(200), nullable=True)
    booking_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor_row_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    match_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    not_billed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mo_vendor_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    commission_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # A deal could apply but the row lacks what it depends on (class, sector…) — income is
    # not known yet, so the ticket waits for Operations rather than auto-approving.
    income_needs_data: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    commission_ran: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    vendor_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    mo_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    calc_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_shortfall: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # vendor net − commission shortfall: what the module proposes paying.
    suggested_payable: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── decision (step 10) ───────────────────────────────────────────────────
    decision_status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=DECISION_PENDING, index=True)
    decision_source: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=SOURCE_AUTO)
    decision_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    approved_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Why the system decided what it did, or why it is waiting ("Net differs from MO by …").
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    ops_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    decided_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── payment (step 12) ────────────────────────────────────────────────────
    payment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vendor_payments.id", ondelete="SET NULL"), nullable=True,
        index=True)
    paid_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # The ticket is no longer on its statement (the upload was re-processed or edited).
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
