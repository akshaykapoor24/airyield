"""An invoice the platform raises to a workspace — Subscriptions → Generate invoice.

Not to be confused with `billings`: those are invoices a WORKSPACE raises to its own
customers, tenant-scoped, with ticket-shaped lines. These run the other way — the platform
is the supplier and the workspace is the recipient — and they are the platform's own sales
records, so nothing about them is scoped to, or owned by, the workspace billed.

THE ROW IS A SNAPSHOT
    `issuer` and `bill_to` are copied onto the row when the invoice is raised, and every
    figure is stored, never recomputed. An invoice is a legal document: editing a
    workspace's address next month, or the platform changing its bank, must not change
    paper that has already been sent. The PDF is rebuilt from the row on each download
    (services/platform_invoice_pdf.py) and comes out identical every time.

NUMBERED PER FINANCIAL YEAR, WITHOUT GAPS
    `FQ/26-27/0001` — a consecutive serial per Indian financial year (April–March), as
    GST invoicing rules expect. Allocated under a transaction-scoped advisory lock
    (services/platform_invoices.allocate_number), so two admins generating at once cannot
    collide and a failed insert does not burn a number. The unique constraints are the
    backstop, not the mechanism.

NEVER DELETED
    A wrong invoice is CANCELLED, keeping its number and a reason; a cancelled number is
    not reused. That is why there is no delete endpoint, and why `billed_tenant_id` is
    ON DELETE SET NULL: removing a workspace from the platform must not remove the record
    of what it was billed. `bill_to` still says who it was.

    For the same reason the column is deliberately NOT called `tenant_id` — the tenant
    deletion registry treats every `tenant_id` table as the workspace's own data, to be
    deleted with it. This table is the platform's.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STATUS_ISSUED = "issued"
STATUS_PAID = "paid"
STATUS_CANCELLED = "cancelled"
STATUSES = (STATUS_ISSUED, STATUS_PAID, STATUS_CANCELLED)

# The same vocabulary as billings.gst_treatment, plus 'none' for a supplier with no GSTIN,
# which may not charge GST at all.
TREATMENT_INTRA = "cgst_sgst"
TREATMENT_INTER = "igst"
TREATMENT_NONE = "none"


class PlatformInvoice(Base):
    __tablename__ = "platform_invoices"
    __table_args__ = (
        UniqueConstraint("financial_year", "serial", name="uq_platform_invoices_fy_serial"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")",
            name="ck_platform_invoices_status",
        ),
        CheckConstraint(
            f"gst_treatment IN ('{TREATMENT_INTRA}', '{TREATMENT_INTER}', '{TREATMENT_NONE}')",
            name="ck_platform_invoices_treatment",
        ),
        # A workspace's invoice history, newest first.
        Index("ix_platform_invoices_tenant_date", "billed_tenant_id", "invoice_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    financial_year: Mapped[str] = mapped_column(String(5), nullable=False)      # "26-27"
    serial: Mapped[int] = mapped_column(Integer, nullable=False)

    billed_tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=STATUS_ISSUED)

    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # {name, address, city, state, pincode, country, gstin, pan, email, phone,
    #  bank: {account_name, account_number, ifsc, bank_name, branch, upi_id}}
    issuer: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {name, address, city, state, pincode, country, gstin, pan, email, phone}
    bill_to: Mapped[dict] = mapped_column(JSONB, nullable=False)

    gst_treatment: Mapped[str] = mapped_column(String(12), nullable=False)
    place_of_supply_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # [{description, sac, quantity, unit_price, amount}] — amounts as strings, exact.
    line_items: Mapped[list] = mapped_column(JSONB, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    sgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    igst: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Payment is recorded by hand — there is no gateway. `payment_reference` is whatever
    # identifies the money: a UTR, a cheque number, a UPI transaction id.
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The last time it was emailed, and to whom.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_to: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # SET NULL: the platform admin's account can go without taking the invoices with it.
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
