"""LCC Detailed Statement — standard 129-column spec + typed-row builder.

Single source of truth for the LCC Detailed "standard template": the exact ordered
columns a user downloads, fills and uploads, and the rules that route each column's
value into the redesigned ``lcc_detailed`` table:

  * 27 CORE columns  -> typed columns on the row (dates, money, codes, flags)
  * 87 TAX/FEE codes -> folded into ``taxes``    JSONB [{code, amount}] (non-zero only)
  * 15 LEG columns   -> folded into ``segments`` JSONB [{leg, route, flight_no, dep_date}]

Header auto-matching and value cleaning reuse the helpers in
``services/lcc_statement.py`` (``norm``, ``_clean``, ``LCC_ALIASES``) so the same
per-airline header aliasing that the old parser used still applies.

The mapping the API/worker pass around is ``{standard_field: xls_column}`` — never
inverted, because two standard fields may legitimately point at the same source column.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services.lcc_statement import norm, _clean, LCC_ALIASES


# ── column spec ──────────────────────────────────────────────────────────────
# Each CORE entry: (display header, snake_case field, dtype, alias_key, maxlen)
# `alias_key` is the canonical field in LCC_ALIASES used for fuzzy fallback matching
# when a non-template file doesn't have the exact header. `maxlen` guards typed str
# columns against over-length values.
_CORE: list[tuple] = [
    ("Transaction Date",        "transaction_date",         "datetime", "transaction_datetime",     None),
    ("Name",                    "name",                     "str",      "name",                     255),
    ("PaymentDtm",              "payment_datetime",         "datetime", "payment_datetime",         None),
    ("PaymentMethodCode",       "payment_method_code",      "str",      "payment_method",           40),
    ("PaymentAmount",           "payment_amount",           "numeric",  "payment_amount",           None),
    ("PaymentNumber",           "payment_number",           "str",      "payment_number",           60),
    ("BookingDate",             "booking_date",             "datetime", "booking_date",             None),
    ("RecordLocator",           "record_locator",           "str",      "record_locator",           20),
    ("SourceOrganizationCode",  "source_organization_code", "str",      "source_organization_code", 40),
    ("BookingPromoCode",        "booking_promo_code",       "str",      "booking_promo_code",       60),
    ("ReceivedBy",              "received_by",              "str",      "received_by",              120),
    ("SourceAgentCode",         "source_agent_code",        "str",      "source_agent_code",        60),
    ("International",           "international",             "bool",     "international",            None),
    ("CurrencyCode",            "currency_code",            "str",      "currency",                 8),
    ("ProductClass",            "product_class",            "str",      "product_class",            40),
    ("PaxCount",                "pax_count",                "int",      "passenger_count",          None),
    ("Name1",                   "name1",                    "str",      "passenger_name",           255),
    ("EmailAddress",            "email_address",            "str",      "passenger_email",          255),
    ("HomePhone",               "home_phone",               "str",      "passenger_phone",          60),
    ("GDS_recordcode",          "gds_record_code",          "str",      "gds_record_code",          40),
    ("GDS_recordlocator",       "gds_record_locator",       "str",      "gds_record_locator",       20),
    ("GDS_BookingSystemCode",   "gds_booking_system_code",  "str",      "gds_booking_system_code",  40),
    ("PaymentStatus",           "payment_status",           "str",      "payment_status",           40),
    ("Total",                   "total",                    "numeric",  "total_amount",             None),
    ("BaseFare",                "base_fare",                "numeric",  "base_fare",                None),
    ("OtherFeeTotal",           "other_fee_total",          "numeric",  "other_fee_total",          None),
    ("OtherSSRTotal",           "other_ssr_total",          "numeric",  "other_ssr_total",          None),
]

# 87 named tax/fee codes — each folds into `taxes` by its own code, no fixed columns.
_TAX_CODES: list[str] = [
    "AE", "ASF", "BD", "BKF", "BQ", "C4", "CCF", "CFB", "CHG", "CNX", "COS", "CXL",
    "D5", "E3", "E5", "E7", "F6", "FEE", "G1", "G4", "G8", "GST", "GZ", "H8", "H9",
    "I2", "IGT", "IO", "JC", "KW", "L7", "LK", "M6", "MY", "N4", "NMV", "NP", "NQ",
    "NXT", "OM", "OP", "OVG", "OW", "P7", "P8", "PHF", "PSF", "PSFR", "PZ", "QA",
    "R9", "RAF", "RCF", "S6", "SG", "SXL", "T2", "T6", "TF", "TP", "TR", "TS", "UDF",
    "UDFR", "UT", "XXPN", "YX", "ZR", "ABHF", "AGSW", "CJSW", "CPML", "FFWD", "FRCK",
    "INFT", "JNML", "LCML", "NUSW", "PROT", "PTSW", "SEAT", "UPMA", "VBIR", "VCSW",
    "VGAN", "XBPA", "XBPB",
]

_ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth"]   # up to 5 legs

GROUP_CORE = "Core"
GROUP_TAX = "Taxes & Fees"
GROUP_LEG = "Legs"


def _build_columns() -> list[dict]:
    cols: list[dict] = []
    for header, field, dtype, alias_key, maxlen in _CORE:
        cols.append({"header": header, "field": field, "role": "core",
                     "dtype": dtype, "group": GROUP_CORE, "alias_key": alias_key, "maxlen": maxlen})
    for code in _TAX_CODES:
        cols.append({"header": code, "field": f"tax_{norm(code)}", "role": "tax",
                     "dtype": "numeric", "group": GROUP_TAX})
    for i, ordinal in enumerate(_ORDINALS, start=1):
        cols.append({"header": f"{ordinal} Leg", "field": f"leg{i}_route", "role": "leg",
                     "dtype": "str", "group": GROUP_LEG, "leg_no": i, "slot": "route"})
        cols.append({"header": f"{ordinal} Leg Flight No", "field": f"leg{i}_flight_no", "role": "leg",
                     "dtype": "str", "group": GROUP_LEG, "leg_no": i, "slot": "flight_no"})
        cols.append({"header": f"{ordinal} Leg Dep Date", "field": f"leg{i}_dep_date", "role": "leg",
                     "dtype": "str", "group": GROUP_LEG, "leg_no": i, "slot": "dep_date"})
    return cols


LCC_STANDARD_COLUMNS: list[dict] = _build_columns()
LCC_STANDARD_HEADERS: list[str] = [c["header"] for c in LCC_STANDARD_COLUMNS]

# Core columns only — used to flatten typed rows for the /records display grid.
CORE_COLUMNS: list[dict] = [c for c in LCC_STANDARD_COLUMNS if c["role"] == "core"]
_CORE_FIELDS: list[str] = [c["field"] for c in CORE_COLUMNS]


def grouped_columns() -> list[dict]:
    """[{group, columns:[{header, field, role, dtype}]}] for the mapping UI."""
    order = [GROUP_CORE, GROUP_TAX, GROUP_LEG]
    out: list[dict] = []
    for g in order:
        cols = []
        for c in LCC_STANDARD_COLUMNS:
            if c["group"] != g:
                continue
            item = {"header": c["header"], "field": c["field"], "role": c["role"], "dtype": c["dtype"]}
            if c["role"] == "leg":
                item["leg_no"] = c["leg_no"]
                item["slot"] = c["slot"]
            cols.append(item)
        out.append({"group": g, "columns": cols})
    return out


# ── auto-match ───────────────────────────────────────────────────────────────
def suggest_mapping(xls_columns: list[str]) -> tuple[dict[str, str], int, bool]:
    """Best-guess {standard_field: xls_column}.

    1. Direct: xls column whose norm() equals norm(standard header) — the fill-the-
       template case resolves 100%.
    2. Fallback (core only): LCC_ALIASES variants, so a raw airline export still
       auto-fills the core fields.

    Returns (mapping, matched_columns, is_template_match).
    """
    norm_xls: dict[str, str] = {}
    for c in xls_columns:
        norm_xls.setdefault(norm(c), str(c))

    mapping: dict[str, str] = {}
    direct = 0
    for col in LCC_STANDARD_COLUMNS:
        field = col["field"]
        exact = norm_xls.get(norm(col["header"]))
        if exact is not None:
            mapping[field] = exact
            direct += 1
            continue
        if col["role"] == "core":
            for alias in LCC_ALIASES.get(col.get("alias_key") or "", []):
                if alias in norm_xls:
                    mapping[field] = norm_xls[alias]
                    break

    is_template_match = direct == len(LCC_STANDARD_COLUMNS)
    return mapping, len(mapping), is_template_match


# ── value coercion ───────────────────────────────────────────────────────────
_NUMERIC_MAX = Decimal(10) ** 12   # NUMERIC(14,2) holds at most 12 integer digits
_SMALLINT_MIN, _SMALLINT_MAX = -32768, 32767   # pax_count is SMALLINT


def _to_decimal(v):
    """Parse money/number, tolerant of thousands separators and currency symbols.
    Returns None if the value can't fit NUMERIC(14,2) (so a stray large id/phone in a
    numeric-mapped column is dropped rather than crashing the whole insert)."""
    if v is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(v))
    if s in ("", "-", ".", "-.", "."):
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    if d.copy_abs() >= _NUMERIC_MAX:
        return None
    return d


# Common explicit formats — a fallback if dateutil isn't importable, and faster too.
_DT_FORMATS = (
    "%d-%b-%Y %I:%M:%S %p", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y",
)


def _to_datetime(v):
    from datetime import datetime as _dt
    s = _clean(v)
    if not s:
        return None
    for fmt in _DT_FORMATS:
        try:
            return _dt.strptime(s, fmt)
        except ValueError:
            continue
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(s, dayfirst=True)
    except Exception:  # noqa: BLE001
        return None


def _to_date(v):
    dt = _to_datetime(v)
    return dt.date() if dt else None


_TRUE = {"true", "1", "yes", "y", "t", "international", "intl", "i"}
_FALSE = {"false", "0", "no", "n", "f", "domestic", "dom", "d"}


def _to_bool(v):
    s = _clean(v)
    if s is None:
        return None
    k = s.strip().lower()
    if k in _TRUE:
        return True
    if k in _FALSE:
        return False
    return None


def _to_int(v):
    """Parse an integer; returns None if outside SMALLINT range so a mis-mapped value
    (e.g. a phone number in the PaxCount column) can never overflow the column."""
    d = _to_decimal(v)
    if d is None:
        return None
    try:
        n = int(d)
    except (ValueError, OverflowError):
        return None
    if n < _SMALLINT_MIN or n > _SMALLINT_MAX:
        return None
    return n


def _coerce(dtype: str, value, maxlen=None):
    if dtype == "datetime":
        return _to_datetime(value)
    if dtype == "date":
        return _to_date(value)
    if dtype == "numeric":
        return _to_decimal(value)
    if dtype == "int":
        return _to_int(value)
    if dtype == "bool":
        return _to_bool(value)
    s = _clean(value)
    if s is not None and maxlen:
        s = s[:maxlen]
    return s


# ── row builder (used by the Celery worker) ──────────────────────────────────
def build_typed_row(raw_row: dict, column_map: dict[str, str]) -> dict | None:
    """Route one raw source row through the mapping into a typed row dict.

    ``raw_row`` = {xls_column: value}, ``column_map`` = {standard_field: xls_column}.
    Returns a COMPLETE typed row dict (every column key present — required for
    executemany bulk insert; Decimals/dates kept for typed columns) minus provenance
    (tenant_id/created_by_id/batch_id are added by the caller), or ``None`` for a blank row.
    """
    row: dict = {f: None for f in _CORE_FIELDS}   # complete key set (uniform for executemany)
    has_core = False
    taxes: list[dict] = []
    legs: dict[int, dict] = {}

    for col in LCC_STANDARD_COLUMNS:
        xls_col = column_map.get(col["field"])
        if not xls_col:
            continue
        raw_val = raw_row.get(xls_col)
        role = col["role"]

        if role == "core":
            val = _coerce(col["dtype"], raw_val, col.get("maxlen"))
            if val is not None:
                row[col["field"]] = val
                has_core = True
        elif role == "tax":
            n = _to_decimal(raw_val)
            if n is not None and n != 0:
                taxes.append({"code": col["header"], "amount": float(n)})
        elif role == "leg":
            v = _clean(raw_val)
            if v is not None:
                legs.setdefault(col["leg_no"], {})[col["slot"]] = v

    # fold segments (drop legs that carry no route/flight)
    segments: list[dict] = []
    for n in sorted(legs):
        leg = legs[n]
        if leg.get("route") or leg.get("flight_no"):
            segments.append({"leg": n, "route": leg.get("route"),
                             "flight_no": leg.get("flight_no"), "dep_date": leg.get("dep_date")})

    if not has_core and not taxes and not segments:
        return None   # blank row

    # derived columns
    row["taxes"] = taxes or None
    row["segments"] = segments or None
    row["ssr"] = None
    row["extra"] = None
    row["taxes_total"] = sum((Decimal(str(t["amount"])) for t in taxes), Decimal("0")) if taxes else None
    dep = next((s["dep_date"] for s in segments if s.get("dep_date")), None)
    row["departure_date"] = _to_date(dep)
    row["raw_data"] = {str(k): _clean(v) for k, v in raw_row.items() if _clean(v) is not None} or None
    return row
