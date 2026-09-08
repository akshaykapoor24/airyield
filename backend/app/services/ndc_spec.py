"""Column spec for NDC statements — the airline-direct (New Distribution Capability)
sales export, e.g. Air India's.

WHY THIS IS ITS OWN MODULE AND NOT A LIST IN ``statement_spec``. NDC is 69 columns with
per-field grouping and aliases; inlining that next to the TGQ HMPR literals would bury
both. The other multi-format types (``di_statement``, ``flown_report``, …) already own
their column lists this way — this follows them.

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
  (`YQ Tax`, `K3 Tax`, …), so they are ordinary fields here and `fold_taxes` is off. An
  airline whose codes differ maps them onto these on the mapping screen, or leaves them
  unmapped.
* **Per-sector splitting.** `Sectors` on an NDC line is one leg ("HSR-DEL"), not the
  space-separated list TGQ packs into a single ticket row, so there is nothing to expand.

ROW TYPES. An NDC export is a transaction ledger, not a ticket list: alongside issued
tickets it carries ancillaries (`Product` = Seat, `TXN Type` = FREE_SEAT / UNPAID_SEAT),
unpaid holds (`UNPAID_BOOKING`, no Document No) and refunds (`REFUND`, negative Payment
Amount). All of them import. Dropping the non-ticket lines would make the file stop
reconciling against the airline's own totals, and `Product` / `TXN Type` / `Payment Status`
are filters so they can be separated on screen instead.
"""
from __future__ import annotations

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
    ("Booking Signin",               "Agency",    ["Booking Sign In", "Booking User"]),
    ("TKT Issue Signin",             "Agency",    ["Ticket Issue Signin", "Ticketing Signin", "TKT Issue Sign In", "Issue Signin"]),
    ("Agency Name",                  "Agency",    ["Agent Name"]),
    ("Agency Type",                  "Agency",    ["Agent Type"]),
    ("Agency Code",                  "Agency",    ["Agent Code", "Office Id"]),

    # ── Document ─────────────────────────────────────────────────────────────
    # `Document No` is the ticket number (13 digits, airline prefix included).
    ("Document No",                  "Document",  ["Ticket No", "Ticket Number", "Document Number", "TicketNo"]),
    ("Inconnection Doc number",      "Document",  ["In Connection Doc Number", "In-Connection Document Number", "Inconnection Document No"]),
    ("Coupon number",                "Document",  ["Coupon No", "Coupon"]),
    ("Document Type",                "Document",  ["Doc Type"]),
    ("Conjunction Ticket No",        "Document",  ["Conjunction Ticket Number", "Conj Ticket No"]),
    ("Product",                      "Document",  ["Product Type"]),
    ("TXN Sequence",                 "Document",  ["Transaction Sequence", "Txn Seq"]),
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
    ("Date Of Booking",              "Dates",     ["Booking Date", "Booked Date"]),
    ("Time Of Booking",              "Dates",     ["Booking Time"]),
    ("Date Of Issue",                "Dates",     ["Issue Date", "Ticket Date", "Ticketing Date"]),
    ("Time Of Issue",                "Dates",     ["Issue Time", "Time Of Issue (HH:MM:SS - 24 hr format)"]),
    ("TTL (Due Time Limit)",         "Dates",     ["TTL", "Due Time Limit", "Time Limit", "Ticketing Time Limit"]),
    ("Departure Date",               "Dates",     ["Dep Date", "Travel Date"]),
    ("Departure Time",               "Dates",     ["Dep Time", "Departure Time (HH:MM)"]),
    ("Arrival Date",                 "Dates",     ["Arr Date"]),
    ("Arrival Time",                 "Dates",     ["Arr Time", "Arrival Time(HH:MM)"]),

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
    ("Form Of Payment",              "Money",     ["FOP", "Payment Type"]),
    ("Total Fare",                   "Money",     ["Gross Fare", "Total Amount"]),
    ("Basic Fare",                   "Money",     ["Base Fare", "Basic"]),
    ("Total Tax",                    "Money",     ["Taxes", "Total Taxes"]),
    ("Payment Amount",               "Money",     ["Paid Amount", "Amount Paid"]),
    ("Penalty Amount",               "Money",     ["Penalty", "Cancellation Charge"]),
    ("Payment Surcharge",            "Money",     ["Surcharge"]),
    ("PNR Level Surcharge",          "Money",     []),
    ("Amount Retained At PNR Level", "Money",     ["Amount Retained"]),
    ("Amount Held",                  "Money",     ["Held Amount"]),
    ("PNR Level",                    "Money",     []),
    ("Currency",                     "Money",     ["Curr", "Currency Code"]),
    ("Discount",                     "Money",     ["Discount Amount"]),
    ("Service Fee",                  "Money",     ["Service Charge"]),
    ("Application FOP",              "Money",     ["Application Form Of Payment"]),
    ("Payment Reference Id",         "Money",     ["Payment Reference", "Payment Ref Id", "Transaction Reference"]),
    ("Payment Status",               "Money",     ["Status"]),

    # ── Taxes ────────────────────────────────────────────────────────────────
    # Air India's code set. Another carrier's codes are mapped onto these on the mapping
    # screen (or left unmapped); `Total Tax` above stays the reconcilable figure.
    ("AE Tax",                       "Taxes",     ["AE"]),
    ("DE Tax",                       "Taxes",     ["DE"]),
    ("F6 Tax",                       "Taxes",     ["F6"]),
    ("FR Tax",                       "Taxes",     ["FR"]),
    ("IN Tax",                       "Taxes",     ["IN"]),
    ("K3 Tax",                       "Taxes",     ["K3", "GST", "K3 GST"]),
    ("O4 Tax",                       "Taxes",     ["O4"]),
    ("P2 Tax",                       "Taxes",     ["P2"]),
    ("QX Tax",                       "Taxes",     ["QX"]),
    ("RA Tax",                       "Taxes",     ["RA"]),
    ("TP Tax",                       "Taxes",     ["TP"]),
    ("YQ Tax",                       "Taxes",     ["YQ", "YQ Surcharge"]),
    ("YR Tax",                       "Taxes",     ["YR", "YR Surcharge"]),
    ("ZR Tax",                       "Taxes",     ["ZR"]),

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
    import re
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

