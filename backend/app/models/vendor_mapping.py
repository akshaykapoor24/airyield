"""A decision taken on one line of the Payment Module's Vendor Mapping.

Vendor Mapping (services/vendor_mapping.py) is never stored: it is computed on request, the
vendor's statement against the MO (Internal Statement's Booking / MO uploads). What IS stored
is what the user decided about a line that does not agree — the vendor billed a ticket the MO
does not have, at a fare the MO does not have, or one the MO files under another vendor:

    vendor_wrong   the vendor's bill is wrong — what is at risk is claimed back, not paid
    mo_wrong       the MO is wrong — pay as billed; the MO is corrected
    accepted       explained or agreed — pay as billed

KEPT APART FROM `vendor_internal_resolutions` (Reconciliation → Vendor Reconciliation), whose
lines are judged on their NET, commission included; a line here is judged on its FARE. The
same ticket can agree on one and not the other, so one table would reopen the other's
decisions.

KEYED BY CONTENT. `item_key` is the line's key from the matching (ticket + sale/refund + the
vendor's week + the MO's Doc No — services/vendor_internal_recon._item_key), so re-uploading
either statement keeps the decision. The figures are a SNAPSHOT: when the vendor's fare, the
MO's fare or the vendor's net moves, the decision no longer describes the line on screen, and
the line is open again with the old decision beside it.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

MAPPING_VENDOR_WRONG = "vendor_wrong"
MAPPING_MO_WRONG = "mo_wrong"
MAPPING_ACCEPTED = "accepted"
MAPPING_DECISIONS = (MAPPING_VENDOR_WRONG, MAPPING_MO_WRONG, MAPPING_ACCEPTED)


class VendorMappingDecision(Base):
    __tablename__ = "vendor_mapping_decisions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "created_by_id", "item_key", name="uq_vendor_mapping_decision_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    item_key: Mapped[str] = mapped_column(String(500), nullable=False)
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # fare_diff | not_in_mo | other_vendor — what the line was when it was decided.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The snapshot the decision was taken on.
    vendor_fare: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    mo_fare: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    vendor_net: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
