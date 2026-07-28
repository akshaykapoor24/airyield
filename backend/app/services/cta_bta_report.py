"""LCC CTA/BTA Report — normalizer.

CTA = Central Travel Account, BTA = Business Travel Account: centrally-billed
"lodged account" arrangements (UATP / AirPlus / Diners / lodged cards) where a
company's air travel is charged to a single settlement account instead of each
traveller's own card. The CTA/BTA report an LCC/airline (or the scheme provider)
sends is a per-transaction ledger reconciling everything charged to that account
in a period: the account reference, PNR/ticket, passenger, sector, amounts, the
card scheme, and a settlement status.

No real sample was provided, so this is a sensible superset schema with a tolerant
alias map (many header synonyms) so a real export maps cleanly later. Same
parser-hook shape as di_statement / divided_pnr / flown_report (`build_col_map` +
`build_row`); flat — no folded taxes/segments/ssr (a single "taxes total" is a
canonical column).
"""
from __future__ import annotations

import math
import re


def norm(header) -> str:
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


CANONICAL_COLUMNS: list[tuple[str, str]] = [
    ("account_type",       "Account Type"),      # CTA | BTA
    ("account_number",     "Account No"),         # lodged card / account reference (masked)
    ("account_name",       "Account Name"),       # company / corporate the account belongs to
    ("transaction_date",   "Transaction Date"),   # charge / settlement date
    ("booking_date",       "Booking Date"),
    ("travel_date",        "Travel Date"),
    ("pnr",                "PNR"),
    ("ticket_number",      "Ticket No"),
    ("invoice_number",     "Invoice No"),
    ("passenger_name",     "Passenger"),
    ("airline_code",       "Airline"),
    ("flight_number",      "Flight No"),
    ("origin",             "From"),
    ("destination",        "To"),
    ("sector",             "Sector"),
    ("booking_class",      "Class"),
    ("base_fare",          "Base Fare"),
    ("taxes",              "Taxes"),
    ("fee_amount",         "Fees"),
    ("total_amount",       "Total Amount"),
    ("currency",           "Currency"),
    ("card_scheme",        "Card Scheme"),        # UATP / AirPlus / Diners / Visa …
    ("merchant_name",      "Merchant"),
    ("reference_number",   "Reference No"),
    ("agency_code",        "Agency Code"),
    ("agent_name",         "Agent"),
    ("payment_status",     "Status"),
    ("remarks",            "Remarks"),
]
DISPLAY_COLUMNS: list[dict] = [{"header": h, "field": f} for f, h in CANONICAL_COLUMNS]

CTA_BTA_ALIASES: dict[str, list[str]] = {
    "account_type":     ["account_type", "accounttype", "cta_bta", "ctabta", "cta_bta_type", "type", "lodge_type", "lodgetype"],
    "account_number":   ["account_number", "accountnumber", "account_no", "accountno", "lodged_card", "lodgedcard", "lodge_card", "card_number", "cardnumber", "uatp_number", "uatpnumber", "account_ref", "accountref"],
    "account_name":     ["account_name", "accountname", "company", "company_name", "companyname", "corporate", "corporate_name", "corporatename", "client", "client_name", "clientname"],
    "transaction_date": ["transaction_date", "transactiondate", "txn_date", "txndate", "charge_date", "chargedate", "billing_date", "billingdate", "settlement_date", "settlementdate", "posting_date", "postingdate"],
    "booking_date":     ["booking_date", "bookingdate", "bookingdatetime", "issue_date", "issuedate"],
    "travel_date":      ["travel_date", "traveldate", "traveldt", "flight_date", "flightdate", "journey_date", "departure_date", "departuredate"],
    "pnr":              ["pnr", "record_locator", "recordlocator", "booking_reference", "bookingreference", "gds_pnr", "gdspnr"],
    "ticket_number":    ["ticket_number", "ticketnumber", "ticket_no", "ticketno", "document_number", "documentnumber"],
    "invoice_number":   ["invoice_number", "invoicenumber", "invoice_no", "invoiceno", "bill_number", "billnumber", "bill_no", "billno"],
    "passenger_name":   ["passenger_name", "passengername", "pax_name", "paxname", "name", "traveller_name", "travellername", "traveler_name", "travelername"],
    "airline_code":     ["airline_code", "airlinecode", "airline", "carrier", "carrier_code", "carriercode", "air_code", "aircode"],
    "flight_number":    ["flight_number", "flightnumber", "flight_no", "flightno", "flight"],
    "origin":           ["origin", "from", "source", "dep", "departure_airport", "depairport", "sector_from"],
    "destination":      ["destination", "to", "dest", "arr", "arrival_airport", "arrairport", "sector_to"],
    "sector":           ["sector", "sectors", "route", "segment"],
    "booking_class":    ["booking_class", "bookingclass", "class", "rbd", "fare_class"],
    "base_fare":        ["base_fare", "basefare", "fare", "amount", "net_amount", "netamount"],
    "taxes":            ["taxes", "tax", "total_tax", "totaltax"],
    "fee_amount":       ["fee_amount", "feeamount", "fee", "fees", "service_fee", "servicefee", "surcharge"],
    "total_amount":     ["total_amount", "totalamount", "total", "gross_amount", "grossamount", "amount_charged", "amountcharged", "charged_amount", "chargedamount", "total_fare", "totalfare"],
    "currency":         ["currency", "currency_code", "currencycode"],
    "card_scheme":      ["card_scheme", "cardscheme", "scheme", "card_type", "cardtype", "product", "card_product", "cardproduct"],
    "merchant_name":    ["merchant_name", "merchantname", "merchant", "supplier", "supplier_name", "suppliername", "provider"],
    "reference_number": ["reference_number", "referencenumber", "reference_no", "referenceno", "reference", "ref_no", "refno", "transaction_reference", "transactionreference", "auth_code", "authcode"],
    "agency_code":      ["agency_code", "agencycode", "agent_code", "agentcode"],
    "agent_name":       ["agent_name", "agentname", "agency_name", "agencyname"],
    "payment_status":   ["payment_status", "paymentstatus", "status", "settlement_status", "settlementstatus", "txn_status", "txnstatus"],
    "remarks":          ["remarks", "remark", "notes", "note", "narration", "description"],
}

_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in CTA_BTA_ALIASES.items():
    for _a in _aliases:
        _ALIAS_TO_CANON[_a] = _canon


def _clean(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


def build_col_map(columns: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    seen: set[str] = set()
    for col in columns:
        canon = _ALIAS_TO_CANON.get(norm(col))
        if canon and canon not in seen:
            out[col] = canon
            seen.add(canon)
    return out


def detect_format(columns: list[str]) -> str:
    return "cta-bta"


def build_row(row, columns: list[str]) -> dict:
    """Normalize one raw CTA/BTA row (pandas Series or dict) into the canonical shape."""
    vals = {c: _clean(row.get(c)) for c in columns}
    colmap = build_col_map(columns)
    data = {field: vals[col] for col, field in colmap.items() if vals.get(col) is not None}
    raw_data = {str(c): vals[c] for c in columns if vals.get(c) is not None}
    return {
        "source_format": detect_format(columns),
        "data": data,
        "taxes": [],
        "segments": [],
        "ssr": [],
        "raw_data": raw_data,
    }
