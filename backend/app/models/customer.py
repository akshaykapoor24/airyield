from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Customer(Base):
    """A traveller maintained privately by an agency user — "Employee Master".

    Scoped per user: queries always filter by tenant_id + created_by_id.
    Markup config (type/value) is applied to the customer's sold tickets.

    WHO THEY WORK FOR. `corporate_id` is the link to Corporate Master: set, this
    person is an employee of that corporate and their tickets are what Corporate
    Billing bills; NULL, they are an individual / direct customer billed in their
    own right. Nullable is the meaningful state, not a missing one.

    `company` IS A MIRROR of the linked corporate's name, not an independent
    field, and the API writes it on every link/unlink (api/v1/customers.py) and
    re-writes it when a corporate is renamed (api/v1/corporates.py). It exists
    because the billing PDF, the counterparty directory, the search filter and
    the statement panels all read a party's company as a STRING and none of them
    can join; keeping it in step is cheaper than teaching all of them the join.
    A row with a `company` but no `corporate_id` is a pre-link free-text value.
    """
    __tablename__ = "customers"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    first_name:    Mapped[str]        = mapped_column(String(200), nullable=False)
    last_name:     Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Deleting a corporate does not delete its people — they become individuals.
    corporate_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True, index=True)
    company:       Mapped[str | None] = mapped_column(String(255), nullable=True)   # mirror of corporates.company — see docstring
    title:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone:         Mapped[str | None] = mapped_column(String(50),  nullable=True)
    email:         Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Note: customer-local naming (gst_no / pan_no). The User/tenant/supplier models
    # use gst_number / pan_number — intentionally NOT unified; only the frontend regexes are shared.
    gst_registered: Mapped[bool]      = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    gst_no:        Mapped[str | None] = mapped_column(String(30),  nullable=True)   # only set when gst_registered
    pan_no:        Mapped[str | None] = mapped_column(String(20),  nullable=True)   # optional

    markup_type:   Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'percentage' | 'fixed'
    markup_value:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    billing_type:  Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'reseller' | 'agency'

    is_active:     Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
