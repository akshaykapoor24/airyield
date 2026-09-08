"""Generic flat-statement normalizer for simple ledger types.

Many statement types are "flat": a per-row ledger normalized to canonical fields via a
tolerant alias map, with no folded taxes/segments/SSR. Rather than a near-duplicate module
per type, register a config here (display columns + alias map + a source-format label); the
router resolves a bound builder by parser name and calls the same `build_col_map(cols)` /
`build_row(row, cols)` interface as the per-type modules.

Currently hosts the **Third Party** types (a consolidator/big-agency sends the sub-agency a
GDS or LCC statement of the bookings it made through them).

**Third Party GDS is now mapped against a REAL consolidator export** — a 40-column sheet
whose money columns (`Basic Fare`, `YQ Fare`, `Other Taxes`, `Agent Commission`,
`Incentive`, `Net Amount`) none of the original speculative aliases reached. Those forty
headers are the ones marked "real export" below; everything else in the schema is the
earlier superset, kept so a differently-shaped consolidator file still parses exactly as it
did. **Third Party LCC is still speculative** — no real LCC export has been supplied; it
gets the shared fixes (alias collisions, ISO dates, passenger name) and nothing more.

Three things a reader should know before editing:

  1. `_FlatBuilder._a2c` inverts the alias map to `{alias: canonical}`. A string appearing
     under two canonical fields therefore resolves to whichever the dict defined LAST —
     silently. `register` now raises on that rather than letting it ship; three real
     collisions existed here (`status`, `service_charge`, `payment_mode`).
  2. Two source columns cannot both reach one canonical field: `build_col_map`'s
     `canon not in seen` guard keeps the first and drops the second. That is why
     First/Last Name are separate canonicals joined by `derive`, not two aliases of
     `passenger_name`.
  3. Dates and amounts are NORMALIZED into `data` (ISO-8601, no thousands separators) but
     left verbatim in `raw_data`. Downstream SQL depends on it: `plb_accrual` only buckets a
     date matching `^\\d{4}-\\d{2}-\\d{2}` and only casts an amount matching
     `^-?\\d+(\\.\\d+)?$`, so an un-normalized value is not a formatting nit — it is a row
     that silently drops out of the accrual.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Callable


def norm(header) -> str:
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


def _clean(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


# ── Value coercion ───────────────────────────────────────────────────────────
# Explicit formats first (deterministic and faster), dateutil as the fallback. Mirrors
# services/lcc_detailed_spec.py::_to_datetime, including `dayfirst=True`: an Indian
# consolidator prints 13-08-2026, and month-first would read that as invalid and
# 08-08-2026 as the wrong day for half the year.
_DT_FORMATS = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y",
    "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d-%b-%Y %H:%M:%S",
)

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def to_iso_date(value) -> str | None:
    """'08-08-2026' -> '2026-08-08'. Returns None when it is not a date at all.

    An unparseable cell yields None rather than a guess: the caller keeps the original in
    `raw_data`, and a wrong date silently shifts a ticket into another contract window.
    """
    s = _clean(value)
    if not s:
        return None
    if _ISO_RE.match(s):
        return s[:10]
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(s, dayfirst=True).date().isoformat()
    except Exception:  # noqa: BLE001 — a free-form cell from someone else's spreadsheet
        return None


_NUM_STRIP = re.compile(r"[,\s ₹$€£]")
_PAREN_NEG = re.compile(r"^\((.*)\)$")


def to_number_str(value) -> str | None:
    """'1,23,456.78' -> '123456.78'; '(285.72)' -> '-285.72'. None when not a number.

    Returns a STRING, not a float: `data` is JSONB read back as text by every downstream
    aggregate, and a float round-trip loses paise.
    """
    s = _clean(value)
    if s is None:
        return None
    m = _PAREN_NEG.match(s)
    neg = bool(m)
    if m:
        s = m.group(1)
    s = _NUM_STRIP.sub("", s)
    if s.endswith("-"):          # trailing-minus exports
        s, neg = s[:-1], True
    if not re.fullmatch(r"[+-]?\d*\.?\d+", s or ""):
        return None
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        s, neg = s[1:], not neg
    return f"-{s}" if neg and float(s) != 0 else s


def _f(data: dict, field: str) -> float:
    """A normalized amount as a float, 0 when absent — for derived sums only."""
    try:
        return float(data.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


class _FlatBuilder:
    """Bound builder — same interface as the per-type parser modules."""

    def __init__(self, display_columns: list[dict], aliases: dict[str, list[str]],
                 source_format: str, derive: Callable[[dict], None] | None = None):
        self.display_columns = display_columns
        self._a2c = {v: k for k, vs in aliases.items() for v in vs}
        self._fmt = source_format
        self._derive = derive

    def build_col_map(self, columns: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        seen: set[str] = set()
        for col in columns:
            canon = self._a2c.get(norm(col))
            if canon and canon not in seen:
                out[col] = canon
                seen.add(canon)
        return out

    def build_row(self, row, columns: list[str]) -> dict:
        vals = {c: _clean(row.get(c)) for c in columns}
        colmap = self.build_col_map(columns)
        data = {field: vals[col] for col, field in colmap.items() if vals.get(col) is not None}
        raw_data = {str(c): vals[c] for c in columns if vals.get(c) is not None}
        if self._derive is not None:
            self._derive(data)
        return {"source_format": self._fmt, "data": data, "taxes": [], "segments": [], "ssr": [], "raw_data": raw_data}

    def build_row_mapped(self, row, columns: list[str], column_map: dict[str, str],
                         overrides: dict[str, str] | None = None) -> dict:
        """Same row, but built from a mapping the USER chose rather than from the aliases.

        `column_map` is {canonical field: source column header} — the direction the mapping
        UI works in, since a person picks "which of my columns is the Basic Fare", not the
        reverse. A field mapped to a column the file does not have is dropped rather than
        stored empty: the mapping may have been made against a different export.

        `overrides` are per-row corrections made on the review step, applied AFTER the
        mapping and BEFORE `derive`, so a corrected date is still normalised to ISO and a
        corrected fare still feeds the derived total. An override of "" clears the field —
        that is how a reviewer deletes a value the sheet got wrong.

        `raw_data` stays the file's own columns verbatim, exactly as in `build_row`, so a
        later Reprocess re-reads the source rather than our interpretation of it.
        """
        vals = {c: _clean(row.get(c)) for c in columns}
        present = set(columns)
        data: dict = {}
        for field, col in (column_map or {}).items():
            if col in present and vals.get(col) is not None:
                data[field] = vals[col]
        for field, value in (overrides or {}).items():
            cleaned = _clean(value)
            if cleaned is None:
                data.pop(field, None)
            else:
                data[field] = cleaned
        raw_data = {str(c): vals[c] for c in columns if vals.get(c) is not None}
        if self._derive is not None:
            self._derive(data)
        return {"source_format": self._fmt, "data": data, "taxes": [], "segments": [], "ssr": [], "raw_data": raw_data}

    def suggest_mapping(self, columns: list[str]) -> dict[str, str]:
        """{canonical field: source column} — the alias map's own answer, as a starting
        point for the mapping UI. A file built from our template comes back fully mapped;
        anything else comes back partly mapped and the user fills the rest in."""
        return {field: col for col, field in self.build_col_map(columns).items()}


_REGISTRY: dict[str, _FlatBuilder] = {}


# Which section of the mapping screen a field belongs to, and the order the sections read
# in. Fifty-six dropdowns in one list is not a form anybody can fill in; grouped by what
# the columns are FOR, a user maps the money block and stops.
#
# `required` marks the sections the commission run cannot work without — see
# REQUIRED_GROUPS below for the field-level rule, which is what is actually enforced.
GROUP_ORDER = ["Dates", "Carrier", "Document", "Passenger", "Itinerary", "Money", "Other"]

_FIELD_GROUP = {
    # Dates
    "week": "Dates", "booking_date": "Dates", "transaction_date": "Dates",
    "issue_date": "Dates", "travel_date": "Dates",
    # Carrier
    "airline_name": "Carrier", "airline_code": "Carrier", "ticket_prefix": "Carrier",
    "segment_type": "Carrier",
    # Document
    "pnr": "Document", "airline_pnr": "Document", "gds_pnr": "Document",
    "booking_reference": "Document", "ticket_number": "Document",
    "ticket_status": "Document", "transaction_type": "Document",
    "booking_type": "Document", "username": "Document", "issuing_office": "Document",
    "invoice_number": "Document",
    # Passenger
    "pax_type": "Passenger", "first_name": "Passenger", "last_name": "Passenger",
    "passenger_name": "Passenger", "passenger_count": "Passenger",
    "customer_name": "Passenger", "customer_id": "Passenger",
    # Itinerary
    "sector": "Itinerary", "flight_number": "Itinerary", "trip_type": "Itinerary",
    "travel_type": "Itinerary", "booking_class": "Itinerary",
    "payment_method": "Itinerary",
    # Money
    "currency": "Money", "base_fare": "Money", "yq": "Money", "other_taxes": "Money",
    "taxes": "Money", "ssr_amount": "Money", "reschedule_charges": "Money",
    "convenience_fee": "Money", "other_charges": "Money", "total_fare": "Money",
    "commission_amount": "Money", "commission_rate": "Money",
    "incentive_amount": "Money", "tds": "Money", "service_charge": "Money",
    "service_fee": "Money", "gst_on_sf": "Money", "markup": "Money",
    "agent_penalty": "Money", "cancellation_markup": "Money", "net_amount": "Money",
}

# What a row is unusable without, and what it is merely unpriceable without. Each entry is
# "at least one of these fields", because exports label the same thing differently.
#
# The split matters. A row with no identifier and no money is not a statement line at all —
# it cannot be found in Ticket Search and cannot be reconciled, so importing it is a
# mis-mapping rather than a choice, and the API refuses. A row with no carrier or no date
# is a real line that simply cannot be matched to a deal: it is stored, searchable and
# visible, and the user is TOLD that Commission income will report it unmatched. Blocking
# that case would stop someone archiving a statement they only wanted on file.
REQUIRED_GROUPS = [
    {"label": "a booking identifier", "fields": ["ticket_number", "pnr", "airline_pnr", "gds_pnr"],
     "headers": "Ticket No, S PNR, Airline PNR or CRS PNR"},
    {"label": "an amount", "fields": ["base_fare", "net_amount", "total_fare"],
     "headers": "Basic Fare, Net Amount or Total Fare"},
]
ADVISORY_GROUPS = [
    {"label": "the airline", "fields": ["airline_name", "airline_code", "ticket_prefix"],
     "headers": "Airline Name, Airline Code or TicketPrefix",
     "consequence": "Commission income cannot find a deal for a row whose carrier it does not know."},
    {"label": "a date", "fields": ["booking_date", "issue_date", "transaction_date"],
     "headers": "Booked Date, Issue Date or Transaction Date",
     "consequence": "Deal validity is checked against the issue date, so rows without one stay unmatched."},
]


def _cols(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"header": h, "field": f, "group": _FIELD_GROUP.get(f, "Other")} for f, h in pairs]


def column_groups(parser_name: str) -> list[dict]:
    """The registered type's columns, grouped and ordered for the mapping screen."""
    b = _REGISTRY.get(parser_name)
    if b is None:
        return []
    by_group: dict[str, list[dict]] = {}
    for c in b.display_columns:
        by_group.setdefault(c.get("group") or "Other", []).append(c)
    ordered = [g for g in GROUP_ORDER if g in by_group]
    ordered += [g for g in by_group if g not in GROUP_ORDER]
    return [{"group": g, "columns": by_group[g]} for g in ordered]


