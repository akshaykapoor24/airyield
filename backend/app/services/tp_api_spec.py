"""Column spec for Third Party API statements — an aggregator's booking export.

An aggregator (MakeMyTrip, TBO) is not a GDS or an LCC consolidator: it sells the agency
HOTELS, FLIGHTS, TRAINS, BUSES and CARS, and it settles all of them on one statement. A
single file has a hotel line, a flight line and a train line one under the other, and the
column that decides which is which is `Lob` (MMT) or `PRODUCT TYPE` (TBO).

WHY THIS IS ITS OWN MODULE. Same reason as `ndc_spec`: ~90 columns with per-field grouping
and per-vendor aliases would bury both this and the TGQ HMPR literals if inlined into
`statement_spec`. It is deliberately NOT registered in `flat_statement` either, for two
reasons that are specific to this type:

* `flat_statement.REQUIRED_GROUPS` demands one of ticket_number / pnr / airline_pnr /
  gds_pnr. An MMT hotel line has none of them — it has a `Booking Id` — so every hotel row
  in the file would be refused. This type needs its own required groups, which is what the
  spec-driven path (`services/spec_mapping.py`) allows and the parser path does not.
* `_FlatBuilder` takes its `source_format` as a constructor constant, so a parser-registered
  type has exactly one. This one has two — `mmt-bookings-v1` and `tbo-statement-v1`,
  detected per file — the same thing `lcc_di` does with its two deposit formats.

ONE SPEC FOR BOTH VENDORS, NOT ONE EACH. The columns below are the UNION of MMT's 35 and
TBO's 68. Where the two name the same fact they collapse onto one field via aliases, so a
mixed-vendor report totals correctly; where they name different facts they stay apart (see
`Total Paid Amount` vs `Net Amount` below, which is the one that matters). A field the
uploaded file has no column for is simply absent from `data` — it is JSONB, so an MMT file
pays nothing for TBO's forty tax columns.

THE POLYMORPHIC COLUMNS ARE ROLE-NAMED, NOT PRODUCT-NAMED. MMT ships one column pair for
two meanings: `Check-In/Departure Date` is a hotel check-in on a Hotel line and a flight
departure on a Flight line. Modelling that as `hotel_check_in` + `flight_departure_date` is
mechanically impossible — `build_col_map` claims a field once per source column, so the one
column could fill only one of them, and one alias may claim only one canonical field. So
they are `start_date` / `end_date` / `origin` / `destination`, which is also the better
answer: TBO's `CheckInDate`, MMT's flight columns and the AI's parsed train stations all
land in the same comparable column, and a Category-filtered grid shows the same itinerary
columns whichever product it is showing.

WHAT THE AI DOES AND DOES NOT DO. TBO packs a train's whole itinerary into one free-text
`NARRATION` cell ("Train Name-NZM RAJDHANI Train number- 22221 TravelDate-Aug  2 2026
From-C SHIVAJI MAH T (CSMT) To-H NIZAMUDDIN (NZM)"). No column mapping can reach inside a
sentence, so the review step offers an AI pass that fills `AI_FILLABLE` from it — and
nothing else. See services/ai_statement_narration.py.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services import flat_statement as _flat

# ── Columns ──────────────────────────────────────────────────────────────────
# (canonical template header, mapping-screen group, [extra source headers seen in the wild]).
# The field key is norm(header) — see statement_spec.norm — and the order here is the order
# of both the blank template and the repository table.
#
# Matching is on norm() of both sides, so case, spacing, punctuation and line breaks inside a
# header cell are already handled: "PGCharges" and "PG Charges" are different alias strings
# and both are listed, but "TDS AMOUNT" and "Tds Amount" are the same one and only need one.
_SPEC: list[tuple[str, str, list[str]]] = [
    # ── Booking ──────────────────────────────────────────────────────────────
    # Six different identifier columns, and they are NOT interchangeable: MMT stamps one
    # `Booking Id` per booking, TBO stamps an `INVOICE NUMBER` per invoice line and carries
    # the supplier's own three references beside it. Collapsing them would make a duplicate
    # check on either vendor meaningless.
    ("Booking Id",               "Booking",   ["Booking ID", "BookingId", "Booking Reference", "Booking Ref"]),
    ("Invoice Number",           "Booking",   ["Invoice No", "Invoice"]),
    ("Supplier Bill Number",     "Booking",   ["Supplier Bill No"]),
    ("Reference No",             "Booking",   ["Reference Number", "Ref No"]),
    ("Confirmation No",          "Booking",   ["Confirmation Number"]),
    ("TBO Confirmation No",      "Booking",   ["TBO Confirmation Number"]),
    ("PNR",                      "Booking",   ["Airline PNR", "Record Locator"]),
    ("Agency Reference",         "Booking",   ["Agency Ref"]),
    ("Booking Channel",          "Booking",   ["Booking Platform", "BookingMode", "Booking Mode", "Platform"]),
    ("Booking Type",             "Booking",   []),
    ("Booked By",                "Booking",   ["Created By", "Booking User", "Agent Name"]),
    ("Booking Status",           "Booking",   ["Status", "Bkg Status"]),
    ("Amendment Type",           "Booking",   []),

    # ── Product ──────────────────────────────────────────────────────────────
    # `Product Type` is THE column of this type — it is what makes one table workable
    # instead of five, and it is a declared `select` filter so the drill-in can show one
    # product at a time. TBO's `CATEGORY` ("R" for rail) is deliberately NOT an alias of it:
    # it is a one-letter code with its own vocabulary, and letting it claim `product_type`
    # would overwrite the real `PRODUCT TYPE` column on every TBO line.
    ("Product Type",             "Product",   ["Lob", "Line Of Business", "Product"]),
    ("Category",                 "Product",   []),
    ("Intl/Dom",                 "Product",   ["International/Domestic", "Dom Intl", "Geography", "Sector Type"]),

    # ── Passenger ────────────────────────────────────────────────────────────
    # The identity columns below are NOT offered as drill-in filters — see FILTERS.
    ("Passenger Name",           "Passenger", ["Primary Traveller", "Pax Name", "Guest Name", "Traveller Name", "Passenger"]),
    ("Pax Count",                "Passenger", ["No of Pax", "Pax", "Passenger Count", "Number Of Pax"]),
    ("Mobile Number",            "Passenger", ["Mobile", "Contact Number", "Phone"]),
    ("PAN",                      "Passenger", ["Pan No", "PAN Number"]),
    ("Guardian PAN",             "Passenger", ["GuardianPAN"]),
    ("Passport No",              "Passenger", ["PassportNo", "Passport Number"]),
    ("Passport Issue Date",      "Passenger", ["PassportIssueDate"]),
    ("Passport Expiry Date",     "Passenger", ["PassportExpDate", "Passport Exp Date"]),

    # ── Dates ────────────────────────────────────────────────────────────────
    # `Transaction Date` is TBO's invoice `DATE` and is a different fact from
    # `Booking Confirmation Date`; using one for the other misdates every line by the
    # booking-to-invoice gap. `Start`/`End` are the role-named polymorphic pair — see the
    # module docstring.
    ("Transaction Date",         "Dates",     ["Date", "Invoice Date", "Statement Date", "Txn Date"]),
    ("Booking Date",             "Dates",     ["Booking Confirmation Date", "Booked Date", "Book Date"]),
    ("Booking Time",             "Dates",     ["Booked Time"]),
    ("Travel Date",              "Dates",     ["Date Of Travel", "Journey Date", "TravelDate"]),
    ("Start Date",               "Dates",     ["Check-In/Departure Date", "CheckInDate", "Check In Date", "Departure Date"]),
    ("Start Time",               "Dates",     ["Check-In/Departure Time", "Check In Time", "Departure Time"]),
    ("End Date",                 "Dates",     ["Check-Out/Arrival Date", "CheckOutDate", "Check Out Date", "Arrival Date"]),
    ("End Time",                 "Dates",     ["Check-Out/Arrival Time", "Check Out Time", "Arrival Time"]),
    ("Payment Due Date",         "Dates",     ["Due Date"]),

    # ── Itinerary ────────────────────────────────────────────────────────────
    # `Airline/Property Name` is MMT's own header and says the polymorphism out loud: it is
    # the hotel on a Hotel line, the carrier on a Flight line, the operator on a Bus line.
    ("Airline/Property Name",    "Itinerary", ["Hotel Name", "Property Name", "Airline Name", "Airline", "Operator", "Bus Operator"]),
    ("Flight Number",            "Itinerary", ["Flight No", "FlightNo"]),
    ("Origin",                   "Itinerary", ["Departure/Hotel City", "Departure City", "From City", "Source City", "Boarding Point", "Pickup Location"]),
    ("Origin Code",              "Itinerary", ["From Code", "Origin Station"]),
    ("Destination",              "Itinerary", ["Arrival City", "DestinationCity", "Destination City", "To City", "Dropping Point", "Drop Location"]),
    ("Destination Code",         "Itinerary", ["To Code", "Destination Station"]),
    # MMT's own spelling of the header is "Depature/Hotel Country" — the typo is in the
    # export, so it has to be an alias or the column silently fails to map.
    ("Origin Country",           "Itinerary", ["Depature/Hotel Country", "Departure/Hotel Country", "Hotel Country", "Country"]),
    ("Trip Type",                "Itinerary", ["Journey Type"]),
    ("Booking Class",            "Itinerary", ["Class", "RBD", "Coach Class", "Travel Class"]),

    # ── Hotel ────────────────────────────────────────────────────────────────
    ("Hotel Star Rating",        "Hotel",     ["Star Rating", "Hotel Rating"]),
    ("No of Nights",             "Hotel",     ["Nights", "Number Of Nights"]),
    ("No of Rooms",              "Hotel",     ["Rooms", "Number Of Rooms"]),

    # ── Train ────────────────────────────────────────────────────────────────
    # `Train Name` and `Train Number` have no column in either export — they live inside
    # TBO's NARRATION sentence and are filled by the AI pass (see AI_FILLABLE). They are
    # declared here anyway so they have a canonical header, a group, a place in the template
    # and a column in the repository table.
    ("Train Name",               "Train",     []),
    ("Train Number",             "Train",     ["Train No"]),
    ("Quota",                    "Train",     []),
    ("Catering Charge",          "Train",     ["Catering Charges"]),
    # The ERS (rail) gateway charges are a SEPARATE line from the booking's own PG Charges
    # and both appear on the same TBO row — collapsing them would double-count neither and
    # lose one.
    ("ERS PG Charges",           "Train",     ["ERS PGCharges"]),
    ("ERS Agent Service Charge", "Train",     ["ERS AgentServiceCharge"]),
    ("ERS GST Invoice Number",   "Train",     ["ERS GSTInvoiceNumber"]),

    # ── Vehicle (bus / car) ──────────────────────────────────────────────────
    ("Vehicle Type",             "Vehicle",   []),
    ("No of Vehicle",            "Vehicle",   ["Number Of Vehicles", "No Of Vehicles"]),

    # ── Money ────────────────────────────────────────────────────────────────
    # THE ONE TO READ TWICE: `Net Amount` and `Total Paid Amount` are NOT the same figure
    # and must never be aliased together.
    #
    #   Net Amount        (TBO `NET`)  — the invoice payable. BASIC + TAXES + SERVICE
    #                                    CHARGES + GST − DISC − TDS. What the agency owes.
    #   Total Paid Amount (MMT)        — a TENDER total, which MMT itself decomposes into
    #                                    PG + Wallet + E-Coupon + Promo Cash + My Cash +
    #                                    Plus on the same row, and which reads 0 on a live
    #                                    "Pending Payment" line.
    #
    # Different denominator, different timing, different sign convention. Both are in
    # SUMMARY, so each reads zero on the other vendor's file — which is the honest result
    # and is precisely why they are two fields.
    ("Rate Of Exchange",         "Money",     ["RATEOFEXCHANGE", "ROE", "Exchange Rate"]),
    ("Base Fare",                "Money",     ["Basic Amount", "Basic Fare", "Basic"]),
    ("Taxes",                    "Money",     ["Total Tax", "Tax Amount"]),
    ("Discount",                 "Money",     ["Disc Paid Amount", "Discount Amount"]),
    ("Service Charges",          "Money",     ["Service Charge"]),
    ("Convenience Fee",          "Money",     ["Conv Fee"]),
    ("Travel Insurance",         "Money",     ["Insurance"]),
    ("Agent Markup",             "Money",     ["AgentMarkup", "Markup"]),
    ("Cancellation Fee",         "Money",     ["Cancellation Charges", "Cancel Fee"]),
    ("PG Charges",               "Money",     ["PGCharges", "Payment Gateway Charges"]),
    ("Net Amount",               "Money",     ["Net", "Net Payable"]),
    ("Total Paid Amount",        "Money",     ["Paid Amount"]),
    ("Pending Amount",           "Money",     ["Balance Amount"]),
    ("Wallet Amount",            "Money",     ["Total Wallet Amount(At the Time of Booking)", "Total Wallet Amount"]),
    ("PG Amount",                "Money",     ["Payment Gateway Amount"]),
    ("E-Coupon Amount",          "Money",     ["ECoupon Amount", "Coupon Amount"]),
    ("Promo Cash Amount",        "Money",     ["Promo Cash"]),
    ("My Cash",                  "Money",     []),
    ("Plus Amount",              "Money",     []),
    ("Refund Amount",            "Money",     ["Refund"]),
    ("Payment Mode",             "Money",     ["Mode Of Payment", "Form Of Payment"]),
    ("Payment Id",               "Money",     ["PaymentID"]),
    ("OXI Trx Id",               "Money",     ["OXITRXID"]),

    # ── Taxes ────────────────────────────────────────────────────────────────
    # The rates stay beside the amounts because an Indian statement is reconciled on both,
    # but they are kept OUT of MONEY_FIELDS and SUMMARY — see MONEY_FIELDS.
    ("SGST Rate",                "Taxes",     []),
    ("SGST Amount",              "Taxes",     ["SGST Amt"]),
    ("CGST Rate",                "Taxes",     []),
    ("CGST Amount",              "Taxes",     ["CGST Amt"]),
    ("IGST Rate",                "Taxes",     []),
    ("IGST Amount",              "Taxes",     ["IGST Amt"]),
    ("Total GST",                "Taxes",     ["GST Amount"]),
    ("Service Tax Amount",       "Taxes",     ["Service Tax"]),
    # Derived, not mapped — the three dead pre-GST cesses added together. See `derive`.
    ("Legacy Cess",              "Taxes",     []),
    ("TDS",                      "Taxes",     ["TDS Amount", "TDS Deducted", "TDS Amt"]),
    ("Edu Cess TDS Amount",      "Taxes",     ["Edu Cess (TDS)"]),
    ("TCS Rate",                 "Taxes",     []),
    ("TCS Amount",               "Taxes",     []),
    ("TCS Declaration Type",     "Taxes",     ["TCSDeclarationType"]),

    # ── Other ────────────────────────────────────────────────────────────────
    ("Narration",                "Other",     ["Remarks", "Description", "Details", "Particulars"]),
    # Derived from the detected `source_format`. It is mirrored into `data` rather than read
    # off the column because the drill-in filter builds `model.data[field].astext` and
    # cannot reach a real column.
    ("Vendor",                   "Other",     []),
]

GROUP_ORDER = ["Booking", "Product", "Passenger", "Dates", "Itinerary",
               "Hotel", "Train", "Vehicle", "Money", "Taxes", "Other"]


def _norm(header: str) -> str:
    # Local copy of statement_spec.norm — importing it here would be circular, since
    # statement_spec imports this module.
    h = str(header).lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", h).strip("_")


HEADERS: list[str] = [h for h, _g, _a in _SPEC]

#: Ordered ``[{header, field, group}]`` — the repository table, the template and the
#: mapping screen all read from this one list.
COLUMNS: list[dict] = [
    {"header": h, "field": _norm(h), "group": g} for h, g, _a in _SPEC
]

#: ``{field: [source header, …]}`` for auto-mapping. The canonical header is included, so a
#: file made from our own Template maps itself and the wizard says so.
ALIASES: dict[str, list[str]] = {
    _norm(h): [h, *extra] for h, _g, extra in _SPEC
}

FIELDS: list[str] = [c["field"] for c in COLUMNS]
_FIELD_SET = set(FIELDS)


def _assert_unique_aliases() -> None:
    """Refuse to import a spec where one alias claims two canonical fields.

    ``spec_mapping.SpecMapper`` builds its alias index with ``setdefault``, so a collision
    does not raise — it silently resolves to whichever field came first in spec order. The
    symptom is a column landing in the wrong field: no error, no blank cell, just a wrong
    number in a total. ``flat_statement.register`` guards its own specs this way for the
    same reason; the spec-driven path has no such guard, so this one is not optional.
    """
    owner: dict[str, str] = {}
    for canon, names in ALIASES.items():
        for a in names:
            n = _norm(a)
            if n in owner and owner[n] != canon:
                raise ValueError(
                    f"tp_api_spec: alias '{a}' is claimed by both '{owner[n]}' and "
                    f"'{canon}'. One alias, one canonical field."
                )
            owner[n] = canon


def _assert_headers_round_trip() -> None:
    """Every canonical header must read back as the field it declares.

    ``GET /statements/tp-api/template`` emits these headers verbatim and the product tells
    people that filling that template in is the surest way to have everything read
    correctly. A header the alias map cannot read makes that advice false — the column is
    silently dropped. ``flat_statement`` asserts this at import; ``spec_mapping`` does not,
    so it is asserted here.
    """
    index = {_norm(a): f for f, names in ALIASES.items() for a in names}
    broken = [(c["header"], c["field"], index.get(_norm(c["header"])))
              for c in COLUMNS if index.get(_norm(c["header"])) != c["field"]]
    if broken:
        detail = "; ".join(f"'{h}' declares '{want}' but reads back as {got!r}"
                           for h, want, got in broken)
        raise ValueError(f"tp_api_spec: template header(s) do not round-trip — {detail}.")


_assert_unique_aliases()
_assert_headers_round_trip()


# ── Vendor detection ─────────────────────────────────────────────────────────
# One file is one vendor, so this is computed once per upload from the header row and
# stored on every row as `source_format` (and mirrored into `data.vendor` so it can be
# filtered on).

MMT = "mmt-bookings-v1"
TBO = "tbo-statement-v1"

VENDOR_LABELS = {MMT: "MakeMyTrip", TBO: "TBO"}

#: Headers that only this vendor ships. Scored as a set intersection rather than matched
#: exactly, so an aggregator adding or dropping a column does not stop detection.
_MMT_SIG = {"booking_id", "lob", "booking_platform", "primary_traveller",
            "total_paid_amount", "e_coupon_amount", "promo_cash_amount", "my_cash"}
_TBO_SIG = {"product_type", "narration", "tbo_confirmation_no", "rateofexchange",
            "supplier_bill_number", "swachh_bharat_cess", "tcsdeclarationtype",
            "oxitrxid"}

_MIN_SIGNATURE_HITS = 3


def detect_format(columns: list[str]) -> str | None:
    """The vendor this header row belongs to, or None.

    None rather than a guess. A third aggregator's file still imports — its rows simply
    carry no vendor label and the Format column reads "—" — whereas guessing would write a
    provenance claim the file does not support, and provenance that is sometimes invented
    is worse than provenance that is sometimes absent.
    """
    keys = {_norm(c) for c in columns}
    mmt, tbo = len(keys & _MMT_SIG), len(keys & _TBO_SIG)
    if mmt >= _MIN_SIGNATURE_HITS and mmt > tbo:
        return MMT
    if tbo >= _MIN_SIGNATURE_HITS and tbo > mmt:
        return TBO
    return None


def format_label(source_format: str | None) -> str | None:
    return VENDOR_LABELS.get(source_format or "")


# ── Derived: the legacy cess fold ────────────────────────────────────────────
# Swachh Bharat and Krishi Kalyan were abolished in 2017 and the STX education cess long
# before that; TBO still ships all three, at 0.00 on every modern line. They are still READ
# — they just land added together instead of costing three columns of scrolling.
#
# WHY DERIVED RATHER THAN MAPPED, and why this is the same shape as ndc_spec's `Other
# Taxes`: the mapping screen maps one field to one source column, so "this field is three
# columns added up" cannot be expressed as a mapping. A file that carries its own
# `Legacy Cess` column maps it normally and the mapped value wins — that is what makes a
# file exported from our own Template round-trip.

LEGACY_CESS_HEADERS = [
    "SWACHH BHARAT CESS", "KRISHI KALYAN CESS", "EDU. CESS(STX) AMOUNT",
]
_LEGACY_CESS_KEYS = [_norm(h) for h in LEGACY_CESS_HEADERS]
_LEGACY_CESS_FIELD = "legacy_cess"


def to_decimal(value) -> Decimal | None:
    """"1,234.50" → Decimal("1234.50"); anything that is not a number → None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def derive(values: dict) -> dict:
    """{normalised source header: cleaned value} for ONE line → the fields to add to it.

    Returns ``{}`` when the line carries none of the three cess columns — an absent column
    and a genuine zero are different facts, and writing "0.00" for a file that never had
    them would invent a figure the vendor never sent.
    """
    total, seen = Decimal(0), False
    for key in _LEGACY_CESS_KEYS:
        n = to_decimal(values.get(key))
        if n is not None:
            total += n
            seen = True
    return {_LEGACY_CESS_FIELD: f"{total:.2f}"} if seen else {}


