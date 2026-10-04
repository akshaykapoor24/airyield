"""The control figures of one statement upload — what its completeness is checked against.

Vendors data → Payment Module step 2/5: "validate completeness by checking count of records
and amount of records for every statement loaded". The spec-driven types keep no batch
header row, so these figures need a home of their own, one row per upload, exactly like
`statement_batch_billing`:

  * `file_rows` / `loaded_rows` — data lines read from the file vs rows written. Captured
    at ingest because neither is recoverable afterwards: blank lines are dropped on read,
    and rows can later be deleted or re-processed.
  * `opening_balance` / `closing_balance` — the statement's own OLD and BALANCE lines. The
    OLD line sits ABOVE the header and is otherwise discarded with the preamble, so this is
    the only place it survives. `opening_source` says whether the file printed it or the
    user typed it in (an upload made before this table existed).
  * `expected_count` / `expected_amount` — what the uploader says the statement should hold
    (the vendor's covering note), optional, the same idea as LCC Detailed's `expected_rows`.

Money is NUMERIC(20,4): real nets carry four decimals (-28267.7162) and the opening +
Σ net = closing identity is only exact at the file's own precision.

Keyed `(slug, batch_id)` with no FK on the batch — the spec tables have no header row to
point at. Removed explicitly in `api/v1/statements.py::delete_batch`.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StatementBatchControl(Base):
    __tablename__ = "statement_batch_controls"
    __table_args__ = (
        UniqueConstraint("slug", "batch_id", name="uq_statement_batch_controls_batch"),
        Index("ix_statement_batch_controls_batch", "slug", "batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # The uploader — the rows themselves are scoped by created_by_id, so this is too.
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)

    file_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loaded_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    header_row: Mapped[int | None] = mapped_column(Integer, nullable=True)

    opening_balance: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    opening_source: Mapped[str | None] = mapped_column(String(8), nullable=True)   # file|user
    closing_balance: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)

    expected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_amount: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