def _assert_unique_aliases(parser_name: str, aliases: dict[str, list[str]]) -> None:
    """Refuse to register a spec where one alias claims two canonical fields.

    `_a2c` would resolve it to whichever came last in dict order, so the failure is a
    column quietly landing in the wrong field — no error, no blank cell, just a wrong
    number. Failing at import is the only place this is cheap to notice.
    """
    owner: dict[str, str] = {}
    for canon, names in aliases.items():
        for a in names:
            if a in owner and owner[a] != canon:
                raise ValueError(
                    f"flat_statement[{parser_name}]: alias '{a}' is claimed by both "
                    f"'{owner[a]}' and '{canon}'. One alias, one canonical field."
                )
            owner[a] = canon


def _assert_headers_round_trip(parser_name: str, builder: _FlatBuilder) -> None:
    """Every display header must parse back to the field it displays.

    `GET /statements/{slug}/template` emits these headers verbatim, and the user guide tells
    people to fill that template in because it is "the surest way to have everything read
    correctly". A header the alias map cannot read makes that advice false — the column is
    silently dropped from `data`. ('Passenger' was exactly this, from the day the spec was
    written.) Checked at import so a new display column cannot ship without its alias.
    """
    colmap = builder.build_col_map([c["header"] for c in builder.display_columns])
    broken = [(c["header"], c["field"], colmap.get(c["header"]))
              for c in builder.display_columns if colmap.get(c["header"]) != c["field"]]
    if broken:
        detail = "; ".join(f"'{h}' declares '{want}' but reads back as {got!r}" for h, want, got in broken)
        raise ValueError(
            f"flat_statement[{parser_name}]: template header(s) do not round-trip — {detail}. "
            f"Add the normalized header as an alias of its own field."
        )


