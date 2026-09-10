"""Spec-driven vendor statement tables — one dedicated table per type.

Each statement type gets its OWN table (so its data is easy to find/query):
``tgq_hmpr`` now; NDC / LCC / GDS later. They share a mixin — provenance + a ``data``
JSONB (the fixed columns, keyed by the spec's normalized field names) + a ``taxes``
JSONB array (the folded ``Tax_TypeN`` / ``TaxN`` pairs, so any number of taxes is
supported with no fixed Tax1..Tax20 columns). Slug → dedicated model via
``STATEMENT_MODELS`` (same pattern as ``ADJUSTMENT_MODELS`` for ADM/ACM/RA).
"""
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class _StatementBase:
    """Shared scaffolding for every spec-driven statement table."""

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Provenance — one batch_id per uploaded file.
    batch_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)
    source_file:   Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url:      Mapped[str | None] = mapped_column(String(1000), nullable=True)   # GCS blob path of the uploaded XLS
    uploaded_at:   Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Fixed columns (keyed by spec field name) + folded taxes (any count).
    data:          Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    taxes:         Mapped[list | None] = mapped_column(JSONB, nullable=True)


class _SplitMixin:
    """Per-sector leg expansion + declared-grand-total marking (airline ticket types).

    An airline statement line covers a whole ticket; ingest expands it into one row per
    flown sector with the money allocated across the legs (services/sector_split.py).
    Applied only to the ticket-shaped tables — the ledger-shaped ones have no sectors.

    ``orig_data``/``orig_taxes`` deliberately do NOT reuse ``_NormalizedBase.raw_data``:
    that name means *pre-normalization*, this means *pre-split*, and declaring the same
    mapped_column in two places on one MRO is a trap. Keeping them distinct also lets a
    batch be re-split later (e.g. under a different allocation rule) without re-upload.
    """

    row_seq:      Mapped[int | None]  = mapped_column(Integer, nullable=True)   # 1-based source line
    sector_index: Mapped[int | None]  = mapped_column(Integer, nullable=True)   # 1-based leg ("2" of 2/4)
    sector_count: Mapped[int | None]  = mapped_column(Integer, nullable=True)   # NULL ⇒ never processed
    split_status: Mapped[str | None]  = mapped_column(String(20), nullable=True)  # single|split|split_partial|unparsed|total
    is_total:     Mapped[bool]        = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # none_as_null: without it SQLAlchemy writes Python None as the JSON scalar `null`,
    # which is NOT SQL NULL — `orig_data IS NULL` would never match and
    # `coalesce(orig_data, data)` would resolve to JSON null instead of falling through.
    orig_data:    Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)  # pre-split row, verbatim
    orig_taxes:   Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)


class _BillingMixin:
    """Party resolution + the roll-up verdict + the projection back-link.

    ON `Ndc` ALONE, and that is the point. `_StatementBase` is shared by eight tables; these
    thirteen columns on all of them would be 24 foreign keys and a model layer claiming every
    statement type is billable while `statement_spec.supports_billing` says one is. A second
    type opts in by adding this mixin to its class and one `add_column` migration.

    IF A SECOND CLASS EVER ADOPTS THIS, every column carrying a `ForeignKey` must first
    become a `@declared_attr`: a single `mapped_column` instance cannot be shared between
    two mappers, and SQLAlchemy fails at import time rather than at runtime. It is a
    single-user mixin today by design, not by accident.

    See services/ndc_billing_projection.py for what writes each column.
    """

    # ── who this row is billed to ────────────────────────────────────────────
    bill_kind:          Mapped[str | None] = mapped_column(String(12), nullable=True)   # sale|refund|payment
    bill_status:        Mapped[str]        = mapped_column(String(16), nullable=False, default="unresolved", server_default="unresolved")
    bill_customer_type: Mapped[str | None] = mapped_column(String(12), nullable=True)   # agency|corporate|direct
    bill_customer_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    bill_corporate_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True)
    bill_match_reason:  Mapped[str | None] = mapped_column(String(300), nullable=True)

    # ── the roll-up: which ticket this row's money belongs to ────────────────
    # An NDC export writes ancillaries as their own document-less lines. `bill_group_key`
    # is "D:<document no>" for a real ticket or "O:<row id>" for a line that could not be
    # attached to one; exactly one row per group carries `bill_is_anchor`.
    bill_group_key:     Mapped[str | None] = mapped_column(String(64), nullable=True)
    bill_is_anchor:     Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    bill_latch_status:  Mapped[str | None] = mapped_column(String(12), nullable=True)   # anchor|latched|orphan|ambiguous|unidentified
    # This row's own signed settled figure. NO LCC COUNTERPART, and it earns its place: NDC
    # amounts are verbatim STRINGS in `data`, so without it the worklist's amount column,
    # the summary totals and the projection would each re-parse `data->>'payment_amount'`
    # through a CASE guard and could disagree. NULL means the cell would not parse — which
    # is visible on screen, rather than silently 0.
    bill_amount:        Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── the projection ───────────────────────────────────────────────────────
    # THE idempotency key. Every row in a group carries the SAME ticket id, read off the
    # anchor — re-sending syncs rather than duplicating. Not the ticket number: re-uploading
    # one file legitimately repeats it, and a natural key would merge two uploads.
    projected_ticket_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("uploaded_tickets.id", ondelete="SET NULL"), nullable=True)

    resolved_at:    Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_id: Mapped[int | None]      = mapped_column(Integer, ForeignKey("users.id"), nullable=True)


