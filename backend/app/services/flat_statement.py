"""Generic flat-statement normalizer for simple ledger types.

Many statement types are "flat": a per-row ledger normalized to canonical fields via a
tolerant alias map, with no folded taxes/segments/SSR. Rather than a near-duplicate module
per type, register a config here (display columns + alias map + a source-format label); the
router resolves a bound builder by parser name and calls the same `build_col_map(cols)` /
`build_row(row, cols)` interface as the per-type modules.

Currently hosts the **Third Party** types (a consolidator/big-agency sends the sub-agency a
GDS or LCC statement of the bookings it made through them). No real templates were provided,
so these are sensible superset schemas with tolerant aliases — a real export maps cleanly
later by tweaking the alias map (no table/migration change).
"""
from __future__ import annotations

import math
import re


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


class _FlatBuilder:
    """Bound builder — same interface as the per-type parser modules."""

    def __init__(self, display_columns: list[dict], aliases: dict[str, list[str]], source_format: str):
        self.display_columns = display_columns
        self._a2c = {v: k for k, vs in aliases.items() for v in vs}
        self._fmt = source_format

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
        return {"source_format": self._fmt, "data": data, "taxes": [], "segments": [], "ssr": [], "raw_data": raw_data}


_REGISTRY: dict[str, _FlatBuilder] = {}


def _cols(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"header": h, "field": f} for f, h in pairs]


def register(parser_name: str, columns: list[tuple[str, str]], aliases: dict[str, list[str]], source_format: str) -> list[dict]:
    b = _FlatBuilder(_cols(columns), aliases, source_format)
    _REGISTRY[parser_name] = b
    return b.display_columns


def get(parser_name: str) -> _FlatBuilder | None:
    return _REGISTRY.get(parser_name)


# ── shared alias fragments (a consolidator statement, GDS or LCC) ─────────────
_COMMON_ALIASES = {
    "transaction_date":  ["transaction_date", "transactiondate", "txn_date", "trans_date", "date", "transaction_dtm"],
    "travel_date":       ["travel_date", "traveldate", "traveldt", "flight_date", "flightdate", "departure_date", "departuredate", "journey_date"],
    "pnr":               ["pnr", "record_locator", "recordlocator", "booking_reference", "bookingreference"],
    "transaction_type":  ["transaction_type", "transactiontype", "type", "txn_type", "trans_type"],
    "airline_code":      ["airline_code", "airlinecode", "airline", "carrier", "carrier_code", "carriercode"],
    "sector":            ["sector", "sectors", "route", "segment"],
    "flight_number":     ["flight_number", "flightnumber", "flight_no", "flightno", "flight"],
    "passenger_name":    ["passenger_name", "passengername", "pax_name", "paxname", "name"],
    "passenger_count":   ["passenger_count", "paxcount", "pax_count", "pax"],
    "base_fare":         ["base_fare", "basefare", "fare"],
    "taxes":             ["taxes", "tax", "total_tax", "totaltax"],
    "total_fare":        ["total_fare", "totalfare", "total_amount", "totalamount", "total", "gross", "gross_amount", "grossamount"],
    "currency":          ["currency", "currency_code", "currencycode"],
    "commission_amount": ["commission_amount", "commissionamount", "comm_amount", "commamount", "commission"],
    "markup":            ["markup", "mark_up", "service_charge", "servicecharge", "agency_markup", "margin"],
    "net_amount":        ["net_amount", "netamount", "net", "net_payable", "netpayable", "net_remit", "netremit", "amount", "payable"],
    "invoice_number":    ["invoice_number", "invoicenumber", "invoice_no", "invoiceno", "invoice"],
    "agency_code":       ["agency_code", "agencycode", "agent_code", "agentcode", "sub_agent", "subagent", "sub_agent_code", "subagentcode"],
    "consolidator_name": ["consolidator_name", "consolidator", "consolidatorname", "supplier", "supplier_name", "suppliername", "vendor", "source_agency", "sourceagency", "parent_agency"],
    "payment_status":    ["payment_status", "paymentstatus", "status"],
    "remarks":           ["remarks", "remark", "narration", "note", "notes", "details", "description"],
}


