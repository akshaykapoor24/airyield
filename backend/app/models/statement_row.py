"""Spec-driven statement tables — one dedicated table per type.

Each statement type gets its OWN table (so its data is easy to find/query):
``tgq_hmpr`` now; NDC / LCC / GDS later. They share a mixin — provenance + a ``data``
JSONB (the fixed columns, keyed by the spec's normalized field names) + a ``taxes``
JSONB array (the folded ``Tax_TypeN`` / ``TaxN`` pairs, so any number of taxes is
supported with no fixed Tax1..Tax20 columns). Slug → dedicated model via
``STATEMENT_MODELS`` (same pattern as ``ADJUSTMENT_MODELS`` for ADM/ACM/RA).

THIRD PARTY GDS IS THE EXCEPTION: one typed column per field and no JSONB at all, with
``data`` rebuilt over the columns so its readers are unchanged — see ``ThirdPartyGds`` and
models/typed_statement.py.

NOT EVERY TYPE HERE IS A VENDOR STATEMENT. ``mo-gds`` is the workspace's OWN mid-office
record, uploaded under Vendors data → Payment Module to be checked against the vendor's
bill. It shares this registry because it shares the router, the parser and the upload
wizard — not because it is something a vendor sent. Code that means "what a vendor sent"
(the report download, the revenue board, commission) keeps its own explicit slug list
rather than looping over this dict.
"""
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, Integer, Boolean, CheckConstraint, ForeignKey, Index, Numeric, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.typed_statement import TypedData


class _Provenance:
    """Who uploaded a line, and from which file — on every statement table."""

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Provenance — one batch_id per uploaded file.
    batch_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)
    source_file:   Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url:      Mapped[str | None] = mapped_column(String(1000), nullable=True)   # GCS blob path of the uploaded XLS
    uploaded_at:   Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, index=True)


class _StatementBase(_Provenance):
    """Shared scaffolding for every spec-driven statement table that keeps its fields in JSONB."""

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
    """Party resolution + the row's own settled figure + the projection back-link.

    On `Ndc` and `ThirdPartyApi`. NOT on `_StatementBase`: eight tables share that, and these
    ten columns on all of them would be a model layer claiming every statement type is
    billable while `statement_spec.supports_billing` says two are. A third type opts in by
    adding this mixin to its class and one `add_column` migration.

    AN EARLIER NOTE HERE CLAIMED a second class must first convert every `ForeignKey` column
    to `@declared_attr`, because "a single `mapped_column` instance cannot be shared between
    two mappers". That is NOT true for the four below, and the correction matters because the
    conversion buys nothing and costs readability. SQLAlchemy COPIES a mixin's columns per
    mapper — `orm/decl_base.py:1445`, `column_copies[obj] = obj._copy()` — foreign keys
    included, so `Ndc` and `ThirdPartyApi` each get their own column object pointing at
    `customers.id`. The one shape that genuinely needs `@declared_attr` is a ForeignKey naming
    a Column OBJECT rather than a `"table.column"` STRING (decl_base.py:1425-1443), which
    raises at import; all four here are strings. Verified on SQLAlchemy 2.0.49.

    See services/ndc_billing_projection.py and services/tp_api_billing_projection.py for what
    writes each column.
    """

    # ── who this row is billed to ────────────────────────────────────────────
    bill_kind:          Mapped[str | None] = mapped_column(String(12), nullable=True)   # sale|refund|payment
    bill_status:        Mapped[str]        = mapped_column(String(16), nullable=False, default="unresolved", server_default="unresolved")
    bill_customer_type: Mapped[str | None] = mapped_column(String(12), nullable=True)   # agency|corporate|direct
    bill_customer_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    bill_corporate_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True)
    bill_match_reason:  Mapped[str | None] = mapped_column(String(300), nullable=True)

    # This row's own signed settled figure. NO LCC COUNTERPART, and it earns its place on the
    # two types that have it: their amounts are verbatim STRINGS in `data`, so without it the
    # worklist's amount column, the summary totals and the projection would each re-parse
    # `data->>'…'` through a CASE guard and could disagree. NULL means the cell would not
    # parse — which is visible on screen, rather than silently 0.
    bill_amount:        Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── the projection ───────────────────────────────────────────────────────
    # THE idempotency key. On NDC every row in a group carries the SAME ticket id, read off
    # the anchor; on Third Party API a row IS its own ticket. Either way, re-sending syncs
    # rather than duplicating. Not the ticket number: re-uploading one file legitimately
    # repeats it, and a natural key would merge two uploads.
    projected_ticket_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("uploaded_tickets.id", ondelete="SET NULL"), nullable=True)

    resolved_at:    Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_id: Mapped[int | None]      = mapped_column(Integer, ForeignKey("users.id"), nullable=True)


