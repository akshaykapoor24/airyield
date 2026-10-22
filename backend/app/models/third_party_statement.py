"""A third-party statement upload — the header its lines in `third_party_*` belong to.

Before this table a Third Party GDS, LCC or API upload existed only as the rows that
happened to share a `batch_id`: the file name, the stored copy and the upload time were
repeated on every line, the uploads list was a GROUP BY over the whole table, and nothing
in the database said the lines belonged together. This row IS the statement;
`third_party_gds`, `third_party_lcc` and `third_party_api` hold its lines, and each line's
`batch_id` is a foreign key to here with ON DELETE CASCADE, so a line cannot outlive the
statement it came from.

ONE TABLE FOR ALL THREE TYPES, told apart by `slug`, rather than a header per type: the
three share one router, one uploads list and one delete, and every side table about an
upload (statement_batch_suppliers / _controls / _airline_ids / _billing) is already keyed
by `(slug, batch_id)` across types.

`batch_id` STAYS THE KEY. It is the uuid every downstream table already stores — commission
runs, the income board, the payment module — so making it the primary key gives each of
them a header to reach without changing any of them. Same shape as `lcc_detailed_batch`.

THE LINES STILL CARRY THEIR OWN COPY of source_file / file_url / uploaded_at, for now. About
a dozen readers outside the statements router (commission, payment reconciliation,
statement checks, report download, …) take them off the rows; they move to this table one
at a time and the row columns are dropped after the last. Until then this table is the
source of truth, and the row copies are written from the same values in the same
transaction.

`tenant_id` and `created_by_id` stay on the lines for good: every query on those tables is
scoped by both, and a join on every read to recover them would buy nothing.

THE PERIOD — `period_from` / `period_to`, the days the statement covers, as the uploader
declared them (read off the file name, or typed: services/statement_period.py). Third Party
GDS asks for it on every upload: its tickets are checked against it, and a period already
uploaded for the agency is asked about before the file is read (services/tp_gds_reupload.py).
NULL for LCC and API, which do not ask yet, and for uploads made before it was asked for
whose file name and Week column named none. Both or neither, and never backwards.

THE TALLY — `total_entries` = `new_entries` + `duplicate_entries`, entries only (the
statement's own OLD / BALANCE / payment lines are not entries). `new_entries` are the lines
saved as this statement's own — duplicates the user chose to save included, flagged on the
line; `duplicate_entries` are the lines of its file left out as duplicates of lines already
saved for the same agency (or of the file's own) — they are counted here and nowhere else. Only Third Party GDS compares, so LCC and API always
read 0. Written with the lines; deleting one line takes one off `new` and `total`.

THE DATE FORMATS — `date_formats`, the order the uploader declared each date column of the
file is written in, {field: "DMY" | "MDY" | "YMD"} (statement_spec.date_format_fields):
"05/08/2026" is 5 Aug from one consolidator and 8 May from another. Third Party GDS asks
for Booked Date and Date of Travel on every upload. Kept as the record of how the upload's
dates were read, and to pre-fill the agency's next upload — a consolidator writes its dates
the same way statement after statement. NULL for LCC and API, and for uploads made before
it was asked for, which were read day-first.
"""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# The statement types whose uploads have a header here. MO GDS shares their parser and
# their side tables but is the workspace's own record, not a third-party statement.
THIRD_PARTY_SLUGS: frozenset[str] = frozenset({"tp-gds", "tp-lcc", "tp-api"})


class ThirdPartyStatement(Base):
    __tablename__ = "third_party_statements"
    __table_args__ = (
        CheckConstraint(
            "slug IN (" + ", ".join(f"'{s}'" for s in sorted(THIRD_PARTY_SLUGS)) + ")",
            name="ck_third_party_statements_slug",
        ),
        # Both ends or neither, and never backwards.
        CheckConstraint(
            "(period_from IS NULL AND period_to IS NULL) OR "
            "(period_from IS NOT NULL AND period_to IS NOT NULL AND period_from <= period_to)",
            name="ck_third_party_statements_period",
        ),
        # The uploads list: one user's uploads of one type, newest first.
        Index("ix_third_party_statements_list", "tenant_id", "created_by_id", "slug", "uploaded_at"),
    )

    batch_id:      Mapped[str]        = mapped_column(String(100), primary_key=True)   # uuid4
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    slug:          Mapped[str]        = mapped_column(String(20), nullable=False)       # tp-gds | tp-lcc | tp-api

    source_file:   Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url:      Mapped[str | None] = mapped_column(String(1000), nullable=True)      # GCS blob path; None when storing failed
    uploaded_at:   Mapped[datetime]   = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # The statement period — see the module docstring.
    period_from:   Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to:     Mapped[date | None] = mapped_column(Date, nullable=True)

    # The declared date formats — see the module docstring.
    date_formats:  Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # The tally — see the module docstring.
    total_entries:     Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    duplicate_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_entries:       Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
