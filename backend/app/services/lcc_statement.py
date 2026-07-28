"""LCC Detailed Statement — unified multi-format normalizer.

LCC statements arrive in several different airline export formats with different
header names for the same field, 80+ named tax-code columns, multi-leg segment
columns (``First Leg`` / ``Second Leg`` …), and SSR columns. This module normalizes
ANY of them into one canonical shape:

    build_lcc_row(row, columns) -> {
        "source_format": str,           # detected format label
        "data":     {canonical_field: value, ...},   # mapped common fields
        "taxes":    [{"code", "amount"}, ...],        # folded per-code taxes/fees (unlimited)
        "segments": [{"leg", "route", "flight_no", "dep_date"}, ...],
        "ssr":      [{"code", "amount"}, ...],
        "raw_data": {original_header: value, ...},    # verbatim, for audit
    }

Technique lifted from ``services/ticket_extraction.py`` (alias map + wide-column
folding), kept self-contained (no ticket-schema coupling).
"""
from __future__ import annotations

import re

# ── header canonicalization (same rule as statement_spec.norm) ───────────────
def norm(header) -> str:
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


# ── canonical columns (order = repository display order) ─────────────────────
# (field, display header). `field` is the key stored in the row's `data` JSONB.
CANONICAL_COLUMNS: list[tuple[str, str]] = [
    ("transaction_datetime",     "Transaction Date/Time"),
    ("payment_datetime",         "Payment Date/Time"),
    ("payment_date",             "Payment Date"),
    ("booking_date",             "Booking Date"),
    ("departure_date",           "Departure Date"),
    ("pnr",                      "PNR"),
    ("parent_pnr",               "Parent PNR"),
    ("child_pnr",                "Child / Divided PNR"),
    ("record_locator",           "Record Locator"),
    ("transaction_type",         "Type"),
    ("payment_method",           "Payment Method"),
    ("payment_status",           "Payment Status"),
    ("passenger_name",           "Passenger"),
    ("passenger_count",          "Pax Count"),
    ("passenger_email",          "Email"),
    ("passenger_phone",          "Phone"),
    ("organization_name",        "Organization"),
    ("source_organization",      "Source Org"),
    ("source_organization_code", "Source Org Code"),
    ("agent_name",               "Agent"),
    ("source_agent_code",        "Source Agent Code"),
    ("created_agent_code",       "Created Agent Code"),
    ("received_by",              "Received By"),
    ("customer_number",          "Customer No"),
    ("account_transaction_id",   "Acct Txn ID"),
    ("reference",                "Reference"),
    ("payment_number",           "Payment No"),
    ("currency",                 "Currency"),
    ("payment_amount",           "Payment Amount"),
    ("transaction_amount",       "Txn Amount"),
    ("total_amount",             "Total"),
    ("base_fare",                "Base Fare"),
    ("ticket_fare",              "Ticket Fare"),
    ("airport_charges",          "Airport Charges"),
    ("taxes_total",              "Taxes (Total)"),
    ("other_fee_total",          "Other Fee Total"),
    ("other_ssr_total",          "Other SSR Total"),
    ("wfee",                     "WFEE"),
    ("tfee",                     "TFEE"),
    ("foreign_amount",           "Foreign Amount"),
    ("foreign_currency",         "Foreign Currency"),
    ("organization_amount",      "Org Amount"),
    ("organization_currency",    "Org Currency"),
    ("booking_promo_code",       "Promo Code"),
    ("promo_code_type",          "Promo Type"),
    ("segment_count",            "Segment Count"),
    ("product_class",            "Product Class"),
    ("international",            "Intl"),
    ("sector",                   "Sector"),
    ("gds_record_locator",       "GDS Locator"),
    ("gds_record_code",          "GDS Code"),
    ("gds_booking_system_code",  "GDS System"),
    ("gst_company_name",         "GST Company"),
    ("gst_number",               "GST No"),
    ("gst_email",                "GST Email"),
    ("fee_code",                 "Fee Code"),
    ("name",                     "Name"),
    ("at_created_utc",           "Created UTC"),
    ("note",                     "Note"),
]