# ── Normalization ────────────────────────────────────────────────────────────
# Runs on the FINAL row — after the mapping, after `derive`, and after the reviewer's own
# corrections on the review step. That order is what makes the wizard's promise true
# ("dates and amounts are still normalised after you edit"): a user who types 13-08-2026 or
# 1,23,456.78 into a cell gets the same treatment the file's own value got.
#
# It is wired as the spec's `normalize_row`, NOT as `derive_row`, and the three reasons are
# worth stating because they are not obvious: `derive_row` is spread BEFORE the mapping
# (`{**extra, **data}`) so a mapped column would overwrite anything it normalised; it is
# keyed by SOURCE HEADER so it cannot see a canonical field at all; and it runs before the
# overrides, so a reviewer's correction would escape it.

_PRODUCT_TYPES = {
    "hotel": "Hotel", "hotels": "Hotel", "htl": "Hotel", "accommodation": "Hotel",
    "stay": "Hotel",
    "flight": "Flight", "flights": "Flight", "air": "Flight", "airline": "Flight",
    "domestic flight": "Flight", "international flight": "Flight",
    "train": "Train", "trains": "Train", "rail": "Train", "railways": "Train",
    "irctc": "Train",
    "bus": "Bus", "buses": "Bus", "coach": "Bus",
    "car": "Car", "cab": "Car", "cabs": "Car", "self drive": "Car",
    "selfdrive": "Car", "car rental": "Car",
}

