"""A column mapping the user saved a statement with — remembered for that vendor's next file.

The mapping step (components/statements/StatementUploadWizard.tsx) asks "which of your
columns is the Basic Fare". A vendor sends the same layout week after week, so the answer
is the same week after week, and asking it again is the whole cost of an upload. When a
statement is SAVED, its mapping is kept here; when the same vendor's next file is read, it
is proposed instead of the name-matching guess (services/saved_mapping.py).

ONE ROW PER (user, type, vendor, column layout). Keyed by layout as well as vendor because
a vendor can send more than one — a weekly ticket statement and a monthly ledger — and the
second must not overwrite the first. `signature` is the layout: the file's column names,
normalised and sorted, hashed. Saving the same vendor's same layout again updates the row.

Scoped to the uploader like everything it serves: `agencies` is each user's own copy of a
vendor, and statements are listed per `created_by_id` (api/v1/statements.py::_scope).

The vendor ids are SET NULL, not CASCADE: an agency deleted and onboarded again shares its
supplier id, and a row left with neither id still serves as a layout match.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StatementColumnMapping(Base):
    __tablename__ = "statement_column_mappings"
    __table_args__ = (
        Index("ix_statement_column_mappings_owner", "tenant_id", "created_by_id", "slug"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    slug:          Mapped[str]        = mapped_column(String(40), nullable=False)       # "tp-gds"

    # The vendor, as the upload named it (statement_batch_suppliers' two ids). Both NULL for
    # a type that names no vendor (NDC) — such a mapping is only ever reused on an exact layout.
    supplier_id:   Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    agency_id:     Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True)
    vendor_name:   Mapped[str | None] = mapped_column(String(255), nullable=True)      # snapshot, for "whose mapping"

    signature:     Mapped[str]        = mapped_column(String(64), nullable=False)       # the column layout
    columns:       Mapped[list]       = mapped_column(JSONB, nullable=False)            # the file's columns, as printed
    column_map:    Mapped[dict]       = mapped_column(JSONB, nullable=False)            # {field: column}

    # The statement it was last saved with — what the wizard names ("from TripJack.xlsx").
    source_file:   Mapped[str | None] = mapped_column(String(500), nullable=True)
    batch_id:      Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
