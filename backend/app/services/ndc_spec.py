"""Column spec for NDC statements — the airline-direct (New Distribution Capability)
sales export, e.g. Air India's.

WHY THIS IS ITS OWN MODULE AND NOT A LIST IN ``statement_spec``. This is dozens of columns
with per-field grouping and aliases; inlining that next to the TGQ HMPR literals would bury
both. The other multi-format types (``di_statement``, ``flown_report``, …) already own
their column lists this way — this follows them.

THE SPEC IS NARROWER THAN THE EXPORT. Air India sends 69 columns; this keeps 43. A vendor
repository is read by a human reconciling a statement, and a column that is the same on
every line, restates another column, or was only ever populated on a row type we no longer
import is worse than absent — it is 68 columns of scrolling to find the four that matter.
Each group below says what it dropped and why. Nothing is lost from the source file, which
is stored whole and downloadable from the uploads list.

TWO COLUMNS CAME BACK when NDC rows started feeding billing (services/ndc_billing_projection.py),
because the projection reads them and nothing else can stand in:

* **Payment Amount** is the SETTLED figure and the only signed one. `Total Fare` on a REFUND
  line is the positive magnitude of the original sale — the refund's own value is
  `Payment Amount` (-9200 against a 9480 fare and a 280 penalty). It becomes the projected
  ticket's `total_amt`, which IS the billing base (api/v1/customers.py reads it first).
* **Date Of Issue** becomes `uploaded_tickets.ticket_date`. Deal validity and BSP
  reconciliation are both checked against the issue date; `Date Of Booking` is a different
  fact and using it would misdate every invoice line by the booking-to-ticketing gap.

WHY NDC IS MAPPED RATHER THAN READ VERBATIM. TGQ HMPR comes out of one GDS with one fixed
export, so its columns can be matched by name and anything else is an error. NDC does not
work like that: every airline runs its own NDC portal and names the same field differently
("Document No" / "Ticket Number" / "TicketNo"), and the shape below is Air India's. So the
uploader is shown the mapping and can correct it before anything is written —
``supports_mapping`` in statement_spec.STATEMENT_SPECS["ndc"] is what turns that on.

WHAT IS DELIBERATELY ABSENT.

* **User Name.** The export repeats the logged-in portal user on every line, so it says
  nothing about the row — it is a property of the download, not of the ticket. The uploader
  is already recorded on the batch (`created_by_id`), which is the same fact stored once.
* **Tax_TypeN / TaxN folding.** TGQ HMPR arrives with generic numbered tax pairs, which is
  why that type folds them into a JSONB array. An NDC export names its taxes as columns
  (`YQ Tax`, `K3 Tax`, …), so they are ordinary fields here and `fold_taxes` is off. The
  minor codes are added into one `Other Taxes` figure instead — see `derive`.
* **Per-sector splitting.** `Sectors` on an NDC line is one leg ("HSR-DEL"), not the
  space-separated list TGQ packs into a single ticket row, so there is nothing to expand.

ROW TYPES. An NDC export is a transaction ledger, not a ticket list: alongside issued
tickets it carries ancillaries (`Product` = Seat, `TXN Type` = FREE_SEAT / PAID_SEAT),
unpaid holds (`UNPAID_BOOKING`, no Document No) and refunds (`REFUND`, negative Payment
Amount). Only the lines where money actually moved are imported — see
`EXCLUDED_TXN_TYPES` below. `Product` / `TXN Type` / `Payment Status` remain filters so
the kept types can still be separated on screen.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# ── Columns ──────────────────────────────────────────────────────────────────
# (canonical template header, mapping-screen group, [extra source headers seen in the
# wild]). The field key is norm(header) — see statement_spec.norm — and the order here is
# the order of both the template and the repository table.
#
# Aliases exist for two reasons: the airline's own header differs from ours (`Ticket
# Number` for `Document No`), or the airline's own header carries a format hint we do not
# want in a template ("Departure Time (HH:MM)"). Matching is on norm() of both sides, so
# case, spacing, punctuation and line breaks inside a header cell are already handled and
# need no alias.
_SPEC: list[tuple[str, str, list[str]]] = [
    # ── Agency ───────────────────────────────────────────────────────────────
    # `Agency Name` and `Agency Code` are dropped: an NDC export is downloaded from one
    # agency's own portal, so both are the same value on every line — the batch's uploader
    # and tenant already say whose file it is. The two sign-ins stay because they differ
    # row to row, and they are the only record of WHO in the agency booked and who ticketed.
    ("Booking Signin",               "Agency",    ["Booking Sign In", "Booking User"]),
    ("TKT Issue Signin",             "Agency",    ["Ticket Issue Signin", "Ticketing Signin", "TKT Issue Sign In", "Issue Signin"]),
    ("Agency Type",                  "Agency",    ["Agent Type"]),

    # ── Document ─────────────────────────────────────────────────────────────
    # `Document No` is the ticket number (13 digits, airline prefix included).
    ("Document No",                  "Document",  ["Ticket No", "Ticket Number", "Document Number", "TicketNo"]),
    ("Inconnection Doc number",      "Document",  ["In Connection Doc Number", "In-Connection Document Number", "Inconnection Document No"]),
    ("Coupon number",                "Document",  ["Coupon No", "Coupon"]),
    ("Document Type",                "Document",  ["Doc Type"]),
    ("Conjunction Ticket No",        "Document",  ["Conjunction Ticket Number", "Conj Ticket No"]),
    ("Product",                      "Document",  ["Product Type"]),
    # `TXN Sequence` is dropped — it numbers the transactions within one PNR, which is the
    # portal's own bookkeeping and means nothing once the rows are out of the file.
    ("TXN Type",                     "Document",  ["Transaction Type"]),
    ("Airline PNR",                  "Document",  ["PNR", "Airline PNR No"]),
    ("Child/Parent PNR",             "Document",  ["Parent PNR"]),
    ("Coupon Status",                "Document",  ["Cpn Status"]),

    # ── Carrier ──────────────────────────────────────────────────────────────
    # Two different codes, both from the file: `Airline` is the 2-letter marketing code
    # ("AI"); `Airline IATA Code` is the 3-digit accounting/numeric code ("098") that
    # prefixes the ticket number. Kept apart because they join to different things.
    ("Airline",                      "Carrier",   ["Carrier", "Airline Code", "Marketing Airline"]),
    ("Airline IATA Code",            "Carrier",   ["IATA Code", "Airline Numeric Code", "Accounting Code"]),

    # ── Dates ────────────────────────────────────────────────────────────────
    # Three dates, no clock times. The times (`Time Of Booking`, `Time Of Issue`, `Departure
    # Time`, `Arrival Time`) are operational detail nothing here reads, and a time in its
    # own column is only half a timestamp anyway. `TTL` is the ticketing time limit on an
    # unpaid hold, and holds are no longer imported at all (see EXCLUDED_TXN_TYPES), so the
    # column would be blank on every row that survives. `Arrival Date` follows `Departure
    # Date` on a single leg; the itinerary detail lives in the airline's own record.
    #
    # `Date Of Issue` is the ticket's own date and the one billing bills on — see the
    # header note. The export heads it with a trailing space ("Date Of Issue "), which
    # `norm` already collapses, so the canonical header matches it with no alias; the
    # aliases below are for the other portals.
    ("Date Of Booking",              "Dates",     ["Booking Date", "Booked Date"]),
    ("Date Of Issue",                "Dates",     ["Issue Date", "Ticket Date", "Ticketing Date"]),
    ("Departure Date",               "Dates",     ["Dep Date", "Travel Date"]),

    # ── Itinerary ────────────────────────────────────────────────────────────
    ("Flight No",                    "Itinerary", ["Flight Number", "FlightNo"]),
    ("Sectors",                      "Itinerary", ["Sector", "Route", "Segment"]),
    ("Class Of Booking",             "Itinerary", ["Booking Class", "RBD", "Class"]),
    ("FareBasis",                    "Itinerary", ["Fare Basis", "Fare Basis Code"]),
    ("Cabin Code",                   "Itinerary", ["Cabin"]),
    ("Cabin Name",                   "Itinerary", ["Cabin Class"]),

    # ── Passenger ────────────────────────────────────────────────────────────
    ("Passenger Name",               "Passenger", ["Pax Name", "Traveller Name"]),
    ("Passenger Type",               "Passenger", ["Pax Type", "PTC"]),

    # ── Money ────────────────────────────────────────────────────────────────
    # What the ticket cost, what was settled for it, and in what currency. The portal's
    # payment-PLUMBING columns are still dropped: `Payment Surcharge` / `PNR Level Surcharge`
    # / `Amount Retained At PNR Level` / `Amount Held` / `PNR Level` are the hold-and-release
    # mechanics of an unpaid booking, which is a row type this spec no longer imports; and
    # `Application FOP` / `Payment Reference Id` identify the transaction inside the airline's
    # gateway, which is not where anything here reconciles.
    #
    # `Payment Amount` is NOT one of those. It is the settled figure and the only signed one
    # in the file — on a REFUND line `Total Fare` stays the positive magnitude of the original
    # sale while `Payment Amount` carries the credit. Billing reads it; see the header note.
    ("Form Of Payment",              "Money",     ["FOP", "Payment Type"]),
    ("Total Fare",                   "Money",     ["Gross Fare", "Total Amount"]),
    ("Basic Fare",                   "Money",     ["Base Fare", "Basic"]),
    ("Total Tax",                    "Money",     ["Taxes", "Total Taxes"]),
    ("Payment Amount",               "Money",     ["Paid Amount", "Amount Paid", "Settled Amount", "Payment Amt"]),
    ("Penalty Amount",               "Money",     ["Penalty", "Cancellation Charge"]),
    ("Currency",                     "Money",     ["Curr", "Currency Code"]),
    ("Discount",                     "Money",     ["Discount Amount"]),
    ("Service Fee",                  "Money",     ["Service Charge"]),
    ("Payment Status",               "Money",     ["Status"]),

    # ── Taxes ────────────────────────────────────────────────────────────────
    # Three codes get a column of their own; the other eleven Air India emits are summed
    # into `Other Taxes`. K3 is GST — it is the input credit and the one tax with its own
    # compliance question. YQ and YR are the carrier-imposed surcharges, which is where the
    # money and the argument with the airline usually are. The rest (AE, DE, F6, FR, IN,
    # O4, P2, QX, RA, TP, ZR) are statutory levies nobody queries line by line, and eleven
    # near-empty columns cost more to read than they are worth.
    #
    # `Other Taxes` is DERIVED, not mapped — see `derive` below. `Total Tax` above stays
    # the reconcilable figure, and K3 + YQ + YR + Other Taxes should equal it.
    ("K3 Tax",                       "Taxes",     ["K3", "GST", "K3 GST"]),
    ("YQ Tax",                       "Taxes",     ["YQ", "YQ Surcharge"]),
    ("YR Tax",                       "Taxes",     ["YR", "YR Surcharge"]),
    ("Other Taxes",                  "Taxes",     ["Other Tax", "Misc Tax", "Miscellaneous Taxes"]),

    # ── Other ────────────────────────────────────────────────────────────────
    # `Deal Code` and `Tour Code` are how the airline stamps a negotiated fare onto the
    # ticket, so they are the file's own link back to a deal.
    ("Tour Code",                    "Other",     ["Tourcode"]),
    ("Deal Code",                    "Other",     ["Dealcode", "Contract Code"]),
    ("Promo Code",                   "Other",     ["Promotion Code"]),
]

# Section order on the mapping screen. Identity first, money last: a user checks who and
# what before they check how much, and the tax block is long enough to scroll past.
GROUP_ORDER = ["Agency", "Document", "Carrier", "Dates", "Itinerary", "Passenger",
               "Money", "Taxes", "Other"]


def _norm(header: str) -> str:
    # Local copy of statement_spec.norm — importing it here would be circular, since
    # statement_spec imports this module.
    h = str(header).lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", h).strip("_")


HEADERS: list[str] = [h for h, _g, _a in _SPEC]

#: Ordered ``[{header, field, group}]`` — the repository table, the template, and the
#: mapping screen all read from this one list.
COLUMNS: list[dict] = [
    {"header": h, "field": _norm(h), "group": g} for h, g, _a in _SPEC
]

#: ``{field: [source header, …]}`` for auto-mapping. The canonical header is included, so
#: a file made from our own Template maps itself and the wizard says so.
ALIASES: dict[str, list[str]] = {
    _norm(h): [h, *extra] for h, _g, extra in _SPEC
}

# ── Other Taxes ──────────────────────────────────────────────────────────────
# The eleven codes that no longer get a column each. They are still READ from the file —
# they just land added together.
#
# WHY THIS IS DERIVED RATHER THAN MAPPED. The mapping screen maps one field to one source
# column; there is no way to say "this field is eleven columns added up". So `Other Taxes`
# is computed from the raw line, the way `_fold_taxes` already computes TGQ HMPR's tax
# array from the whole row rather than from the mapping. A file that carries its own
# `Other Taxes` column maps it normally and the mapped value wins — that is what makes a
# file exported from our own Template round-trip.
OTHER_TAX_HEADERS = [
    "AE Tax", "DE Tax", "F6 Tax", "FR Tax", "IN Tax",
    "O4 Tax", "P2 Tax", "QX Tax", "RA Tax", "TP Tax", "ZR Tax",
]

#: Normalised source headers the sum looks for. Both spellings, because the bare code is
#: how some portals head the column — the same pairs the old per-code aliases carried.
OTHER_TAX_KEYS: set[str] = {
    *(_norm(h) for h in OTHER_TAX_HEADERS),
    *(_norm(h.split(" ")[0]) for h in OTHER_TAX_HEADERS),
}

DERIVED_FIELD = "other_taxes"


def to_decimal(value) -> Decimal | None:
    """"1,234.50" → Decimal("1234.50"); anything that is not a number → None.

    Public because services/ndc_billing_projection.py parses the same verbatim cells when
    it prices a row, and two parsers over one column is how the repository total and the
    billed total come to disagree.

    Values reach the row as verbatim strings (these types are a faithful copy of the
    vendor's file), so the thousands separators and the stray "—" an export uses for an
    empty cell both have to be survivable. A cell that will not parse is skipped rather
    than counted as zero — silently reading "N/A" as 0.00 would understate the total with
    nothing on screen to say so.
    """
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def derive(values: dict) -> dict:
    """{normalised source header: cleaned value} for ONE line → the fields to add to it.

    Returns `{}` when the line carries none of the eleven codes — an absent column and a
    genuine zero are different facts, and writing "0.00" for a file that never had those
    columns would invent a total the airline never sent.
    """
    total, seen = Decimal(0), False
    for key in OTHER_TAX_KEYS:
        n = to_decimal(values.get(key))
        if n is not None:
            total += n
            seen = True
    return {DERIVED_FIELD: f"{total:.2f}"} if seen else {}


# ── Row filter ───────────────────────────────────────────────────────────────
# WHICH LINES OF THE LEDGER ARE WORTH KEEPING. Air India's export carries ten TXN Types.
# Six of them are transactions where money moved or is owed back — PAID_BOOKING, PAID_SEAT,
# REFUND, REFUND_SEAT, SPLIT_BOOKING, TICKETING — and those are the repository's subject.
# The four below are not:
#
# * `UNPAID_BOOKING` / `UNPAID_SEAT` are holds against a ticketing time limit (`TTL`). Their
#   `Payment Amount` is 0.00 and they carry no Document No, so there is nothing to reconcile
#   and nothing for Commission income to price. They either become a PAID_* line later, in
#   which case that line is the fact, or the TTL lapses and they were never a sale.
# * `UNPAID_CANCEL` is such a hold expiring — the absence of a sale, recorded.
# * `FREE_SEAT` is a seat given away at 0.00. It is an operational note on a booking whose
#   revenue is already on the flight line.
#
# WHY A DROP LIST AND NOT A KEEP LIST. Every airline runs its own NDC portal (the reason
# this type is mapped at all), so the next carrier will have a TXN Type this list has never
# seen. Naming what to discard means an unrecognised type imports and is visible in the
# `TXN Type` filter; naming what to keep would make it disappear with nothing on screen to
# say so. Swap the two only if silence on an unknown type is the safer failure here.
#
# Enforced at ingest, in both loops of api/v1/statements.py — not at query time — so the
# entry count on the uploads list is the count of rows that exist.
EXCLUDED_TXN_TYPES: set[str] = {
    "FREE_SEAT", "UNPAID_BOOKING", "UNPAID_CANCEL", "UNPAID_SEAT",
}

#: The six that survive, for the wizard's note and for the tests. Not what the filter reads.
KEPT_TXN_TYPES: set[str] = {
    "PAID_BOOKING", "PAID_SEAT", "REFUND", "REFUND_SEAT", "SPLIT_BOOKING", "TICKETING",
}

#: The field `is_excluded` reads. Named here so statements.py can tell the wizard which
#: mapped column drives the rule without importing this module.
FILTER_FIELD = "txn_type"


def norm_txn(value) -> str:
    """"Paid Booking", "paid-booking", " PAID_BOOKING " → PAID_BOOKING.

    The values above are Air India's spelling. Another portal exporting the same fact with
    a space or a hyphen is the same transaction, and matching on the raw string would let
    it through as an unrecognised type.
    """
    return re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")


def is_excluded(data: dict) -> bool:
    """Should this built row be dropped rather than written?

    `data` is the mapped row — {field: value} — so a row whose `TXN Type` column was left
    unmapped has no `txn_type` key at all and is KEPT. That is deliberate: not knowing a
    row's type is not evidence that it is an unpaid hold, and dropping on a missing mapping
    would empty the whole file. The confirm endpoint warns instead.

    A blank `TXN Type` on a mapped column is kept for the same reason.
    """
    raw = data.get(FILTER_FIELD)
    if raw is None or not str(raw).strip():
        return False
    return norm_txn(raw) in EXCLUDED_TXN_TYPES


#: What /standard-columns hands the wizard so it can grey out the rows it is about to skip
#: and say why. The API is the authority; this is only how the screen explains it.
ROW_FILTER = {
    "field": FILTER_FIELD,
    "header": "TXN Type",
    "exclude": sorted(EXCLUDED_TXN_TYPES),
    "keep": sorted(KEPT_TXN_TYPES),
    "label": "unpaid and free-seat rows",
    "note": "Unpaid holds and free seats are not transactions — no money moved and there is "
            "nothing to reconcile — so they are skipped. Everything else in the file imports.",
}


# ── Drill-in ─────────────────────────────────────────────────────────────────
# "select" is an exact match fed by /records/facets; "text" is a case-insensitive contains.
# Product / TXN Type / Payment Status are here because they are what separates a ticket
# from an ancillary or a refund — see the row-types note above.
# `Booking Signin` stands in for the dropped `Agency Name`: it is the sign-in the booking
# was made under, so it is the surviving column that differs between one desk and another.
# Both dates are offered — a statement is reconciled by issue date and chased by booking date.
FILTERS = [
    {"field": "airline",         "label": "Airline",   "type": "select"},
    {"field": "booking_signin",  "label": "Booking Signin", "type": "select"},
    {"field": "product",         "label": "Product",   "type": "select"},
    {"field": "txn_type",        "label": "TXN Type",  "type": "select"},
    {"field": "payment_status",  "label": "Payment",   "type": "select"},
    {"field": "date_of_booking", "label": "Booking Date", "type": "select"},
    {"field": "date_of_issue",   "label": "Issue Date", "type": "select"},
    {"field": "document_no",     "label": "Document No", "type": "text"},
    {"field": "airline_pnr",     "label": "Airline PNR", "type": "text"},
    {"field": "passenger_name",  "label": "Passenger", "type": "text"},
]

# Totalled over the whole filtered set and shown in the slab above the table. `Payment
# Amount` is last and deliberately beside `Total Fare`: the pair is what a reconciler
# checks first, and on a batch holding refunds the two totals differ by design.
SUMMARY = [
    {"field": "basic_fare",     "label": "Basic Fare"},
    {"field": "total_tax",      "label": "Total Tax"},
    {"field": "total_fare",     "label": "Total Fare"},
    {"field": "penalty_amount", "label": "Penalty"},
    {"field": "service_fee",    "label": "Service Fee"},
    {"field": "payment_amount", "label": "Settled"},
]

# Right-aligned and thousands-formatted in the table. Broader than SUMMARY on purpose:
# every amount should read as an amount, but only six of them are worth a total slab.
MONEY_FIELDS = {
    "total_fare", "basic_fare", "total_tax", "payment_amount", "penalty_amount",
    "discount", "service_fee",
    *(c["field"] for c in COLUMNS if c["group"] == "Taxes"),
}

# ── Mapping guard rails ──────────────────────────────────────────────────────
# Same split as flat_statement.REQUIRED_GROUPS: `required` is what the API refuses without,
# `advisory` is what it accepts but warns about.
#
# A row with no document number and no PNR cannot be found in Ticket Search and cannot be
# reconciled, so importing it is a mis-mapping rather than a choice. Note the identifier
# list includes `Airline PNR` precisely because the seat rows have no Document No —
# requiring the ticket number alone would reject PAID_SEAT and REFUND_SEAT, which the row
# filter above keeps.
REQUIRED_GROUPS = [
    {"label": "a booking identifier",
     "fields": ["document_no", "airline_pnr", "conjunction_ticket_no"],
     "headers": "Document No, Airline PNR or Conjunction Ticket No"},
    {"label": "an amount",
     "fields": ["total_fare", "basic_fare", "payment_amount"],
     "headers": "Total Fare, Basic Fare or Payment Amount"},
]
ADVISORY_GROUPS = [
    {"label": "the airline",
     "fields": ["airline", "airline_iata_code"],
     "headers": "Airline or Airline IATA Code",
     "consequence": "Commission income cannot find a deal for a row whose carrier it does not know."},
    {"label": "a date",
     "fields": ["date_of_issue", "date_of_booking", "departure_date"],
     "headers": "Date Of Issue, Date Of Booking or Departure Date",
     "consequence": "Deal validity is checked against the issue date, and it is what a billed "
                    "line is dated by, so rows without one stay unmatched."},
]