class TgqHmpr(_SplitMixin, _StatementBase, Base):
    """TGQ HMPR statement rows — one row per flown sector (see _SplitMixin)."""
    __tablename__ = "tgq_hmpr"


class Ndc(_BillingMixin, _SplitMixin, _StatementBase, Base):
    """NDC statement rows — one row per transaction line (splitting available, not yet
    enabled in statement_spec.STATEMENT_SPECS["ndc"]).

    The only spec-driven type that feeds billing — hence `_BillingMixin`. Its rows are
    resolved to a Customer/Corporate, rolled up per document number, and projected into
    `uploaded_tickets`; see services/ndc_billing_projection.py."""
    __tablename__ = "ndc"


class _NormalizedBase(_StatementBase):
    """Adds the normalized-statement columns for multi-format types (LCC Detailed, DI, …):
    `data` holds canonical common fields; `taxes`/`segments`/`ssr` are folded JSONB arrays;
    `raw_data` preserves the original row verbatim; `source_format` is the detected format.
    Simple types (e.g. DI) just leave taxes/segments/ssr null."""

    source_format: Mapped[str | None]  = mapped_column(String(40), nullable=True)
    segments:      Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [{leg, route, flight_no, dep_date}]
    ssr:           Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [{code, amount}]
    raw_data:      Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # original row, verbatim


class LccDi(_NormalizedBase, Base):
    """LCC DI (Deposit) Statement — one normalized deposit/transaction row from either the
    deposit-ledger or agency-ledger format. See services/di_statement.py."""
    __tablename__ = "lcc_di"


class LccDividedPnr(_NormalizedBase, Base):
    """LCC Divided PNR Statement — one normalized parent→child PNR split row.
    See services/divided_pnr.py."""
    __tablename__ = "lcc_divided_pnr"


class LccFlownReport(_NormalizedBase, Base):
    """LCC Flown Report — one normalized flown (uplifted) segment/ticket row.
    See services/flown_report.py."""
    __tablename__ = "lcc_flown_report"


class LccCtaBta(_NormalizedBase, Base):
    """LCC CTA/BTA Report — one normalized lodged-account (Central/Business Travel
    Account) settlement transaction. See services/cta_bta_report.py."""
    __tablename__ = "lcc_cta_bta"


class ThirdPartyGds(_NormalizedBase, Base):
    """Third Party GDS Statement — a consolidator's GDS statement to a sub-agency.
    See services/flat_statement.py (tp-gds)."""
    __tablename__ = "third_party_gds"


class ThirdPartyLcc(_NormalizedBase, Base):
    """Third Party LCC Statement — a consolidator's LCC statement to a sub-agency.
    See services/flat_statement.py (tp-lcc)."""
    __tablename__ = "third_party_lcc"


# slug → its dedicated table/model. Add a new type here (+ a spec entry + a migration).
STATEMENT_MODELS: dict[str, type] = {
    "tgq-hmpr": TgqHmpr,
    "ndc": Ndc,
    # lcc-detailed now has its own dedicated batch+rows schema (models/lcc_detailed.py)
    # and router (api/v1/lcc_detailed.py) — no longer routed through the generic table.
    "lcc-di": LccDi,
    "lcc-divided-pnr": LccDividedPnr,
    "lcc-flown-report": LccFlownReport,
    "lcc-cta-bta": LccCtaBta,
    "tp-gds": ThirdPartyGds,
    "tp-lcc": ThirdPartyLcc,
}
