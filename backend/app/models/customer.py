from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
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
    __table_args__ = (
        # The first constraint this table has ever carried beyond its primary key. Partial,
        # because the code is optional and Postgres would otherwise treat every NULL as
        # distinct anyway; workspace-scoped rather than per-corporate, because a code that
        # means two people in one workspace is not an identifier — searching it would
        # return both, which is the ambiguity it exists to remove.
        #
        # The app-level register (services/party_dedupe) is the RULE and produces a sentence;
        # this is the backstop that catches a concurrent insert the register cannot see.
        Index(
            "uq_customers_employee_code",
            "tenant_id", "created_by_id", "employee_code",
            unique=True,
            postgresql_where=text("employee_code IS NOT NULL"),
        ),
    )

    id:            Mapped[int]      = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    first_name:    Mapped[str]        = mapped_column(String(200), nullable=False)
    last_name:     Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Deleting a corporate does not delete its people — they become individuals.
    corporate_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True, index=True)
    company:       Mapped[str | None] = mapped_column(String(255), nullable=True)   # mirror of corporates.company — see docstring
    # The customer's own identifier for this person — a payroll id, a staff number. Optional,
    # and the ONLY thing that can tell two employees of one name apart: everything else on
    # this row is either the name itself or inherited from the corporate (phone, email,
    # gst_no, pan_no), so two colleagues legitimately share it. Stored trimmed and uppercased
    # like gst_no/pan_no, which is what makes the unique index case-insensitive in effect.
    # See services/party_dedupe.CustomerDuplicates.
    employee_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone:         Mapped[str | None] = mapped_column(String(50),  nullable=True)
    email:         Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Note: customer-local naming (gst_no / pan_no). The User/tenant/supplier models
    # use gst_number / pan_number — intentionally NOT unified; only the frontend regexes are shared.
    # The only geographic field this table carries, and it exists for one reason:
    # place of supply. A direct customer with no GSTIN has no other way to say
    # which state they are in, and that decides CGST+SGST versus IGST. Named and
    # sized to match corporates.state, the other side of the same comparison.
    state:         Mapped[str | None] = mapped_column(String(100), nullable=True)

    gst_registered: Mapped[bool]      = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    gst_no:        Mapped[str | None] = mapped_column(String(30),  nullable=True)   # only set when gst_registered
    pan_no:        Mapped[str | None] = mapped_column(String(20),  nullable=True)   # optional

    # The DEFAULT markup — what a line is charged unless its category overrides it below.
    markup_type:   Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'percentage' | 'fixed'
    markup_value:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Per-category overrides: {"hotel": {"type": "percentage", "value": 5}}, keyed by
    # services/markup_categories.CATEGORY_SLUGS. NULL means "no overrides" — and NULL, not
    # {}, so the two are never separate spellings of one state (services/party_markup and
    # services/party_inherit.is_blank both rely on that). Resolved by party_markup.markup_for.
    category_markups: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    billing_type:  Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'reseller' | 'agency'

    is_active:     Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
