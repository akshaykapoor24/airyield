from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
