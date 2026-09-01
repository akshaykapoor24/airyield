"""Which of the tenant's airline ids a spec-driven statement upload covers.

The LCC types (DI, Divided PNR, Flown Report, CTA/BTA) name no carrier in the file,
exactly like LCC Detailed — so the uploader declares it from their Airline Master, and
may name several ids for that carrier. This is where that set lives for those types.

Why a SECOND table rather than reusing ``lcc_batch_airline_ids``: that one's FK points
at ``lcc_detailed_batch.batch_id``, and these types have no batch header table at all —
a "batch" is just a shared ``batch_id`` string across rows of e.g. ``lcc_di``, derived
with a GROUP BY (see api/v1/statements.py::list_batches). So the link is keyed by
``(slug, batch_id)`` with no FK on the batch, and carries its own ``tenant_id`` because
there is no header row to reach a workspace through.

Which types require this is declared per spec (``requires_airline_id`` in
services/statement_spec.py), NOT assumed here: the same upload endpoint serves TGQ
HMPR, NDC and the third-party types, whose statements do carry their own airline.
"""
from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StatementBatchAirlineId(Base):
    __tablename__ = "statement_batch_airline_ids"
    __table_args__ = (
        UniqueConstraint("slug", "batch_id", "tenant_airline_id",
                         name="uq_statement_batch_airline_ids_triple"),
        Index("ix_statement_batch_airline_ids_batch", "slug", "batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    # The statement type, e.g. "lcc-di" — the same batch_id space is per-type.
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    # No FK: there is no batch header table to point at. Rows are removed explicitly
    # when the upload is deleted (api/v1/statements.py::delete_batch).
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # CASCADE for the same reason as lcc_batch_airline_ids: a RESTRICT would let these
    # rows block the workspace-deletion group that owns `tenant_airlines`. The
    # user-facing protection is the in-use guard on DELETE /tenant-airlines/{pk}.
    tenant_airline_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenant_airlines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
