from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class SupplierApproval(Base):
    __tablename__ = "supplier_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branches:    Mapped[list | None] = mapped_column(JSON, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alternate_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    alternate_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- Directory / member-list fields (from supplier master XLS) ---
    region_chapter: Mapped[str | None] = mapped_column(Text, nullable=True)
    membership_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_3: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    telephone_mobile: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternate_email_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    accounts_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    fax_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    representative_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    representative_2: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending")

    submitted_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_type: Mapped[str] = mapped_column(String(10), default="new")
    target_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )

    # ── platform-admin edit before approval ────────────────────────────────
    # Snapshot of the business columns as the submitter left them, written on
    # the FIRST admin edit only. NULL means no admin changed anything.
    original_payload: Mapped[dict | None]     = mapped_column(JSONB, nullable=True)
    edited_by_id:     Mapped[int | None]      = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    edited_at:        Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    submitted_by: Mapped["User"] = relationship("User", foreign_keys=[submitted_by_id])  # noqa: F821
    reviewed_by: Mapped["User"] = relationship("User", foreign_keys=[reviewed_by_id])  # noqa: F821
    edited_by: Mapped["User"] = relationship("User", foreign_keys=[edited_by_id])  # noqa: F821