class _RollUpMixin:
    """Which ticket a row's money belongs to, when a row is NOT its own ticket.

    ON `Ndc` ALONE, and unlike `_BillingMixin` this one should stay there. An NDC export
    writes ancillaries — a paid seat, excess baggage, a meal — as their own document-less
    lines that have to be attached to the flight line before either can be invoiced.
    `bill_group_key` is "D:<document no>" for a real ticket or "O:<row id>" for a line that
    could not be attached to one; exactly one row per group carries `bill_is_anchor`.

    Split out of `_BillingMixin` when `ThirdPartyApi` adopted the billing columns. An
    aggregator booking IS one line and one ticket — MakeMyTrip and TBO bill a hotel night or
    a train berth on the booking's own row and issue no separate ancillary line — so these
    three would be NULL on every `third_party_api` row forever, and a
    `ck_*_bill_latch_status` CHECK there would police a vocabulary the table never uses.
    """

    bill_group_key:     Mapped[str | None] = mapped_column(String(64), nullable=True)
    bill_is_anchor:     Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    bill_latch_status:  Mapped[str | None] = mapped_column(String(12), nullable=True)   # anchor|latched|orphan|ambiguous|unidentified


class TgqHmpr(_SplitMixin, _StatementBase, Base):
    """TGQ HMPR statement rows — one row per flown sector (see _SplitMixin)."""
    __tablename__ = "tgq_hmpr"


class Ndc(_RollUpMixin, _BillingMixin, _SplitMixin, _StatementBase, Base):
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


