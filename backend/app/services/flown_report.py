"""LCC Flown Report — normalizer.

A "flown report" is what an LCC/airline sends listing tickets/segments that have
actually been FLOWN (uplifted) in a period — the basis for revenue recognition and
flown-based incentive calculation. It's a flat per-flown-segment ledger: flight & date,
sector, PNR/ticket, passenger, fare/tax/total, commission/incentive, and a flown status.

No real sample was provided, so this is a sensible superset schema with a tolerant alias
map (many header synonyms) so a real airline export maps cleanly later. Same parser-hook
shape as di_statement / divided_pnr (`build_col_map` + `build_row`); flat — no folded
taxes/segments/ssr (a single "taxes total" is a canonical column).
"""
from __future__ import annotations

import math
import re


def norm(header) -> str:
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


CANONICAL_COLUMNS: list[tuple[str, str]] = [
    ("flown_date",                "Flown Date"),
    ("travel_date",               "Travel Date"),
    ("booking_date",              "Booking Date"),
    ("pnr",                       "PNR"),
    ("ticket_number",             "Ticket No"),
    ("airline_code",              "Airline"),
    ("flight_number",             "Flight No"),
    ("origin",                    "From"),
    ("destination",               "To"),
    ("sector",                    "Sector"),
    ("booking_class",             "Class"),
    ("cabin",                     "Cabin"),
    ("fare_basis",                "Fare Basis"),
    ("passenger_name",            "Passenger"),
    ("passenger_count",           "Pax"),
    ("base_fare",                 "Base Fare"),
    ("taxes",                     "Taxes"),
    ("total_fare",                "Total Fare"),
    ("currency",                  "Currency"),
    ("commission_amount",         "Commission"),
    ("commission_rate",           "Comm %"),
    ("incentive_amount",          "Incentive"),
    ("net_fare",                  "Net Fare"),
    ("flown_status",              "Status"),
    ("coupon_status",             "Coupon Status"),
    ("agency_code",               "Agency Code"),
    ("agent_name",                "Agent"),
    ("source_organization_code",  "Source Org Code"),
    ("booking_promo_code",        "Promo Code"),
    ("payment_method",            "Payment Method"),
    ("product_class",             "Product Class"),
]
DISPLAY_COLUMNS: list[dict] = [{"header": h, "field": f} for f, h in CANONICAL_COLUMNS]

FLOWN_ALIASES: dict[str, list[str]] = {
    "flown_date":               ["flown_date", "flowndate", "uplift_date", "upliftdate", "flying_date"],
    "travel_date":              ["travel_date", "traveldate", "traveldt", "flight_date", "flightdate", "journey_date", "departure_date", "departuredate"],
    "booking_date":             ["booking_date", "bookingdate", "bookingdatetime"],
    "pnr":                      ["pnr", "record_locator", "recordlocator", "booking_reference", "bookingreference", "gds_pnr", "gdspnr"],
    "ticket_number":            ["ticket_number", "ticketnumber", "ticket_no", "ticketno", "document_number", "documentnumber"],
    "airline_code":             ["airline_code", "airlinecode", "airline", "carrier", "carrier_code", "carriercode", "air_code", "aircode"],
    "flight_number":            ["flight_number", "flightnumber", "flight_no", "flightno", "flight"],
    "origin":                   ["origin", "from", "source", "dep", "departure_airport", "depairport", "sector_from"],
    "destination":              ["destination", "to", "dest", "arr", "arrival_airport", "arrairport", "sector_to"],
    "sector":                   ["sector", "sectors", "route", "segment"],
    "booking_class":            ["booking_class", "bookingclass", "class", "rbd", "fare_class"],
    "cabin":                    ["cabin", "cabin_class", "cabinclass"],
    "fare_basis":               ["fare_basis", "farebasis"],
    "passenger_name":           ["passenger_name", "passengername", "pax_name", "paxname", "name"],
    "passenger_count":          ["passenger_count", "paxcount", "pax_count", "pax", "seats", "seat_count"],
    "base_fare":                ["base_fare", "basefare", "fare"],
    "taxes":                    ["taxes", "tax", "total_tax", "totaltax"],
    "total_fare":               ["total_fare", "totalfare", "total_amount", "totalamount", "total", "gross_fare", "grossfare"],
    "currency":                 ["currency", "currency_code", "currencycode"],
    "commission_amount":        ["commission_amount", "commissionamount", "comm_amount", "commamount", "commission"],
    "commission_rate":          ["commission_rate", "commissionrate", "comm_percent", "commpercent", "comm", "commission_percent"],
    "incentive_amount":         ["incentive_amount", "incentiveamount", "incentive", "plb", "incentive_earned"],
    "net_fare":                 ["net_fare", "netfare", "net_amount", "netamount", "net_remit", "netremit"],
    "flown_status":             ["flown_status", "flownstatus", "status", "flight_status", "flightstatus", "segment_status"],
    "coupon_status":            ["coupon_status", "couponstatus"],
    "agency_code":              ["agency_code", "agencycode", "agent_code", "agentcode"],
    "agent_name":               ["agent_name", "agentname", "agency_name", "agencyname"],
    "source_organization_code": ["source_organization_code", "sourceorganizationcode", "source_org_code", "organization_code", "organizationcode", "source_organization"],
    "booking_promo_code":       ["booking_promo_code", "bookingpromocode", "promo_code", "promocode"],
    "payment_method":           ["payment_method", "paymentmethodcode", "payment_method_code", "fop"],
    "product_class":            ["product_class", "productclass"],
}

_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in FLOWN_ALIASES.items():
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
    return "flown-report"


def build_row(row, columns: list[str]) -> dict:
    """Normalize one raw Flown-Report row (pandas Series or dict) into the canonical shape."""
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