# ── Third Party GDS ──────────────────────────────────────────────────────────
_TP_GDS_COLUMNS = [
    ("transaction_date", "Transaction Date"), ("issue_date", "Issue Date"), ("travel_date", "Travel Date"),
    ("pnr", "PNR"), ("gds_pnr", "GDS PNR"), ("ticket_number", "Ticket No"), ("transaction_type", "Type"),
    ("airline_code", "Airline"), ("sector", "Sector"), ("flight_number", "Flight No"),
    ("passenger_name", "Passenger"), ("passenger_count", "Pax"), ("booking_class", "Class"),
    ("base_fare", "Base Fare"), ("taxes", "Taxes"), ("yq", "YQ"), ("total_fare", "Total Fare"),
    ("currency", "Currency"), ("commission_amount", "Commission"), ("commission_rate", "Comm %"),
    ("markup", "Markup"), ("service_fee", "Service Fee"), ("tds", "TDS"), ("net_amount", "Net Amount"),
    ("invoice_number", "Invoice No"), ("agency_code", "Agency Code"), ("consolidator_name", "Consolidator"),
    ("gds", "GDS"), ("payment_status", "Payment Status"), ("remarks", "Remarks"),
]
_TP_GDS_ALIASES = {
    **_COMMON_ALIASES,
    "issue_date":      ["issue_date", "issuedate", "date_of_issue", "dateofissue", "ticket_date", "ticketdate"],
    "gds_pnr":         ["gds_pnr", "gdspnr", "gds_record_locator", "gdsrecordlocator"],
    "ticket_number":   ["ticket_number", "ticketnumber", "ticket_no", "ticketno", "document_number", "documentnumber"],
    "booking_class":   ["booking_class", "bookingclass", "class", "rbd"],
    "yq":              ["yq", "yq_tax", "yqtax", "fuel_surcharge", "fuelsurcharge"],
    "commission_rate": ["commission_rate", "commissionrate", "comm_percent", "commpercent", "comm", "commission_percent"],
    "service_fee":     ["service_fee", "servicefee", "transaction_fee", "transactionfee", "booking_fee", "bookingfee"],
    "tds":             ["tds", "tds_amount", "tdsamount"],
    "gds":             ["gds", "gds_name", "gdsname", "booking_system", "bookingsystem"],
}
TP_GDS_DISPLAY = register("tp-gds", _TP_GDS_COLUMNS, _TP_GDS_ALIASES, "third-party-gds")


# ── Third Party LCC ──────────────────────────────────────────────────────────
_TP_LCC_COLUMNS = [
    ("transaction_date", "Transaction Date"), ("booking_date", "Booking Date"), ("travel_date", "Travel Date"),
    ("pnr", "PNR"), ("airline_pnr", "Airline PNR"), ("transaction_type", "Type"), ("airline_code", "Airline"),
    ("sector", "Sector"), ("flight_number", "Flight No"), ("passenger_name", "Passenger"),
    ("passenger_count", "Pax"), ("base_fare", "Base Fare"), ("taxes", "Taxes"),
    ("convenience_fee", "Convenience Fee"), ("other_charges", "Other Charges"), ("total_fare", "Total Fare"),
    ("currency", "Currency"), ("markup", "Markup"), ("commission_amount", "Commission"),
    ("incentive_amount", "Incentive"), ("net_amount", "Net Amount"), ("payment_method", "Payment Method"),
    ("booking_reference", "Booking Ref"), ("invoice_number", "Invoice No"), ("agency_code", "Agency Code"),
    ("consolidator_name", "Consolidator"), ("payment_status", "Payment Status"), ("remarks", "Remarks"),
]
_TP_LCC_ALIASES = {
    **_COMMON_ALIASES,
    "booking_date":     ["booking_date", "bookingdate", "bookingdatetime"],
    "airline_pnr":      ["airline_pnr", "airlinepnr", "air_pnr", "airpnr", "carrier_pnr"],
    "convenience_fee":  ["convenience_fee", "conveniencefee", "conv_fee", "convfee"],
    "other_charges":    ["other_charges", "othercharges", "other_fee", "otherfee", "misc_charges", "addon", "add_on_charges"],
    "incentive_amount": ["incentive_amount", "incentiveamount", "incentive", "plb"],
    "payment_method":   ["payment_method", "paymentmethodcode", "payment_method_code", "fop", "payment_mode"],
    "booking_reference": ["booking_reference", "bookingreference", "booking_ref", "bookingref", "reference"],
}
TP_LCC_DISPLAY = register("tp-lcc", _TP_LCC_COLUMNS, _TP_LCC_ALIASES, "third-party-lcc")