def register(parser_name: str, columns: list[tuple[str, str]], aliases: dict[str, list[str]],
             source_format: str, derive: Callable[[dict], None] | None = None) -> list[dict]:
    _assert_unique_aliases(parser_name, aliases)
    b = _FlatBuilder(_cols(columns), aliases, source_format, derive)
    _assert_headers_round_trip(parser_name, b)
    _REGISTRY[parser_name] = b
    return b.display_columns


def get(parser_name: str) -> _FlatBuilder | None:
    return _REGISTRY.get(parser_name)


# ── shared alias fragments (a consolidator statement, GDS or LCC) ─────────────
_COMMON_ALIASES = {
    # identity / party
    "week":              ["week", "period", "settlement_week", "billing_week", "week_period"],
    "customer_name":     ["customer_name", "customername", "client_name", "clientname", "account_name"],
    "customer_id":       ["customer_id", "customerid", "client_id", "clientid", "customer_code", "customercode", "account_code"],
    "consolidator_name": ["consolidator_name", "consolidator", "consolidatorname", "supplier", "supplier_name", "suppliername", "vendor", "source_agency", "sourceagency", "parent_agency"],
    "agency_code":       ["agency_code", "agencycode", "agent_code", "agentcode", "sub_agent", "subagent", "sub_agent_code", "subagentcode"],
    "invoice_number":    ["invoice_number", "invoicenumber", "invoice_no", "invoiceno", "invoice"],
    "username":          ["username", "user_name", "user", "agent", "agent_name", "booked_by", "bookedby"],
    "issuing_office":    ["issuing_office", "issuingoffice", "office", "office_id", "pcc", "branch"],

    # dates
    "transaction_date":  ["transaction_date", "transactiondate", "txn_date", "trans_date", "date", "transaction_dtm"],
    "booking_date":      ["booking_date", "bookingdate", "booked_date", "bookeddate", "book_date", "bookingdatetime"],
    "issue_date":        ["issue_date", "issuedate", "date_of_issue", "dateofissue", "ticket_date", "ticketdate", "issued_on"],
    "travel_date":       ["travel_date", "traveldate", "traveldt", "travel_dt", "date_of_travel", "dateoftravel", "flight_date", "flightdate", "departure_date", "departuredate", "journey_date"],

    # document
    # NOTE: `booking_reference` is deliberately NOT an alias of `pnr` — the LCC spec has it
    # as its own canonical, and having it in both lists made the winner depend on dict order.
    "pnr":               ["pnr", "s_pnr", "spnr", "system_pnr", "supplier_pnr", "record_locator", "recordlocator"],
    "airline_pnr":       ["airline_pnr", "airlinepnr", "air_pnr", "airpnr", "carrier_pnr"],
    "gds_pnr":           ["gds_pnr", "gdspnr", "crs_pnr", "crspnr", "gds_record_locator", "gdsrecordlocator"],
    "ticket_number":     ["ticket_number", "ticketnumber", "ticket_no", "ticketno", "document_number", "documentnumber", "doc_no"],
    "ticket_prefix":     ["ticket_prefix", "ticketprefix", "prefix", "doc_prefix", "stock", "stock_prefix", "airline_accounting_code", "accounting_code"],
    # `status` belongs to the TICKET, not to payment. A consolidator's Status column reads
    # CONFIRMED / CANCELLED / REFUNDED — it drives the issue/refund/skip policy, so letting
    # `payment_status` keep it (as it did) meant the commission run saw no status at all.
    "ticket_status":     ["status", "ticket_status", "ticketstatus", "booking_status", "bookingstatus", "coupon_status", "pnr_status", "doc_status"],
    "payment_status":    ["payment_status", "paymentstatus"],
    "transaction_type":  ["transaction_type", "transactiontype", "type", "txn_type", "trans_type"],
    "booking_type":      ["booking_type", "bookingtype"],

    # carrier / itinerary
    "airline_name":      ["airline_name", "airlinename", "air_name", "carrier_name", "airline_desc"],
    "airline_code":      ["airline_code", "airlinecode", "airline", "carrier", "carrier_code", "carriercode"],
    "segment_type":      ["segment_type", "airline_category", "airlinecategory", "sector_type", "flight_type", "dom_intl", "domestic_international", "category", "geography"],
    "sector":            ["sector", "sectors", "route", "segment"],
    "flight_number":     ["flight_number", "flightnumber", "flight_no", "flightno", "flight"],
    "trip_type":         ["trip_type", "triptype", "journey_type", "journeytype"],
    "travel_type":       ["travel_type", "traveltype"],
    "booking_class":     ["booking_class", "bookingclass", "class", "rbd", "cabin_class", "class_of_service"],
    "payment_method":    ["payment_method", "paymentmethod", "payment_method_code", "paymentmethodcode", "payment_mode", "paymentmode", "form_of_payment", "fop"],

    # passenger
    "first_name":        ["first_name", "firstname", "given_name", "pax_first_name"],
    "last_name":         ["last_name", "lastname", "surname", "family_name", "pax_last_name"],
    "passenger_name":    ["passenger_name", "passengername", "passenger", "pax_name", "paxname", "name"],
    "passenger_count":   ["passenger_count", "paxcount", "pax_count", "pax"],
    "pax_type":          ["pax_type", "paxtype", "passenger_type", "passengertype", "ptc"],

    # money
    "base_fare":         ["base_fare", "basefare", "basic_fare", "basicfare", "basic", "fare"],
    "yq":                ["yq", "yq_fare", "yqfare", "yq_tax", "yqtax", "fuel_surcharge", "fuelsurcharge"],
    "other_taxes":       ["other_taxes", "othertaxes", "other_tax", "othertax", "taxes_other"],
    "taxes":             ["taxes", "tax", "total_tax", "totaltax", "tax_amount"],
    "ssr_amount":        ["ssr_amount", "ssramount", "ssr", "ssr_total", "ancillary", "ancillary_amount"],
    "reschedule_charges": ["reschedule_charges", "reschedulecharges", "reschedule_charge", "reissue_charges", "reissuecharges", "change_fee", "changefee"],
    "total_fare":        ["total_fare", "totalfare", "total_amount", "totalamount", "total", "gross", "gross_amount", "grossamount"],
    "currency":          ["currency", "currency_code", "currencycode"],
    "commission_amount": ["commission_amount", "commissionamount", "comm_amount", "commamount", "commission", "agent_commission", "agentcommission"],
    "commission_rate":   ["commission_rate", "commissionrate", "comm_percent", "commpercent", "comm", "commission_percent", "comm_pct"],
    "incentive_amount":  ["incentive_amount", "incentiveamount", "incentive", "plb"],
    "tds":               ["tds", "tds_amount", "tdsamount", "tds_deducted"],
    # `service_charge` used to be an alias of `markup`, which meant the real export's own
    # Service Charge column was read as an agency markup. They are different lines on the
    # invoice and both appear in the Net Amount identity, so they are separate fields.
    "service_charge":    ["service_charge", "servicecharge", "svc_charge", "svccharge"],
    "service_fee":       ["service_fee", "servicefee", "sf", "transaction_fee", "transactionfee", "booking_fee", "bookingfee"],
    "gst_on_sf":         ["gst_on_sf", "gstonsf", "gst_sf", "sf_gst", "gst_on_service_fee"],
    "agent_penalty":     ["agent_penalty", "agentpenalty", "penalty", "penalty_amount"],
    "cancellation_markup": ["cancellation_markup", "cancellationmarkup", "cancel_markup"],
    "markup":            ["markup", "mark_up", "agency_markup", "margin"],
    # `amount` and `payable` are gone: they are generic enough to hijack a column the file
    # meant as something else, and every real export names this one explicitly.
    "net_amount":        ["net_amount", "netamount", "net", "net_payable", "netpayable", "net_remit", "netremit"],

    "remarks":           ["remarks", "remark", "narration", "note", "notes", "details", "description"],
}