class _ThirdPartyLine:
    """A line of one `third_party_statements` upload (models/third_party_statement.py).

    Redeclares `_StatementBase.batch_id` with the foreign key to its header. Listed FIRST
    among the bases so this is the declaration the mapper takes. CASCADE: a statement's
    lines are part of it, and deleting the statement is deleting them.
    """

    batch_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("third_party_statements.batch_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )


# The `data` keys of a Third Party GDS line whose column is named otherwise.
GDS_DATA_KEYS = {"total_tax": "taxes", "edited_fields": "__edited__"}


class _GdsLineFields:
    """The fields of one Third Party GDS line, a typed column each — shared by the lines a
    statement saves (`ThirdPartyGds`) and the ones its upload left out as repeats of a saved
    line (`ThirdPartyGdsLeftOut`), so both hold a line the same way and a field is added once.

    Column names are the parser's field names, so each is its `data` key; the comment on
    each is the header it is read from (the Third Party GDS template). Two differ:
    `total_tax` holds key `taxes` (the name every other table uses for its folded tax
    array) and `edited_fields` holds `__edited__` — `GDS_DATA_KEYS`, which each class names
    as its `DATA_KEYS` (a mixin's would lose to `TypedData`'s empty one).
    """

    # ── Dates ────────────────────────────────────────────────────────────────
    week:                Mapped[str | None]  = mapped_column(Text)                     # Week
    booking_date:        Mapped[date | None] = mapped_column(Date)                     # Booked / Issue Date
    transaction_date:    Mapped[date | None] = mapped_column(Date)                     # Transaction Date
    issue_date:          Mapped[date | None] = mapped_column(Date)                     # Issue Date (= Booked Date; no longer mapped on its own)
    travel_date:         Mapped[date | None] = mapped_column(Date)                     # Travel Date

    # ── Customer (no longer mapped — kept for the lines saved before) ─────────
    customer_name:       Mapped[str | None]  = mapped_column(Text)                     # Customer Name
    customer_id:         Mapped[str | None]  = mapped_column(Text)                     # Customer ID

    # ── Carrier ──────────────────────────────────────────────────────────────
    airline_name:        Mapped[str | None]  = mapped_column(Text)                     # Airline Name
    airline_code:        Mapped[str | None]  = mapped_column(Text)                     # Airline Code
    ticket_prefix:       Mapped[str | None]  = mapped_column(Text)                     # Ticket Prefix
    segment_type:        Mapped[str | None]  = mapped_column(Text)                     # Segment Type

    # ── Document ─────────────────────────────────────────────────────────────
    pnr:                 Mapped[str | None]  = mapped_column(Text)                     # S PNR
    airline_pnr:         Mapped[str | None]  = mapped_column(Text)                     # Airline PNR
    gds_pnr:             Mapped[str | None]  = mapped_column(Text)                     # CRS PNR
    ticket_number:       Mapped[str | None]  = mapped_column(Text)                     # Ticket No
    ticket_status:       Mapped[str | None]  = mapped_column(Text)                     # Invoice Type (sale / refund)
    transaction_type:    Mapped[str | None]  = mapped_column(Text)                     # not mapped (Invoice Type)
    booking_type:        Mapped[str | None]  = mapped_column(Text)                     # not mapped
    username:            Mapped[str | None]  = mapped_column(Text)                     # not mapped
    issuing_office:      Mapped[str | None]  = mapped_column(Text)                     # not mapped

    # ── Passenger ────────────────────────────────────────────────────────────
    pax_type:            Mapped[str | None]  = mapped_column(Text)                     # not mapped
    first_name:          Mapped[str | None]  = mapped_column(Text)                     # Pax First Name
    last_name:           Mapped[str | None]  = mapped_column(Text)                     # Pax Last Name
    passenger_name:      Mapped[str | None]  = mapped_column(Text)                     # Passenger (First + Last when not printed)
    passenger_count:     Mapped[int | None]  = mapped_column(Integer)                  # Pax Count

    # ── Itinerary ────────────────────────────────────────────────────────────
    sector:              Mapped[str | None]  = mapped_column(Text)                     # Sector
    flight_number:       Mapped[str | None]  = mapped_column(Text)                     # Flight No
    trip_type:           Mapped[str | None]  = mapped_column(Text)                     # not mapped
    travel_type:         Mapped[str | None]  = mapped_column(Text)                     # not mapped
    booking_class:       Mapped[str | None]  = mapped_column(Text)                     # Class
    payment_method:      Mapped[str | None]  = mapped_column(Text)                     # Payment Mode
    card_type:           Mapped[str | None]  = mapped_column(Text)                     # Card Type

    # ── Money ────────────────────────────────────────────────────────────────
    # NUMERIC with no scale: it keeps the file's own precision (-28267.7162, 99090.00),
    # which the opening + Σ net = closing identity is only exact at.
    currency:            Mapped[str | None]  = mapped_column(Text)                     # not mapped
    base_fare:           Mapped[float | None] = mapped_column(Numeric)                 # Basic Fare
    yq:                  Mapped[float | None] = mapped_column(Numeric)                 # YQ Tax
    yr:                  Mapped[float | None] = mapped_column(Numeric)                 # YR Tax
    k3:                  Mapped[float | None] = mapped_column(Numeric)                 # K3 Tax
    other_taxes:         Mapped[float | None] = mapped_column(Numeric)                 # Other Taxes
    total_tax:           Mapped[float | None] = mapped_column(Numeric)                 # Total Tax (YQ + YR + K3 + Other when not printed)
    seat_selection:      Mapped[float | None] = mapped_column(Numeric)                 # Seat Selection (SSR)
    excess_baggage:      Mapped[float | None] = mapped_column(Numeric)                 # Excess Baggage (SSR)
    meals:               Mapped[float | None] = mapped_column(Numeric)                 # Meals (SSR)
    ssr_amount:          Mapped[float | None] = mapped_column(Numeric)                 # SSR Amount (Seat + Baggage + Meals when not printed)
    reschedule_charges:  Mapped[float | None] = mapped_column(Numeric)                 # Reschedule Charges
    total_fare:          Mapped[float | None] = mapped_column(Numeric)                 # Total Fare
    adm:                 Mapped[float | None] = mapped_column(Numeric)                 # ADM
    commission_amount:   Mapped[float | None] = mapped_column(Numeric)                 # Agent Commission
    commission_rate:     Mapped[float | None] = mapped_column(Numeric)                 # Comm %
    incentive_amount:    Mapped[float | None] = mapped_column(Numeric)                 # Incentive
    discount:            Mapped[float | None] = mapped_column(Numeric)                 # Discount (DIS_Sell)
    tds:                 Mapped[float | None] = mapped_column(Numeric)                 # TDS Amount
    service_charge:      Mapped[float | None] = mapped_column(Numeric)                 # Service Charge
    service_fee:         Mapped[float | None] = mapped_column(Numeric)                 # SF
    cgst:                Mapped[float | None] = mapped_column(Numeric)                 # CGST (on SF)
    sgst:                Mapped[float | None] = mapped_column(Numeric)                 # SGST (on SF)
    igst:                Mapped[float | None] = mapped_column(Numeric)                 # IGST (on SF)
    gst_on_sf:           Mapped[float | None] = mapped_column(Numeric)                 # GST On SF (CGST + SGST + IGST when not printed)
    markup:              Mapped[float | None] = mapped_column(Numeric)                 # Markup
    agent_penalty:       Mapped[float | None] = mapped_column(Numeric)                 # Agent Penalty
    cancellation_markup: Mapped[float | None] = mapped_column(Numeric)                 # Cancellation Charges
    refund_amount:       Mapped[float | None] = mapped_column(Numeric)                 # Refund (RFD_SELL)
    uatp_amount:         Mapped[float | None] = mapped_column(Numeric)                 # UATP (paid by card to the airline)
    net_amount:          Mapped[float | None] = mapped_column(Numeric)                 # Net Amount

    # ── Other ────────────────────────────────────────────────────────────────
    invoice_number:      Mapped[str | None]  = mapped_column(Text)                     # Invoice No
    agency_code:         Mapped[str | None]  = mapped_column(Text)                     # Agency Code
    consolidator_name:   Mapped[str | None]  = mapped_column(Text)                     # Consolidator
    gds:                 Mapped[str | None]  = mapped_column(Text)                     # GDS
    payment_status:      Mapped[str | None]  = mapped_column(Text)                     # Payment Status
    remarks:             Mapped[str | None]  = mapped_column(Text)                     # Remarks

    # ── Set at ingest, not read from the file ────────────────────────────────
    issue_date_source:   Mapped[str | None]  = mapped_column(String(20))   # "booked_date": Issue Date was taken from Booked Date
    total_fare_source:   Mapped[str | None]  = mapped_column(String(20))   # "derived": Basic + Total Tax + SSR
    total_tax_source:    Mapped[str | None]  = mapped_column(String(20))   # "derived": YQ + YR + K3 + Other Taxes
    ssr_source:          Mapped[str | None]  = mapped_column(String(20))   # "derived": Seat + Baggage + Meals
    gst_source:          Mapped[str | None]  = mapped_column(String(20))   # "derived": CGST + SGST + IGST
    date_parse_failed:   Mapped[str | None]  = mapped_column(String(40))   # the first date field the parser could not read
    row_kind:            Mapped[str | None]  = mapped_column(String(20))   # the statement's own OLD/BALANCE lines (services/statement_balance.py)
    row_label:           Mapped[str | None]  = mapped_column(Text)         # …and the label printed on that line
    airline_id:          Mapped[int | None]  = mapped_column(Integer)      # the Airline master row the carrier resolved to
    airline_master_name: Mapped[str | None]  = mapped_column(Text)         # …and its name (services/tp_airline_resolution.py)
    airline_conflict:    Mapped[str | None]  = mapped_column(Text)         # why the printed code and the prefix disagreed
    edited_fields:       Mapped[str | None]  = mapped_column(Text)         # cells corrected by hand, comma-separated
    unparsed_fields:     Mapped[str | None]  = mapped_column(Text)         # fields whose value did not fit the column's type


class ThirdPartyGds(TypedData, _ThirdPartyLine, _Provenance, _GdsLineFields, Base):
    """Third Party GDS Statement — a consolidator's GDS statement to a sub-agency, one row
    per line. See services/flat_statement.py (tp-gds).

    THE ONLY STATEMENT TABLE WITH A COLUMN PER FIELD. Every other one here keeps its fields
    in a JSONB `data` blob; this one stores each in its own typed column — dates as DATE,
    amounts as NUMERIC, the pax count as INTEGER — and keeps no JSON at all, not even the
    vendor's row verbatim (`raw_data` is gone, so a GDS upload cannot be Reprocessed; the
    file is re-uploaded instead). `data` is still there to READ and WRITE, built over these
    columns by `TypedData` (models/typed_statement.py), because about fifteen readers and
    Third Party LCC / MO GDS alongside it all speak `data["net_amount"]`.

    The field columns are `_GdsLineFields`; the lines of its file an upload left out as
    repeats are kept apart, in `ThirdPartyGdsLeftOut`.
    """
    __tablename__ = "third_party_gds"
    __table_args__ = (
        # A line's statement period, to read lines by period without the header.
        Index("ix_third_party_gds_period", "tenant_id", "period_from", "period_to"),
        # The lookups every upload makes: the agency's saved lines carrying one of the
        # file's keys (services/tp_gds_reupload.py).
        Index("ix_third_party_gds_dedup_key", "tenant_id", "created_by_id", "dedup_key"),
        Index("ix_third_party_gds_match_key", "tenant_id", "created_by_id", "match_key"),
        Index("ix_third_party_gds_ticket_number", "ticket_number"),
        CheckConstraint("duplicate_kind IS NULL OR duplicate_kind IN ('exact', 'partial', 'in_file')",
                        name="ck_third_party_gds_duplicate_kind"),
    )

    DATA_EXCLUDE = frozenset({"id", "tenant_id", "created_by_id", "batch_id", "source_file",
                              "file_url", "uploaded_at", "source_format", "dedup_key",
                              "period_from", "period_to", "match_key", "duplicate_kind",
                              "duplicate_of_id", "duplicate_fields"})
    DATA_KEYS = GDS_DATA_KEYS

    source_format: Mapped[str | None] = mapped_column(String(40), nullable=True)      # Format

    # Which line this is, exactly, and which entry (its ticket and event) — as the vendor
    # sent it: fixed at upload, before any correction on the review step and untouched by a
    # later cell edit, so a re-send is recognised (services/tp_gds_reupload.py). NULL on a
    # balance line; `match_key` NULL too on a line with no ticket and no PNR.
    dedup_key:   Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_key:   Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A line saved although it repeats one: "exact" (already saved, saved again by choice),
    # "partial" (the same entry with something changed) or "in_file" (an earlier line of its
    # own file). `duplicate_of_id` is the saved line it repeats — NULL for "in_file", and
    # once that line is deleted, when the flag goes with it — and `duplicate_fields` what
    # differs, comma-separated (services/tp_gds_reupload.DIFF_FIELDS). NULL on every other line.
    duplicate_kind:   Mapped[str | None] = mapped_column(String(20), nullable=True)
    duplicate_of_id:  Mapped[int | None] = mapped_column(
        Integer, ForeignKey("third_party_gds.id", ondelete="SET NULL", name="fk_third_party_gds_duplicate_of"),
        nullable=True, index=True)
    duplicate_fields: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The statement period of the upload this line belongs to — a copy of its header's
    # (models/third_party_statement.py), written with the line. NULL where the header has none.
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to:   Mapped[date | None] = mapped_column(Date, nullable=True)


class ThirdPartyGdsLeftOut(TypedData, _GdsLineFields, Base):
    """A line of a Third Party GDS statement's file that its upload did NOT save because it
    repeats a line already saved (services/tp_gds_reupload.py) — kept, so the statement still
    holds every line its file had.

    Before this table a left-out line survived only as a count (`third_party_statements.
    duplicate_entries`): a statement of 18 lines showed 4, and nothing could say which 14 the
    vendor had sent again or where they were reconciled. Each row here is the line exactly as
    the file had it, the statement it was on (`batch_id`), its file row, why it was left out
    (`kind`: exact | partial | in_file, the buckets of the review step) and the saved line it
    repeats (`repeat_of_id`) — the line that carries its money and its reconciliation
    (services/vendor_internal_recon.py). `differs` is what a partial or in-file repeat
    changed (tp_gds_reupload.DIFF_FIELDS); `dedup_key` / `match_key` its keys as the vendor
    sent it, like a saved line's.

    A TABLE OF ITS OWN, not a flag on `third_party_gds`: about fifteen readers — commission,
    the income board, the payment module, the report download, the statement grid — sum that
    table, and each would have to learn to skip a flagged line or count its money twice.
    Nothing reads this one but the reconciliation.

    `repeat_of_id` is SET NULL: the line it repeats can be deleted, with its statement, and
    this one then repeats nothing saved — uploading its statement again brings it back.
    CASCADE on `batch_id`: a statement's lines go with it, saved or left out.
    """
    __tablename__ = "third_party_gds_left_out"
    __table_args__ = (
        CheckConstraint("kind IN ('exact', 'partial', 'in_file')", name="ck_third_party_gds_left_out_kind"),
    )

    DATA_EXCLUDE = frozenset({"id", "tenant_id", "created_by_id", "batch_id", "file_row", "kind",
                              "repeat_of_id", "differs", "dedup_key", "match_key"})
    DATA_KEYS = GDS_DATA_KEYS

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    batch_id:      Mapped[str]        = mapped_column(
        String(100), ForeignKey("third_party_statements.batch_id", ondelete="CASCADE"), nullable=False, index=True)
    file_row:      Mapped[int | None] = mapped_column(Integer, nullable=True)      # the file row (0-based); NULL off the wizard
    kind:          Mapped[str]        = mapped_column(String(20), nullable=False)
    repeat_of_id:  Mapped[int | None] = mapped_column(
        Integer, ForeignKey("third_party_gds.id", ondelete="SET NULL"), nullable=True, index=True)
    differs:       Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key:     Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_key:     Mapped[str | None] = mapped_column(String(64), nullable=True)


class ThirdPartyLcc(_ThirdPartyLine, _NormalizedBase, Base):
    """Third Party LCC Statement — a consolidator's LCC statement to a sub-agency.
    See services/flat_statement.py (tp-lcc)."""
    __tablename__ = "third_party_lcc"


class ThirdPartyApi(_ThirdPartyLine, _BillingMixin, _NormalizedBase, Base):
    """Third Party API Statement — an aggregator's booking export (MakeMyTrip, TBO).
    See services/tp_api_spec.py (tp-api).

    THE ONLY MULTI-PRODUCT TABLE HERE. Every other type on this router is one row per
    airline ticket; one of these files carries hotel, flight, train, bus and car bookings
    side by side, and `data->>'product_type'` is what tells them apart. Products are NOT
    split into a table each: `data` is JSONB, so a train row simply has no `no_of_rooms`
    key and costs nothing for it — whereas five tables would make every total, filter,
    facet and delete on this router a five-way UNION, and would be the first place a batch
    is not one table's rows.

    `source_format` carries the vendor (`mmt-bookings-v1` / `tbo-statement-v1`), detected
    from the header row — the same use `lcc_di` makes of it for its two deposit formats.

    `_BillingMixin` BUT NOT `_RollUpMixin`: one booking is one row is one ticket here, so
    there is nothing to latch. Every CATEGORY is projected into billing, each ticket carrying
    its `product_category` — see services/tp_api_billing_projection.py, where `bill_kind`
    also records why a row is out (`no_category`, `pending`, `cancelled`, `needs_review`,
    `no_amount`) so the worklist can say so with the amount attached, rather than dropping
    it silently."""
    __tablename__ = "third_party_api"

    # ── pax: how many passengers this booking bills for ─────────────────────
    # Here and not in `_BillingMixin`: an NDC line is one passenger's document, so NDC has no
    # use for it. Stamped from `data.pax_count` at resolve time, or corrected by hand on the
    # worklist — `bill_pax_source='user'` is what lets that correction survive a Re-match.
    bill_pax_count:  Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bill_pax_source: Mapped[str | None] = mapped_column(String(8), nullable=True)   # file|default|user


class MidOfficeGds(_NormalizedBase, Base):
    """MO (mid-office / internal) statement — the workspace's own record of the bookings
    a consolidator billed, uploaded under Vendors data → Payment Module.

    Parsed with the Third Party GDS builder for now (services/flat_statement.py `tp-gds`),
    so it has exactly that table's shape. It is the OTHER side of the payment check in
    services/payment_reconciliation.py: the vendor's bill (`third_party_gds`) against what
    our own books say. Nothing else reads it — it is not a sale, not priced by commission
    income, and not part of the vendor-statement report.
    """
    __tablename__ = "mid_office_gds"


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
    "tp-api": ThirdPartyApi,
    # Payment Module's internal side — see MidOfficeGds and the module docstring.
    "mo-gds": MidOfficeGds,
}
