"""Which of the tenant's airline ids an LCC Detailed upload covers.

A tenant holds several agent-portal ids per carrier (five Indigo logins across
offices is ordinary — see models/tenant_airline.py), and one statement routinely
covers more than one of them. The upload wizard therefore takes a SET of ids, and
this is where that set lives.

Every id in a batch's set belongs to the SAME airline — enforced in
``services/lcc_airline_selection.py``. That is what keeps the rest of the schema
untouched: ``lcc_detailed_batch.airline_id / airline_name / airline_code`` and the
per-row stamping in ``workers/lcc_tasks.py`` stay single-valued and correct, because
there is still exactly one carrier per batch. Only the *ids* are many.

The set records which of the user's logins the statement covers. It cannot say which
row belongs to which id — the file carries nothing to that effect, which is the same
reason the carrier has to be declared at upload in the first place.

``lcc_detailed_batch.tenant_airline_id`` / ``airline_ref_id`` remain as the PRIMARY
(first-selected) id, so the batches list, the id-usage count and every batch uploaded
before this existed keep working unchanged.
"""
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LccBatchAirlineId(Base):
    __tablename__ = "lcc_batch_airline_ids"
    __table_args__ = (
        UniqueConstraint("batch_id", "tenant_airline_id", name="uq_lcc_batch_airline_ids_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # CASCADE on both sides. On the batch because its links are meaningless without
    # it. On the airline id because a RESTRICT would let surviving link rows block
    # the workspace-deletion group that owns `tenant_airlines`, which
    # tests/test_tenant_deletion.py exists to prevent. The user-facing protection is
    # the in-use guard on DELETE /tenant-airlines/{pk}, not this constraint.
    batch_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("lcc_detailed_batch.batch_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_airline_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenant_airlines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