# Amount fields normalized to a bare numeric string by `_derive`. Anything a downstream
# SUM or the commission runner reads must be in here.
_MONEY_FIELDS = (
    "base_fare", "yq", "other_taxes", "taxes", "ssr_amount", "reschedule_charges",
    "total_fare", "commission_amount", "commission_rate", "incentive_amount", "tds",
    "service_charge", "service_fee", "gst_on_sf", "agent_penalty", "cancellation_markup",
    "markup", "net_amount", "convenience_fee", "other_charges", "passenger_count",
)

_DATE_FIELDS = ("transaction_date", "booking_date", "issue_date", "travel_date")


def _normalize_common(data: dict) -> None:
    """Shared derivation: ISO dates, bare numbers, and a joined passenger name."""
    for f in _DATE_FIELDS:
        if f in data:
            iso = to_iso_date(data[f])
            if iso:
                data[f] = iso
            else:
                # Keep the original — it is still worth showing — but say so, so nobody
                # reads a blank accrual bucket as "no sales".
                data.setdefault("date_parse_failed", f)
    for f in _MONEY_FIELDS:
        if f in data:
            n = to_number_str(data[f])
            if n is not None:
                data[f] = n

    # First/Last are separate canonicals because build_col_map cannot map two source
    # columns onto one field. Join them here so `passenger_name` is populated either way.
    if not data.get("passenger_name"):
        parts = [p for p in (data.get("first_name"), data.get("last_name")) if p]
        if parts:
            data["passenger_name"] = " ".join(parts)


