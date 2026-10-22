"""A decision taken on one line of the Vendor ↔ Internal reconciliation.

The reconciliation itself is never stored (services/vendor_internal_recon.py computes it
on request from the statements loaded). What IS stored is the one thing the statements
cannot say: what the user decided about a line that does not agree — that the vendor's
GDS statement is wrong, that the internal statement is, or that the difference is
accepted as it stands.

KEYED BY CONTENT, NOT BY ROW ID. `item_key` is ticket + sale/refund + the vendor week and
the internal Doc No (services/vendor_internal_recon._item_key), so re-uploading the same
statement keeps the decision, while a line that gains a partner (the missing side
arrives in the next statement) gets a new key and is looked at afresh.

THE FIGURES ARE A SNAPSHOT. vendor_net / internal_net are what the line showed when it
was resolved. If either moves (a corrected statement re-uploaded), the decision no longer
describes what is on screen, so the line is shown open again with the old decision beside
it rather than staying silently closed.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DECISION_VENDOR_WRONG = "vendor_wrong"        # the GDS statement is wrong — raise it with the vendor
DECISION_INTERNAL_WRONG = "internal_wrong"    # the internal statement is wrong — correct our books
DECISION_ACCEPTED = "accepted"                # explained or agreed — nothing to correct
DECISIONS = (DECISION_VENDOR_WRONG, DECISION_INTERNAL_WRONG, DECISION_ACCEPTED)


class VendorInternalResolution(Base):
    __tablename__ = "vendor_internal_resolutions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "created_by_id", "item_key", name="uq_vendor_internal_resolution_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    item_key: Mapped[str] = mapped_column(String(500), nullable=False)
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # difference | vendor_only | internal_only — which case the line was in when resolved.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    vendor_net: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    internal_net: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # internal − vendor, as the line showed it.
    difference: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    resolved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
