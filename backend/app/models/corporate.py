from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Corporate(Base):
    """A corporate client maintained privately by an agency user ("Corporate Billing").

    A CORPORATE IS AN ORGANISATION, NOT A PERSON. `company` is its name,
    `corporate_type` its legal form (proprietorship, private limited, LLP…), and
    it carries a postal address the way an agency branch does. Scoped per user
    (tenant_id + created_by_id), with markup config (type/value) applied to its
    sold tickets.

    `first_name` / `last_name` / `title` ARE LEGACY. This table began as a copy of
    Customer, which IS a person, so the contact's name lived there. Nothing writes
    them any more: corp_entity_01 copied that name into `company` wherever `company`
    was blank and made `first_name` nullable. They are still read so pre-split rows
    keep rendering, and so the passenger-name ticket match in the sold-tickets
    endpoint keeps working for them — a corporate added since the split matches no
    passenger by name and gets its tickets through its customers instead.
    """
    __tablename__ = "corporates"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    company:       Mapped[str | None] = mapped_column(String(255), nullable=True)   # the corporate's NAME — required by the API
    corporate_type: Mapped[str | None] = mapped_column(String(50), nullable=True)   # 'proprietorship' | 'private_limited' | … (see api/v1/corporates.py)

    first_name:    Mapped[str | None] = mapped_column(String(200), nullable=True)   # legacy, see docstring
    last_name:     Mapped[str | None] = mapped_column(String(200), nullable=True)   # legacy
    title:         Mapped[str | None] = mapped_column(String(100), nullable=True)   # legacy
    phone:         Mapped[str | None] = mapped_column(String(50),  nullable=True)
    email:         Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Registered address. Named to match agencies.address / state / city, with
    # pincode + country carried over from the supplier master's address block.
    address:       Mapped[str | None] = mapped_column(Text, nullable=True)
    city:          Mapped[str | None] = mapped_column(String(120), nullable=True)
    state:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode:       Mapped[str | None] = mapped_column(String(20),  nullable=True)
    country:       Mapped[str | None] = mapped_column(String(100), nullable=True)
    gst_registered: Mapped[bool]      = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    gst_no:        Mapped[str | None] = mapped_column(String(30),  nullable=True)   # only set when gst_registered
    pan_no:        Mapped[str | None] = mapped_column(String(20),  nullable=True)   # optional

    markup_type:   Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'percentage' | 'fixed'
    markup_value:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    billing_type:  Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'reseller' | 'agency'

    is_active:     Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