def _derive_tp_gds(data: dict) -> None:
    _normalize_common(data)

    # ISSUE DATE. The real export has no ticketing-date column, and deal validity keys off
    # the issue date (deal_matching: contract_date = issue_date or travel_date). The booked
    # date is the sale date and the only defensible stand-in — recorded, never assumed
    # silently, so the diagnosis popup can say which date the contract window was tested
    # against. A consolidator who books and issues on different days shifts window edges.
    if not data.get("issue_date") and data.get("booking_date"):
        data["issue_date"] = data["booking_date"]
        data["issue_date_source"] = "booked_date"

    # TOTAL FARE. Not a column on this export, but plb_accrual sums `total_fare` for gross
    # revenue, so without it a third-party statement contributes a gross of zero.
    if not data.get("total_fare"):
        gross = (_f(data, "base_fare") + _f(data, "yq")
                 + (_f(data, "other_taxes") or _f(data, "taxes"))
                 + _f(data, "ssr_amount"))
        if gross:
            data["total_fare"] = to_number_str(f"{gross:.2f}")
            data["total_fare_source"] = "derived"


def _derive_tp_lcc(data: dict) -> None:
    _normalize_common(data)
    if not data.get("issue_date") and data.get("booking_date"):
        data["issue_date"] = data["booking_date"]
        data["issue_date_source"] = "booking_date"


