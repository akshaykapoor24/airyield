from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Date, DateTime, Integer, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


# Money in from the agency is positive, value billed to them is negative.
ENTRY_TYPES = {
    "opening_balance",  # bringing an already-trading agency on board
    "topup",            # cash deposit / further deposit          (+)
    "receipt",          # payment received against an invoice     (+)
    "invoice",          # an agency billing was raised            (−)
    "refund",           # unused deposit paid back out            (−)
    "adjustment",       # write-off / write-back, either sign
    "reversal",         # cancels an earlier entry, either sign
}

# Entries that a user may post by hand. `invoice` is posted by the billing flow
# and `reversal` by the reverse action, so neither is offered as a free choice.
MANUAL_ENTRY_TYPES = {"opening_balance", "topup", "receipt", "refund", "adjustment"}

PAYMENT_MODES = {"neft", "rtgs", "imps", "upi", "cheque", "cash", "card", "other"}


class AgencyLedger(Base):
    """Append-only money movement on an agency's account.

    `amount` is SIGNED from the agency's point of view against us:
        +  money in from the agency   (topup, receipt)
        −  value billed to them       (invoice), or money paid back (refund)
        balance = SUM(amount)
        balance > 0  they hold credit with us (unused cash deposit)
        balance < 0  they owe us              (credit outstanding)

    The agency type only sets how far the balance may fall: cash stops at 0
    (they pay first), credit stops at −credit_limit. One convention serves both.

    `channel` IS NOT NULL AND THAT IS ARITHMETIC, NOT TIDINESS. Every balance read
    is now SUM(amount) WHERE channel = 'GDS'. A NULL-channel row would be excluded
    from that AND from the LCC sum, so the two per-channel balances would silently
    stop adding up to the agency's total — money that exists in the table and in
    no account. Deriving the channel from `terms_id` is not an option either:
    terms_id is ON DELETE SET NULL and is NULL for any entry posted before terms
    existed. The channel is denormalised here so a balance is one indexed scan.

    NOTHING HERE IS EVER UPDATED OR DELETED. A mistake is corrected by posting an
    opposite entry with `reversal_of_id` pointing at the original, so the trail
    survives. `invoice` rows are posted automatically when an agency billing is
    created and reversed when it is deleted, which is what keeps the ledger and
    `billings` from drifting apart.
    """
    __tablename__ = "agency_ledger"

    id:        Mapped[int]        = mapped_column(primary_key=True)
    agency_id: Mapped[int]        = mapped_column(Integer, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    terms_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_terms.id", ondelete="SET NULL"), nullable=True)

    channel:   Mapped[str]        = mapped_column(String(10), nullable=False)   # GDS | LCC — see docstring

    entry_date: Mapped[date]    = mapped_column(Date, nullable=False)
    entry_type: Mapped[str]     = mapped_column(String(20), nullable=False)
    amount:     Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    billing_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("billings.id", ondelete="SET NULL"), nullable=True)
    payment_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)   # UTR / cheque no
    note:         Mapped[str | None] = mapped_column(String(255), nullable=True)

    reversal_of_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_ledger.id", ondelete="SET NULL"), nullable=True)
    created_by_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at:     Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