DISPLAY_COLUMNS: list[dict] = [{"header": h, "field": f} for f, h in CANONICAL_COLUMNS]

# ── alias map: canonical field -> accepted header variants (already normalized) ──
LCC_ALIASES: dict[str, list[str]] = {
    "transaction_datetime":     ["transactiondatetime", "transaction_date", "transactiondate"],
    "payment_datetime":         ["paymentdtm"],
    "payment_date":             ["payment_date", "paymentdate"],
    "booking_date":             ["bookingdatetime", "bookingdate", "booking_date"],
    "departure_date":           ["departuredate", "departure_date"],
    "pnr":                      ["pnr"],
    "parent_pnr":               ["parentpnr", "parent_pnr"],
    "child_pnr":                ["childpnr", "child_pnr", "dividedpnr"],
    "record_locator":           ["recordlocator", "record_locator"],
    "transaction_type":         ["accounttransactiontype", "type"],
    "payment_method":           ["paymentmethodcode", "payment_method"],
    "payment_status":           ["paymentstatus"],
    "passenger_name":           ["paxname", "passenger_name", "name1"],
    "passenger_count":          ["paxcount", "pax_count"],
    "passenger_email":          ["emailaddress", "paxemailaddress"],
    "passenger_phone":          ["bookingcontactnumber", "paxcontact", "homephone"],
    "organization_name":        ["organizationname"],
    "source_organization":      ["sourceorganization"],
    "source_organization_code": ["sourceorganizationcode"],
    "agent_name":               ["agentname"],
    "source_agent_code":        ["sourceagentcode"],
    "created_agent_code":       ["createdagentcode"],
    "received_by":              ["receivedby"],
    "customer_number":          ["customernumber"],
    "account_transaction_id":   ["accounttransactionid"],
    "reference":                ["reference", "accountreference"],
    "payment_number":           ["paymentnumber"],
    "currency":                 ["currencycode", "currency"],
    "payment_amount":           ["paymentamount", "amount"],
    "transaction_amount":       ["acamount", "transactionamount"],
    "total_amount":             ["totalamount", "total"],
    "base_fare":                ["basefare"],
    "ticket_fare":              ["ticketfare"],
    "airport_charges":          ["airportcharges"],
    "taxes_total":              ["taxes"],
    "other_fee_total":          ["otherfeetotal"],
    "other_ssr_total":          ["otherssrtotal"],
    "wfee":                     ["wfee"],
    "tfee":                     ["tfee"],
    "foreign_amount":           ["foreignamount"],
    "foreign_currency":         ["foreigncurrencycode"],
    "organization_amount":      ["organizationamount"],
    "organization_currency":    ["organizationcurrency"],
    "booking_promo_code":       ["bookingpromocode", "promocode"],
    "promo_code_type":          ["promocode_type"],
    "segment_count":            ["segment_count"],
    "product_class":            ["productclass"],
    "international":            ["international"],
    "sector":                   ["sector"],
    "gds_record_locator":       ["gds_recordlocator"],
    "gds_record_code":          ["gds_recordcode"],
    "gds_booking_system_code":  ["gds_bookingsystemcode"],
    "gst_company_name":         ["gstcompanyname"],
    "gst_number":               ["gstnumber"],
    "gst_email":                ["gstemailaddress"],
    "fee_code":                 ["feecode"],
    "name":                     ["name"],
    "at_created_utc":           ["atcreatedutc"],
    "note":                     ["note"],
}

_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in LCC_ALIASES.items():
    for _a in _aliases:
        _ALIAS_TO_CANON[_a] = _canon