# ── Third Party GDS ──────────────────────────────────────────────────────────
# Ordered as the real export reads, with the earlier superset fields interleaved where
# they belong rather than appended — so a file of either shape reads naturally in the
# drill-in. "(real export)" marks one of the forty columns actually supplied.
_TP_GDS_COLUMNS = [
    ("week", "Week"),                                    # real export
    ("booking_date", "Booked Date"),                     # real export
    ("transaction_date", "Transaction Date"),
    ("issue_date", "Issue Date"),
    ("travel_date", "Date of Travel"),                   # real export
    ("customer_name", "Customer Name"),                  # real export
    ("customer_id", "Customer ID"),                      # real export
    ("airline_name", "Airline Name"),                    # real export
    ("airline_code", "Airline Code"),                    # real export
    ("ticket_prefix", "Ticket Prefix"),                  # real export
    ("segment_type", "Airline Category"),                # real export
    ("pnr", "S PNR"),                                    # real export
    ("airline_pnr", "Airline PNR"),                      # real export
    ("gds_pnr", "CRS PNR"),                              # real export
    ("ticket_number", "Ticket No"),                      # real export
    ("ticket_status", "Status"),                         # real export
    ("transaction_type", "Type"),
    ("booking_type", "Booking Type"),                    # real export
    ("username", "Username"),                            # real export
    ("issuing_office", "Issuing Office"),                # real export
    ("pax_type", "Pax Type"),                            # real export
    ("first_name", "First Name"),                        # real export
    ("last_name", "Last Name"),                          # real export
    ("passenger_name", "Passenger"),
    ("passenger_count", "Pax"),
    ("sector", "Sector"),                                # real export
    ("flight_number", "Flight No"),                      # real export
    ("trip_type", "Trip Type"),                          # real export
    ("travel_type", "Travel Type"),                      # real export
    ("booking_class", "Class"),                          # real export
    ("payment_method", "Payment Mode"),                  # real export
    ("currency", "Currency"),
    ("base_fare", "Basic Fare"),                         # real export
    ("yq", "YQ Fare"),                                   # real export
    ("other_taxes", "Other Taxes"),                      # real export
    ("taxes", "Total Tax"),
    ("ssr_amount", "SSR Amount"),                        # real export
    ("reschedule_charges", "Reschedule Charges"),        # real export
    ("total_fare", "Total Fare"),
    ("commission_amount", "Agent Commission"),           # real export
    ("commission_rate", "Comm %"),
    ("incentive_amount", "Incentive"),                   # real export
    ("tds", "TDS Amount"),                               # real export
    ("service_charge", "Service Charge"),                # real export
    ("service_fee", "SF"),                               # real export
    ("gst_on_sf", "GST On SF"),                          # real export
    ("markup", "Markup"),
    ("agent_penalty", "Agent Penalty"),                  # real export
    ("cancellation_markup", "Cancellation Markup"),      # real export
    ("net_amount", "Net Amount"),                        # real export
    ("invoice_number", "Invoice No"),
    ("agency_code", "Agency Code"),
    ("consolidator_name", "Consolidator"),
    ("gds", "GDS"),
    ("payment_status", "Payment Status"),
    ("remarks", "Remarks"),
]
_TP_GDS_ALIASES = {
    **_COMMON_ALIASES,
    "gds": ["gds", "gds_name", "gdsname", "booking_system", "bookingsystem"],
}
TP_GDS_DISPLAY = register(
    "tp-gds", _TP_GDS_COLUMNS, _TP_GDS_ALIASES,
    # v2 = mapped against the real 40-column export. Batches still carrying the v1 label
    # were parsed by the speculative schema and are offered a Reprocess (api/v1/statements.py).
    "third-party-gds-v2", _derive_tp_gds,
)


