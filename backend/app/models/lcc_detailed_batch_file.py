"""The source files behind one LCC Detailed upload — one row per file.

Most LCC exports are a single spreadsheet, and for those this table holds exactly one
row (``role='single'``) that mirrors the scalars still kept on the batch.

Air India Express is the reason it exists. AIX issues the same statement as TWO files
that only make sense joined on ``PNR`` ↔ ``RecordLocator``:

  * ``role='account'`` — one row per money movement (funds used, funds added, refunds,
    daily balance). Carries the payment method, the GST party and the transaction type,
    but no fares and no passengers.
  * ``role='pax'``     — one row per passenger per segment. Carries the passenger, the
    sectors and the full fare breakdown, but no payment and no GST.

Each file needs its OWN ``header_row`` and ``column_map``: they have different headers,
different header rows, and the mapping the user confirms for one says nothing about the
other. Keeping them here rather than adding ``file_url_2``/``column_map_2`` to the batch
follows the same shape as ``models/lcc_batch_airline_id.py`` and leaves room for a third
file without another migration.

``lcc_detailed_batch.file_url / header_row / column_map`` are NOT dropped — they stay
pointed at the PRIMARY file, which is what keeps every batch uploaded before this,
``/file-url``, ``/viewer-url`` and the batches list working unchanged.
"""
from sqlalchemy import ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# Roles a source file can play. 'single' is the pre-existing one-file upload; the other
# two are the halves of a two-file export. Declared here rather than in the merge
# service because the UniqueConstraint below is what actually enforces "at most one of
# each per batch".
ROLE_SINGLE = "single"
ROLE_ACCOUNT = "account"
ROLE_PAX = "pax"
FILE_ROLES = (ROLE_SINGLE, ROLE_ACCOUNT, ROLE_PAX)


class LccDetailedBatchFile(Base):
    __tablename__ = "lcc_detailed_batch_file"
    __table_args__ = (
        # One file per role per batch. This is the constraint that makes "two account
        # files" a 400 at upload instead of a silently half-ingested batch.
        UniqueConstraint("batch_id", "role", name="uq_lcc_detailed_batch_file_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # CASCADE: a file row is meaningless without its batch, and `delete_batch` relies
    # on the cascade for the DB side while it removes the GCS blobs itself.
    batch_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("lcc_detailed_batch.batch_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)

    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Role-namespaced GCS path: lcc-detailed/{tenant}/{batch}/{role}/{filename}. The
    # role segment matters — two AIX exports are routinely named alike, and a flat
    # path would have the second overwrite the first.
    file_url:    Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Pinned per file. The worker re-reads at exactly this row; re-detecting would
    # rename every column and silently invalidate `column_map` (see
    # services/spreadsheet.py::read_table).
    header_row:  Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    column_map:  Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # {standard_field: column}
    # The columns offered to the mapping UI for this file — POST-reshape for a pax
    # file, so the synthetic leg/name columns the merge invents are mappable too.
    xls_columns: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Source lines in this file, before the merge collapses them.
    row_count:   Mapped[int | None] = mapped_column(Integer, nullable=True)