_STATUSES = {
    "cancelled": "Cancelled", "canceled": "Cancelled", "cancel": "Cancelled",
    "pending payment": "Pending", "pending": "Pending", "payment pending": "Pending",
    "travelled": "Travelled", "traveled": "Travelled", "completed": "Travelled",
    "confirmed": "Confirmed", "booked": "Confirmed", "success": "Confirmed",
    "successful": "Confirmed",
    "refunded": "Refunded", "refund": "Refunded",
    "failed": "Failed", "failure": "Failed",
    "no show": "No Show", "noshow": "No Show",
}

#: Product vocabulary offered to the AI and shown in the Category facet.
PRODUCT_VALUES = ["Flight", "Hotel", "Train", "Bus", "Car"]

_DATE_FIELDS = (
    "transaction_date", "booking_date", "travel_date", "start_date", "end_date",
    "payment_due_date", "passport_issue_date", "passport_expiry_date",
)

#: Amounts, normalised to a bare numeric string. Load-bearing: the router's `_num` only
#: strips commas in SQL, so "(285.72)" or "₹1,234" would otherwise SUM as 0 in the summary
#: slab with nothing on screen to say so.
MONEY_FIELDS = (
    "rate_of_exchange", "base_fare", "taxes", "discount", "service_charges",
    "convenience_fee", "travel_insurance", "agent_markup", "cancellation_fee",
    "pg_charges", "net_amount", "total_paid_amount", "pending_amount", "wallet_amount",
    "pg_amount", "e_coupon_amount", "promo_cash_amount", "my_cash", "plus_amount",
    "refund_amount",
    "sgst_amount", "cgst_amount", "igst_amount", "total_gst", "service_tax_amount",
    "legacy_cess", "tds", "edu_cess_tds_amount", "tcs_amount",
    "catering_charge", "ers_pg_charges", "ers_agent_service_charge",
)