# repeating / structured column detectors
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
_LEG_RE = re.compile(r"^(" + "|".join(_ORDINALS) + r")_leg(_flight_no|_dep_date)?$")
_SSR_KEYS = {"ssrlist", "ssrcode", "ssramount"}


def _clean(value) -> str | None:
    if value is None:
        return None
    try:
        import math
        if isinstance(value, float) and math.isnan(value):
            return None
    except Exception:
        pass
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


def _to_num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def build_col_map(columns: list[str]) -> dict[str, str]:
    """{original_column -> canonical_field} via the alias map (first-wins per canonical)."""
    out: dict[str, str] = {}
    seen: set[str] = set()
    for col in columns:
        canon = _ALIAS_TO_CANON.get(norm(col))
        if canon and canon not in seen:
            out[col] = canon
            seen.add(canon)
    return out


def detect_format(columns: list[str]) -> str:
    nz = {norm(c) for c in columns}
    if "dividedpnr" in nz:
        return "divided-pnr"
    if "gds_recordlocator" in nz or "recordlocator" in nz:
        return "gds-payment"
    if "ssrlist" in nz:
        return "booking-detail"
    if "accounttransactionid" in nz:
        return "account"
    return "lcc"


def _fold_segments(columns: list[str], vals: dict, normcol: dict) -> list[dict]:
    legs: dict[int, dict] = {}
    for col in columns:
        m = _LEG_RE.match(norm(col))
        if not m:
            continue
        v = vals.get(col)
        if v is None:
            continue
        n = _ORDINALS[m.group(1)]
        sub = m.group(2)
        leg = legs.setdefault(n, {})
        if sub == "_flight_no":
            leg["flight_no"] = v
        elif sub == "_dep_date":
            leg["dep_date"] = v
        else:
            leg["route"] = v
    out = []
    for n in sorted(legs):
        d = {"leg": n}
        d.update(legs[n])
        out.append(d)
    # Fallback: a single "Sector" column (format-2) with no leg columns.
    if not out:
        sector = vals.get(normcol.get("sector"))
        if sector:
            out.append({"leg": 1, "route": sector})
    return out


def _fold_ssr(vals: dict, normcol: dict) -> list[dict]:
    out = []
    code = vals.get(normcol.get("ssrcode"))
    amount = vals.get(normcol.get("ssramount"))
    if code:
        out.append({"code": code, "amount": amount})
    lst = vals.get(normcol.get("ssrlist"))
    if lst:
        for part in re.split(r"[|,;]", str(lst)):
            p = part.strip()
            if p:
                out.append({"code": p, "amount": None})
    return out


def build_lcc_row(row, columns: list[str]) -> dict:
    """Normalize one raw row (pandas Series or dict) into the canonical shape."""
    vals = {c: _clean(row.get(c)) for c in columns}
    normcol = {norm(c): c for c in columns}
    colmap = build_col_map(columns)

    data = {field: vals[col] for col, field in colmap.items() if vals.get(col) is not None}
    segments = _fold_segments(columns, vals, normcol)
    ssr = _fold_ssr(vals, normcol)

    # taxes = every UNMAPPED, non-segment, non-SSR column with a non-zero numeric value.
    # Captures format-4's 80+ tax/fee codes (and any future code) with no hardcoded list.
    taxes = []
    for col in columns:
        if col in colmap:
            continue
        nz = norm(col)
        if nz in _SSR_KEYS or _LEG_RE.match(nz):
            continue
        v = vals.get(col)
        if v is None:
            continue
        n = _to_num(v)
        if n is None or n == 0:
            continue
        taxes.append({"code": str(col).strip(), "amount": v})

    raw_data = {str(c): vals[c] for c in columns if vals.get(c) is not None}
    return {
        "source_format": detect_format(columns),
        "data": data,
        "taxes": taxes,
        "segments": segments,
        "ssr": ssr,
        "raw_data": raw_data,
    }


# Uniform builder interface shared with di_statement (used by the generic router).
build_row = build_lcc_row