# ── Third Party LCC ──────────────────────────────────────────────────────────
# STILL SPECULATIVE — no real third-party LCC export has been supplied. It inherits the
# shared alias fixes and the date/number/passenger derivation, but its column list is the
# original guess. Map a real file by editing the aliases; no migration is involved.
_TP_LCC_COLUMNS = [
    ("week", "Week"),
    ("booking_date", "Booking Date"),
    ("transaction_date", "Transaction Date"),
    ("issue_date", "Issue Date"),
    ("travel_date", "Travel Date"),
    ("customer_name", "Customer Name"),
    ("customer_id", "Customer ID"),
    ("airline_name", "Airline Name"),
    ("airline_code", "Airline Code"),
    ("segment_type", "Category"),
    ("pnr", "PNR"),
    ("airline_pnr", "Airline PNR"),
    ("booking_reference", "Booking Ref"),
    ("ticket_number", "Ticket No"),
    ("ticket_status", "Status"),
    ("transaction_type", "Type"),
    ("first_name", "First Name"),
    ("last_name", "Last Name"),
    ("passenger_name", "Passenger"),
    ("passenger_count", "Pax"),
    ("sector", "Sector"),
    ("flight_number", "Flight No"),
    ("booking_class", "Class"),
    ("payment_method", "Payment Method"),
    ("currency", "Currency"),
    ("base_fare", "Base Fare"),
    ("taxes", "Taxes"),
    ("other_taxes", "Other Taxes"),
    ("convenience_fee", "Convenience Fee"),
    ("other_charges", "Other Charges"),
    ("ssr_amount", "SSR Amount"),
    ("total_fare", "Total Fare"),
    ("markup", "Markup"),
    ("commission_amount", "Commission"),
    ("incentive_amount", "Incentive"),
    ("tds", "TDS Amount"),
    ("service_fee", "Service Fee"),
    ("gst_on_sf", "GST On SF"),
    ("net_amount", "Net Amount"),
    ("invoice_number", "Invoice No"),
    ("agency_code", "Agency Code"),
    ("consolidator_name", "Consolidator"),
    ("payment_status", "Payment Status"),
    ("remarks", "Remarks"),
]
_TP_LCC_ALIASES = {
    **_COMMON_ALIASES,
    "booking_reference": ["booking_reference", "bookingreference", "booking_ref", "bookingref", "reference"],
    "convenience_fee":   ["convenience_fee", "conveniencefee", "conv_fee", "convfee"],
    "other_charges":     ["other_charges", "othercharges", "other_fee", "otherfee", "misc_charges", "addon", "add_on_charges"],
}
TP_LCC_DISPLAY = register(
    "tp-lcc", _TP_LCC_COLUMNS, _TP_LCC_ALIASES, "third-party-lcc-v2", _derive_tp_lcc,
)


# Format labels the current parsers produce. A batch stamped with anything else was
# ingested by an older schema and its `data` is missing fields the current one extracts —
# api/v1/statements.py offers it a Reprocess rather than silently showing blanks.
CURRENT_SOURCE_FORMATS = {
    "tp-gds": "third-party-gds-v2",
    "tp-lcc": "third-party-lcc-v2",
}
