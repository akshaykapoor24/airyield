"""The tenant's own bank statements, and what each line was.

One `BankStatement` per uploaded file; one `BankStatementRow` per transaction in it. The
parsing lives in services/bank_statement.py, the linking rules in api/v1/bank_statements.py.

A DEPOSIT LINKED TO A PARTY IS MONEY RECEIVED FROM THEM. That is the whole point of the
table: Invoicing says what each corporate, employee and agency was billed; these links say
what they paid. Exactly one of corporate_id / customer_id / agency_id is set on a linked
row — the same shape `billings` uses, so "billed" and "received" group on the same keys.

AN AGENCY ALREADY HAS A MONEY RECORD — its ledger (models/agency_ledger.py), where
receipts can be entered by hand. So a deposit linked to an agency does not keep a second
copy of that fact: it POSTS a `receipt` into the ledger and remembers the entry in
`agency_ledger_id`. Unlinking posts the ledger's own reversal. Received-from-an-agency is
therefore always read from the ledger, and a receipt entered by hand and one linked from
the bank are counted once each, never twice.

`dedupe_key` IS WHAT STOPS A STATEMENT FROM BEING COUNTED TWICE. Uploading September
again, or August-to-September after August, would otherwise double every receipt in the
overlap. It is unique per user; the upload skips lines it has already seen and says how
many.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Read off the statement's own header block; any of them may be missing.
    bank_name:     Mapped[str | None] = mapped_column(String(100), nullable=True)   # from the IFSC prefix
    account_name:  Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_no:    Mapped[str | None] = mapped_column(String(50), nullable=True)
    ifsc:          Mapped[str | None] = mapped_column(String(20), nullable=True)
    branch:        Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency:      Mapped[str | None] = mapped_column(String(10), nullable=True)
    period_from:   Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to:     Mapped[date | None] = mapped_column(Date, nullable=True)

    file_name:     Mapped[str]        = mapped_column(String(255), nullable=False)
    # Snapshots taken at upload, so the list does not re-sum every statement's rows.
    row_count:         Mapped[int]     = mapped_column(Integer, nullable=False, default=0)
    duplicate_count:   Mapped[int]     = mapped_column(Integer, nullable=False, default=0)
    total_deposits:    Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_withdrawals: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)


class BankStatementRow(Base):
    __tablename__ = "bank_statement_rows"
    __table_args__ = (
        Index("uq_bank_statement_rows_dedupe", "created_by_id", "dedupe_key", unique=True),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    statement_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("bank_statements.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # ── As the bank wrote it ──
    line_no:       Mapped[int | None]      = mapped_column(Integer, nullable=True)        # S.N.
    tran_id:       Mapped[str | None]      = mapped_column(String(50), nullable=True)
    value_date:    Mapped[date | None]     = mapped_column(Date, nullable=True)
    txn_date:      Mapped[date | None]     = mapped_column(Date, nullable=True, index=True)
    posted_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cheque_ref:    Mapped[str | None]      = mapped_column(String(100), nullable=True)
    remarks:       Mapped[str]             = mapped_column(Text, nullable=False, default="")
    withdrawal:    Mapped[Decimal]         = mapped_column(Numeric(14, 2), nullable=False, default=0)
    deposit:       Mapped[Decimal]         = mapped_column(Numeric(14, 2), nullable=False, default=0)
    balance:       Mapped[Decimal | None]  = mapped_column(Numeric(14, 2), nullable=True)

    # ── Read out of the remarks at upload ──
    direction:     Mapped[str]        = mapped_column(String(3), nullable=False)          # in | out
    counterparty:  Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_mode:  Mapped[str | None] = mapped_column(String(20), nullable=True)          # neft | rtgs | imps | …
    reference:     Mapped[str | None] = mapped_column(String(100), nullable=True)         # UTR / RRN
    dedupe_key:    Mapped[str]        = mapped_column(String(255), nullable=False)

    # ── Decided by the user ──
    category:      Mapped[str]        = mapped_column(String(20), nullable=False)         # services/bank_statement.CATEGORIES
    party_type:    Mapped[str | None] = mapped_column(String(12), nullable=True)          # corporate | customer | agency
    corporate_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    agency_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True, index=True)
    # The receipt this row posted into the agency's ledger — see the module docstring.
    agency_ledger_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_ledger.id", ondelete="SET NULL"), nullable=True)
    note:          Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