#: Normalised as numbers but deliberately NOT money — a rate is a percentage and a count is
#: a count. Keeping them out of MONEY_FIELDS is what stops `_num` summing percentages in the
#: summary slab and what stops the UI rendering "2 nights" as "2.00".
_RATE_FIELDS = ("sgst_rate", "cgst_rate", "igst_rate", "tcs_rate")
_COUNT_FIELDS = ("pax_count", "no_of_nights", "no_of_rooms", "no_of_vehicle",
                 "hotel_star_rating")

_YYYYMMDD = re.compile(r"^(19|20)\d{6}$")
#: TBO writes "lovekush singh X 1" — the pax count is a suffix on the name, not a column.
_PAX_SUFFIX = re.compile(r"\bX\s*(\d+)\s*$", re.I)


def to_iso_date(value) -> str | None:
    """ISO date, explicit formats first.

    Two traps this exists for, both from TBO's `DATE` column:

    * It is ``20260801`` — yyyymmdd, which none of ``flat_statement._DT_FORMATS`` matches.
      dateutil happens to read it correctly today, but leaving a known format to a
      fallback is how a library update silently changes every date in the table.
    * calamine and openpyxl may hand that cell back as a NUMBER, so the cleaned string is
      ``"20260801.0"`` — which dateutil rejects outright. The failure is invisible until a
      monthly bucket comes back empty.
    """
    s = _flat._clean(value)
    if not s:
        return None
    if s.endswith(".0") and s[:-2].isdigit():   # a numeric cell round-tripped via float
        s = s[:-2]
    if _YYYYMMDD.match(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return _flat.to_iso_date(s)                 # dayfirst=True — an Indian export prints 13-08-2026


def strip_pax_suffix(name) -> str | None:
    """"lovekush singh X 1" -> "lovekush singh". TBO writes the pax count onto the name.

    `normalize` already reads that count into `pax_count`, so by the time anything downstream
    sees the row the suffix is pure noise — but it is NOT only cosmetic, and that is the
    reason this is a public function rather than a display tweak in one template:

    * `customer_resolver.person_match_key` drops the "X" and the digit, so the EXACT-match
      path already works. It returns them as `dropped_initials` though, and a non-empty
      initials set is precisely what ENABLES the strict-subset fallback in
      `CustomerIndex.resolve`. So a TBO row can come back INITIALS_ONLY or AMBIGUOUS against
      a longer master name purely because of the suffix — a gap a human then has to clear by
      hand, for a reason that is not in the data.
    * `customer_resolver.split_person_name` has no such protection at all:
      "lovekush singh X 1" splits into first="lovekush singh X", last="1", which is what
      would land on the projected ticket.

    So it is stripped before RESOLVING, before PROJECTING and before DISPLAY. The original is
    kept on the ticket in `raw_data.passenger_name_raw`, and the count is already its own
    field, so nothing is lost.
    """
    s = _flat._clean(name)
    if not s:
        return None
    return _PAX_SUFFIX.sub("", s).strip() or s


def _map_value(raw: str | None, table: dict[str, str]) -> str | None:
    if raw is None:
        return None
    return table.get(" ".join(str(raw).split()).lower())


def normalize(data: dict) -> None:
    """Rewrite the mapped row in place: one product vocabulary, ISO dates, bare numbers.

    Mutates rather than returns, so the caller cannot accidentally drop the result.
    """
    # ── Product type ─────────────────────────────────────────────────────────
    # An UNRECOGNISED value passes through VERBATIM rather than becoming "Other". It then
    # appears in the Category facet, where a human notices a vendor's new product name and
    # adds it here — whereas "Other" would bury it. Note there are no single-letter keys:
    # TBO's CATEGORY of "R" is rail, but "C" is ambiguous between Car and Cancelled, and a
    # wrong product is worse than an unmapped one.
    known = _map_value(data.get("product_type"), _PRODUCT_TYPES)
    if known:
        data["product_type"] = known

    # ── Booking status ───────────────────────────────────────────────────────
    # MMT's vocabulary is the canonical one because TBO ships no status column at all.
    known = _map_value(data.get("booking_status"), _STATUSES)
    if known:
        data["booking_status"] = known
    elif not _flat._clean(data.get("booking_status")):
        # TBO says nothing about status directly, but an amended line names the amendment.
        # Stamping where it came from is this repo's existing idiom (`issue_date_source`,
        # `total_fare_source`) — an inferred value the user cannot tell from a read one is
        # how a reconciliation quietly goes wrong.
        amendment = _flat._clean(data.get("amendment_type"))
        if amendment and "cancel" in amendment.lower():
            data["booking_status"] = "Cancelled"
            data["booking_status_source"] = "amendment_type"

    # ── Pax count ────────────────────────────────────────────────────────────
    # A regex, not the AI: "<name> X <n>" is a fixed TBO convention, and spending a model
    # call on something `re` reads exactly is both slower and less reliable.
    if not _flat._clean(data.get("pax_count")):
        m = _PAX_SUFFIX.search(_flat._clean(data.get("passenger_name")) or "")
        if m:
            data["pax_count"] = m.group(1)

    # ── Dates ────────────────────────────────────────────────────────────────
    # A cell that will not parse KEEPS its original text and is flagged, rather than being
    # dropped or guessed at: the value stays visible on screen and in `raw_data`, and the
    # flag is what a reconciliation can filter on.
    failed = []
    for field in _DATE_FIELDS:
        raw = data.get(field)
        if not _flat._clean(raw):
            continue
        iso = to_iso_date(raw)
        if iso:
            data[field] = iso
        else:
            failed.append(field)
    if failed:
        data["date_parse_failed"] = ",".join(failed)

    # ── Amounts, rates and counts ────────────────────────────────────────────
    for field in (*MONEY_FIELDS, *_RATE_FIELDS, *_COUNT_FIELDS):
        raw = data.get(field)
        if not _flat._clean(raw):
            continue
        num = _flat.to_number_str(raw)
        if num is not None:
            data[field] = num


def stamp_vendor(data: dict, source_format: str | None) -> None:
    """Mirror the detected vendor into `data` so the drill-in can filter on it."""
    label = format_label(source_format)
    if label:
        data.setdefault("vendor", label)


# ── The AI narration pass ────────────────────────────────────────────────────
# Declared here rather than in the AI service so the router can answer "does this type have
# a free-text field at all?" without importing the OpenAI client.

#: The field whose free text the AI reads.
AI_SOURCE_FIELD = "narration"

#: The ONLY fields the AI may fill. The response schema is generated from this list with
#: `additionalProperties: false`, so the model cannot return an anomaly, a mapping
#: suggestion or a summary even if asked to — the scope is enforced by grammar, not by a
#: sentence in a prompt that a future edit could weaken.
AI_FILLABLE = (
    "train_name", "train_number", "flight_number", "airline_property_name",
    "origin", "origin_code", "destination", "destination_code",
    "travel_date", "start_date", "end_date", "no_of_nights", "vehicle_type",
)

AI_NARRATION = {
    "source_field": AI_SOURCE_FIELD,
    "fields": list(AI_FILLABLE),
    "date_fields": ["travel_date", "start_date", "end_date"],
    "upper_fields": ["origin_code", "destination_code", "train_number", "flight_number"],
    "label": "narration",
}


# ── Drill-in ─────────────────────────────────────────────────────────────────
# "select" is an exact match fed by /records/facets; "text" is a case-insensitive contains.
#
# `pan`, `guardian_pan`, `passport_no` and `mobile_number` are DELIBERATELY ABSENT and must
# stay absent: /records/facets returns up to 200 distinct values for every `select` filter,
# so a passport-number facet would be a bulk PII disclosure by construction. They remain
# stored, visible on the row and exportable — they are simply not a dropdown.
FILTERS = [
    {"field": "product_type",           "label": "Category",  "type": "select"},
    {"field": "vendor",                 "label": "Vendor",    "type": "select"},
    {"field": "booking_status",         "label": "Status",    "type": "select"},
    {"field": "booking_channel",        "label": "Channel",   "type": "select"},
    {"field": "intl_dom",               "label": "Intl/Dom",  "type": "select"},
    {"field": "booking_class",          "label": "Class",     "type": "select"},
    {"field": "quota",                  "label": "Quota",     "type": "select"},
    {"field": "booking_id",             "label": "Booking Id", "type": "text"},
    {"field": "invoice_number",         "label": "Invoice No", "type": "text"},
    {"field": "pnr",                    "label": "PNR",        "type": "text"},
    {"field": "confirmation_no",        "label": "Confirmation No", "type": "text"},
    {"field": "passenger_name",         "label": "Passenger",  "type": "text"},
    {"field": "airline_property_name",  "label": "Airline / Property", "type": "text"},
]

#: Totalled over the whole filtered set and shown in the slab above the table. `Net Amount`
#: and `Total Paid Amount` are both here on purpose — see the Money block above.
SUMMARY = [
    {"field": "base_fare",         "label": "Base Fare"},
    {"field": "taxes",             "label": "Taxes"},
    {"field": "total_gst",         "label": "Total GST"},
    {"field": "net_amount",        "label": "Net Amount"},
    {"field": "total_paid_amount", "label": "Total Paid"},
    {"field": "refund_amount",     "label": "Refund"},
]


# ── What the confirm step refuses, and what it merely warns about ────────────
# The split matters, and it is NOT the same split as flat_statement's. That rule demands a
# ticket number or a PNR, which an MMT hotel line simply does not have — applying it here
# would refuse every hotel row in the file. What actually makes a row unusable is having no
# identifier of ANY kind and no amount: it cannot be found, cannot be reconciled, and
# importing it would be a mis-mapping rather than a choice.
REQUIRED_GROUPS = [
    {"label": "a booking identifier",
     "fields": ["booking_id", "invoice_number", "confirmation_no", "reference_no",
                "tbo_confirmation_no", "pnr"],
     "headers": "Booking Id, Invoice Number, Confirmation No, Reference No or PNR"},
    {"label": "an amount",
     "fields": ["net_amount", "total_paid_amount", "base_fare", "taxes"],
     "headers": "Net Amount, Total Paid Amount, Base Fare or Taxes"},
]

# A real line that is simply harder to report on. Stored, searchable and visible — the user
# is told what they lose rather than blocked, because someone archiving a statement they
# only wanted on file should not be stopped.
ADVISORY_GROUPS = [
    {"label": "the product type",
     "fields": ["product_type"],
     "headers": "Product Type (MMT calls it Lob)",
     "consequence": "Without it every booking lands in one undifferentiated Category, so "
                    "hotels, flights and trains cannot be told apart or totalled separately."},
    {"label": "a date",
     "fields": ["transaction_date", "booking_date", "travel_date", "start_date"],
     "headers": "Transaction Date, Booking Date, Travel Date or Start Date",
     "consequence": "Rows without any date cannot be placed in a settlement period."},
]
