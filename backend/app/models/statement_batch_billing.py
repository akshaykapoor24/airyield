"""Billing state for one spec-driven statement upload — counters, the batch default party,
and the `ticket_statements` header the batch projects into.

WHY THIS TABLE EXISTS AT ALL. LCC Detailed keeps this on `lcc_detailed_batch`, its own
per-upload header row. The spec-driven types have no such row: an upload is nothing but the
rows sharing a `batch_id`, and `api/v1/statements.py::list_batches` derives the list with a
GROUP BY. Billing needs somewhere to hold what is true of the whole upload — how many rows
have a party, which party the unmatched ones fall back to, and the one statement header they
all project under — so this is that row, created lazily on the first billing write.

Keyed `(slug, batch_id)` with **no FK on the batch**, exactly like
`models/statement_batch_supplier.py`: there is no batch header row for one to point at.
Rows are removed explicitly when the upload is deleted (api/v1/statements.py::delete_batch).

NAMED FOR THE SLUG SPACE, not for NDC, even though NDC is the only type that uses it today.
`statement_spec.supports_billing` is what decides who does, and a second type opting in
should be a flag rather than a table rename. That costs nothing now.

`created_by_id` IS NOT DECORATIVE, and it is the one column
`statement_batch_suppliers` does not have. The `ndc` rows are scoped
`(tenant_id, created_by_id)` by `statements.py::_scope` — two users in one tenant can hold
separate uploads. A header keyed on the tenant alone would let one user's batch-default
party rewrite the other's rows.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
    UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Same vocabulary as ck_uploaded_tickets_customer_type (cust_party_01), so a party chosen
# here is always writable onto the projected ticket. 'agency' is listed for the CHECK's sake
# only — the NDC endpoints refuse it, because Agency Billing claims tickets through their
# statement header, not through this link.
PARTY_TYPES = ("agency", "corporate", "direct")


class StatementBatchBilling(Base):
    __tablename__ = "statement_batch_billing"
    __table_args__ = (
        # One billing header per upload, for the life of the upload.
        UniqueConstraint("slug", "batch_id", name="uq_statement_batch_billing_batch"),
        # And one `ticket_statements` row per upload — allocated once and reused, so
        # re-projecting refreshes that header instead of leaving a new one behind.
        UniqueConstraint("billing_batch_id", name="uq_statement_batch_billing_target"),
        CheckConstraint(
            "default_customer_type IS NULL OR default_customer_type IN "
            "('agency','corporate','direct')",
            name="ck_statement_batch_billing_party",
        ),
        Index("ix_statement_batch_billing_batch", "slug", "batch_id"),
        Index("ix_statement_batch_billing_status", "slug", "resolution_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True,
    )

    # The statement type, e.g. "ndc" — the same batch_id space is per-type.
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── counters, refreshed from the rows after every billing mutation ───────
    # Denormalised on purpose: they are what the uploads list's Billing column shows, and
    # that list must not run a per-batch aggregate.
    billable_rows:   Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    resolved_rows:   Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unresolved_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    projected_rows:  Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # DISTINCT tickets, which is the figure LCC has no equivalent of: several NDC rows roll
    # up into one ticket, so "78 rows in billing" and "41 tickets" are both true and the
    # screen has to be able to say which it means.
    projected_tickets: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    group_count:    Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latched_rows:   Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # orphan + ambiguous + unidentified — ancillary lines with no ticket to attach to. Real
    # money awaiting a human decision, so it is counted rather than quietly dropped.
    unlatched_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # ── the batch-level fallback party ───────────────────────────────────────
    # Applied to every row the resolver could not match, and the primary path in practice:
    # an airline export's passenger names rarely overlap the Customer master, so
    # "bill this whole file to X" is what usually resolves it.
    default_customer_type: Mapped[str | None] = mapped_column(String(12), nullable=True)
    default_customer_id:   Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True,
    )
    default_corporate_id:  Mapped[int | None] = mapped_column(
        Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True,
    )

    # none → resolved → projected. `send-to-billing` refuses while "none": nothing has a
    # party to bill yet, so it would be a no-op reported as a success.
    resolution_status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="none", server_default="none",
    )
    # The `ticket_statements.batch_id` this upload projects into.
    billing_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    resolved_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    projected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at:   Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=text("now()"),
    )