# ── Drill-in ─────────────────────────────────────────────────────────────────
# "select" is an exact match fed by /records/facets; "text" is a case-insensitive contains.
# Product / TXN Type / Payment Status are here because they are what separates a ticket
# from an ancillary, a refund, or an unpaid hold — see the row-types note above.
FILTERS = [
    {"field": "airline",         "label": "Airline",   "type": "select"},
    {"field": "agency_name",     "label": "Agency",    "type": "select"},
    {"field": "product",         "label": "Product",   "type": "select"},
    {"field": "txn_type",        "label": "TXN Type",  "type": "select"},
    {"field": "payment_status",  "label": "Payment",   "type": "select"},
    {"field": "date_of_issue",   "label": "Issue Date", "type": "select"},
    {"field": "document_no",     "label": "Document No", "type": "text"},
    {"field": "airline_pnr",     "label": "Airline PNR", "type": "text"},
    {"field": "passenger_name",  "label": "Passenger", "type": "text"},
]

# Totalled over the whole filtered set and shown in the slab above the table.
SUMMARY = [
    {"field": "basic_fare",     "label": "Basic Fare"},
    {"field": "total_tax",      "label": "Total Tax"},
    {"field": "total_fare",     "label": "Total Fare"},
    {"field": "payment_amount", "label": "Payment Amount"},
    {"field": "penalty_amount", "label": "Penalty"},
    {"field": "service_fee",    "label": "Service Fee"},
]

# Right-aligned and thousands-formatted in the table. Broader than SUMMARY on purpose:
# every amount should read as an amount, but only six of them are worth a total slab.
MONEY_FIELDS = {
    "total_fare", "basic_fare", "total_tax", "payment_amount", "penalty_amount",
    "payment_surcharge", "pnr_level_surcharge", "amount_retained_at_pnr_level",
    "amount_held", "discount", "service_fee",
    *(c["field"] for c in COLUMNS if c["group"] == "Taxes"),
}

# ── Mapping guard rails ──────────────────────────────────────────────────────
# Same split as flat_statement.REQUIRED_GROUPS: `required` is what the API refuses without,
# `advisory` is what it accepts but warns about.
#
# A row with no document number and no PNR cannot be found in Ticket Search and cannot be
# reconciled, so importing it is a mis-mapping rather than a choice. Note the identifier
# list includes `Airline PNR` precisely because the ancillary and unpaid-hold rows have no
# Document No — requiring the ticket number alone would reject the very rows the row-types
# note above says to keep.
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
     "consequence": "Deal validity is checked against the issue date, so rows without one stay unmatched."},
]
