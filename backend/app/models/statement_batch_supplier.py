"""Which consolidator sent a third-party statement upload.

A third-party statement is issued BY a consolidator and the file never names them: the
sample GDS export's "Customer Name" column is the tenant's OWN name, as the consolidator's
customer. So the uploader declares it, and it is load-bearing — `services/deal_matching.py`'s
B2B supplier guard has nothing to compare against without it, and every row comes back
unmatched.

THE COUNTERPARTY IS A **SUPPLIER**, NOT AN AGENCY, and the distinction is the whole reason
this file replaced `statement_batch_agency.py`:

  * `suppliers` is the platform-admin master — one global directory of ~2,500 vendors, one
    row per branch, `code` unique. It is also where `deals.supplier_name` comes from
    (api/v1/deals.py's B2B form reads `/suppliers/`), so both sides of the match now key
    off the same list.
  * `agencies` is User-master data: a tenant's own onboarding of a vendor, SPLIT BY
    CHANNEL, so one supplier becomes two agency rows (GDS and LCC) with the same name.
    Attributing a statement to one of those was attributing it to half a relationship, and
    it could not line up with a deal that names a supplier.

Because a supplier row IS one branch, `supplier_id` alone identifies the counterparty —
there is no channel to disambiguate and no name ambiguity to guard against. (141 of the
2,340 supplier NAMES do repeat across branches, which is why the picker shows branch and
code, and why the id rather than the name is what is stored.)

Keyed `(slug, batch_id)` with **no FK on the batch**: the spec-driven types keep no batch
header row for one to point at. Rows are removed explicitly when the upload is deleted
(api/v1/statements.py::delete_batch).

UNIQUE ON `(slug, batch_id)`: a statement comes from exactly one consolidator, and
"several" would mean the commission run had to guess which deal applied.
"""
from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StatementBatchSupplier(Base):
    __tablename__ = "statement_batch_suppliers"
    __table_args__ = (
        UniqueConstraint("slug", "batch_id", name="uq_statement_batch_suppliers_batch"),
        Index("ix_statement_batch_suppliers_batch", "slug", "batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    # The statement type, e.g. "tp-gds" — the same batch_id space is per-type.
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # RESTRICT, not CASCADE. `suppliers` is global platform-admin data with no delete
    # endpoint, so this is a backstop against direct SQL rather than a workflow: removing a
    # vendor that a tenant's statements are attributed to would erase the provenance of
    # every commission figure derived from them, and failing loudly is the better outcome.
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True,
    )

    # SNAPSHOT, and the reason this is not a bare join row: it keeps the uploads list and
    # the commission screens readable without a join, and it keeps a renamed supplier from
    # rewriting what a past statement says about itself. `code` is the unique one — two
    # branches of one vendor share a name exactly.
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supplier_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
