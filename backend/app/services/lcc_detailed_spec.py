"""LCC Detailed Statement — standard 141-column spec + typed-row builder.

Single source of truth for the LCC Detailed "standard template": the exact ordered
columns a user downloads, fills and uploads, and the rules that route each column's
value into the redesigned ``lcc_detailed`` table:

  * 39 CORE columns  -> typed columns on the row (dates, money, codes, flags)
  * 87 TAX/FEE codes -> folded into ``taxes``    JSONB [{code, amount}] (non-zero only)
  * 15 LEG columns   -> folded into ``segments`` JSONB [{leg, route, flight_no, dep_date}]

The last 12 core columns were appended for account-style exports (Air India Express
and kin), which carry a GST party, a transaction type, a parent PNR and a lump-sum tax
where an IndiGo export carries none of those. They are APPENDED, never inserted: this
list's order is the template's column order and the drill-in grid's, and inserting
would reshuffle both for every existing user.

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
    # ── Appended for account-style exports (Air India Express and kin) ───────
    # APPENDED, never inserted: the order of this list is the order of the template's
    # columns and of the drill-in grid, and inserting would silently reshuffle both
    # for every existing user.
    #
    # `taxes_total` is normally DERIVED from the per-code tax columns, but an account
    # export ships one lump-sum `Tax` column and no codes at all. Making it mappable
    # is what lets that land; build_typed_row below prefers a mapped value over the
    # derived sum.
    ("Tax Total",               "taxes_total",              "numeric",  "taxes_total",              None),
    ("AccountTransactionType",  "transaction_type",         "str",      "transaction_type",         60),
    ("ParentPNR",               "parent_pnr",               "str",      "parent_pnr",               20),
    ("AccountTransactionID",    "account_transaction_id",   "str",      "account_transaction_id",   40),
    ("Note",                    "note",                     "str",      "note",                     500),
    ("GSTCompanyName",          "gst_company_name",         "str",      "gst_company_name",         255),
    ("GSTNumber",               "gst_number",               "str",      "gst_number",               20),
    ("GSTEmailAddress",         "gst_email",                "str",      "gst_email",                255),
    ("FeeCode",                 "fee_code",                 "str",      "fee_code",                 120),
    ("SSRCode",                 "ssr_code",                 "str",      "ssr_code",                 120),
    ("ForeignCurrencyCode",     "foreign_currency_code",    "str",      "foreign_currency",         8),
    ("PaxType",                 "pax_type",                 "str",      "pax_type",                 8),
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


# ── drill-in filters ─────────────────────────────────────────────────────────
# Declared here rather than in the endpoint signature, mirroring `_TGQ_FILTERS` in
# services/statement_spec.py: adding a filter is a spec edit, and this list doubles as
# the ALLOWLIST the endpoint resolves `f.<field>` params through — user input is only
# ever a dict key into this list, never an attribute name.
#
# `field` is both the `f.<field>` query-param suffix and the LccDetailed column it maps
# to, so what the user filters lines up with the column they see. The split is by
# cardinality: identifiers a person types (a PNR, a passenger) are `text` and match with
# ILIKE; short code vocabularies are `select` and get a facet dropdown of the values
# actually present in the batch; the three date columns are `daterange`, because a
# dropdown of a few thousand distinct timestamps is unusable.
#
# `primary` filters sit in the always-visible row; the rest live behind "More filters",
# so the toolbar plus the totals strip don't push the data itself below the fold.
SEGMENTS_FILTER_FIELD = "__segments__"   # pseudo-field: legs live in the `segments` JSONB

FILTERS: list[dict] = [
    # The most-used lookups: "the passenger who called about PNR X", and the two axes a
    # reconciler splits a statement along.
    {"field": "name1",                    "label": "Passenger",       "type": "text",      "primary": True},
    {"field": "record_locator",           "label": "Record Locator",  "type": "text",      "primary": True},
    {"field": "payment_method_code",      "label": "Payment Method",  "type": "select",    "primary": True},
    {"field": "payment_status",           "label": "Payment Status",  "type": "select",    "primary": True},
    {"field": "transaction_date",         "label": "Txn Date",        "type": "daterange", "primary": True},

    # `name` is the account/agency the booking sits under, NOT the passenger (that is
    # `name1`). It repeats heavily within one file — often a single value — so it is
    # demoted below Passenger, but it is the visible NAME column and must be filterable.
    {"field": "name",                     "label": "Name",            "type": "text"},
    {"field": "gds_record_locator",       "label": "GDS Locator",     "type": "text"},
    {"field": "payment_number",           "label": "Payment No.",     "type": "text"},
    # Text, not a facet: one code per agent login, so a mid-size consolidator blows past
    # _MAX_FACET_VALUES and the dropdown would silently offer an incomplete list.
    {"field": "source_agent_code",        "label": "Agent Code",      "type": "text"},
    # The only reliable traveller key when the name is mangled (MR/, MSTR, transliteration).
    {"field": "email_address",            "label": "Email",           "type": "text"},
    {"field": SEGMENTS_FILTER_FIELD,      "label": "Sector / Flight", "type": "text"},
    {"field": "source_organization_code", "label": "Source Org",      "type": "select"},
    {"field": "product_class",            "label": "Class",           "type": "select"},
    # Cheap, and it matters the moment a file mixes currencies — the totals strip sums
    # across them otherwise.
    {"field": "currency_code",            "label": "Currency",        "type": "select"},
    # Boolean column, so a distinct-value facet would offer "true"/"false". The options
    # are declared statically instead and mapped back to a bool when the condition is
    # built — and they match what _disp() renders, so the filter reads like the column.
    {"field": "international",            "label": "Intl",            "type": "select",
     "options": ["Yes", "No"]},
    # ── Account-statement filters ────────────────────────────────────────────
    # `row_kind` first: on a merged upload it is the split a reconciler reaches for
    # before any other — the billable booking lines versus the money movements.
    {"field": "row_kind",                 "label": "Row Type",        "type": "select"},
    {"field": "movement_kind",            "label": "Movement",        "type": "select"},
    {"field": "transaction_type",         "label": "Txn Type",        "type": "select"},
    # The exact key to a corporate, and the reason a GSTIN beats a passenger name for
    # billing. Text, not a facet: a consolidator's file carries hundreds.
    {"field": "gst_number",               "label": "GST No.",         "type": "text"},
    {"field": "gst_company_name",         "label": "GST Company",     "type": "text"},
    # The reissue link — "what did this rebooking come from".
    {"field": "parent_pnr",               "label": "Parent PNR",      "type": "text"},
    # TEXT, not a facet, even though it looks like a code vocabulary: the real values
    # are comma-joined LISTS ("SEAT,VFPF"), so a distinct-value dropdown would offer
    # combinations as though they were codes.
    {"field": "fee_code",                 "label": "Fee Code",        "type": "text"},
    {"field": "pax_type",                 "label": "Pax Type",        "type": "select"},
    {"field": "booking_date",             "label": "Booking Date",    "type": "daterange"},
    # Ranked last: departure_date is DERIVED from the first leg carrying a dep date
    # (see build_typed_row), so rows whose legs had none are NULL and any range on it
    # silently excludes them.
    {"field": "departure_date",           "label": "Departure",       "type": "daterange"},
]

# Totalled over the WHOLE filtered set (not the visible page) and shown above the grid.
# Ordered as the identity a reconciler eyeballs — Total ≈ Base Fare + Taxes + Other Fees
# + SSR — so a statement that doesn't add up is visible without exporting anything.
# Every one of these is a real NUMERIC column, so the total is a plain SUM.
SUMMARY_FIELDS: list[dict] = [
    {"field": "total",           "label": "Total"},
    {"field": "base_fare",       "label": "Base Fare"},
    {"field": "taxes_total",     "label": "Taxes"},
    {"field": "other_fee_total", "label": "Other Fees"},
    {"field": "other_ssr_total", "label": "SSR"},
    {"field": "payment_amount",  "label": "Payment Amt"},
]


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
# Spec-LOCAL header fallbacks, keyed by standard field. Deliberately not merged into
# ``lcc_statement.LCC_ALIASES``: that module flattens its map into ``_ALIAS_TO_CANON``
# last-writer-wins, so adding "pnr" there would re-point it away from the canonical
# ``pnr`` field and "organizationname" would steal it from ``organization_name``.
# These are decisions about THIS spec's 141 columns, not about the canonical
# vocabulary, so they live here and are consulted first.
_SPEC_ALIASES: dict[str, list[str]] = {
    # An account statement calls the booking reference PNR, a sales report calls it
    # RecordLocator. They are the same value and the same column here — this is the
    # join key the two-file merge runs on.
    "record_locator":           ["pnr"],
    "source_organization_code": ["sourceorganization"],
    # The account the booking sits under, which is the NAME column — not the
    # passenger, who is Name1.
    "name":                     ["organizationname"],
    # ForeignAmount is the TRANSACTION AMOUNT and lands in `total`, not in
    # `payment_amount`: it is the money the row is billed on, and `_bill_kind` reads
    # `total` alone. Deliberately not also aliased to payment_amount — two fields
    # pointing at one column would show the same money twice in the totals strip.
    # (ACAmount, by contrast, is a constant account identifier and is never money.)
    "total":                    ["totalfare", "foreignamount"],
    "other_fee_total":          ["transactionfee"],
    "other_ssr_total":          ["otherservices"],
    "source_agent_code":        ["createdagentcode"],
    # A lump-sum tax column, as opposed to the 87 per-code columns.
    "taxes_total":              ["tax", "taxtotal", "totaltax"],
    "pax_type":                 ["paxtype", "passengertype", "ptc"],
    "ssr_code":                 ["ssrcode"],
}

# A file can share a couple of headers with the template by coincidence ("Name",
# "Total"), so a match on a handful proves nothing. Below this, "every column you have
# is a standard column" is not evidence that the file IS the template.
_MIN_TEMPLATE_COLUMNS = 10


def suggest_mapping(xls_columns: list[str]) -> tuple[dict[str, str], int, bool]:
    """Best-guess {standard_field: xls_column}.

    1. Direct: xls column whose norm() equals norm(standard header) — the fill-the-
       template case resolves 100%.
    2. Fallback (core only): ``_SPEC_ALIASES`` then ``LCC_ALIASES`` variants, so a raw
       airline export still auto-fills the core fields.

    Returns (mapping, matched_columns, is_template_match).

    ``is_template_match`` asks "is every column in YOUR file a standard column?", not
    "do you have all of OURS". The distinction matters the moment the template grows:
    keyed the other way, a user who filled in the 129-column template would be told
    their perfectly-mapped file only matched 129 of 141 the day column 130 was added.
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
            fallbacks = _SPEC_ALIASES.get(field, []) + LCC_ALIASES.get(col.get("alias_key") or "", [])
            for alias in fallbacks:
                if alias in norm_xls:
                    mapping[field] = norm_xls[alias]
                    break

    is_template_match = direct == len(norm_xls) and direct >= _MIN_TEMPLATE_COLUMNS
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
# The "%d %b %y" pair is Air India Express's booking date ("01 Sep 26", and
# "01 Sep 26 13:41:15" once the merge joins BookingDate to BookingTime). dateutil
# parses both correctly, but listing them avoids a dateutil call per row per column.
_DT_FORMATS = (
    "%d-%b-%Y %I:%M:%S %p", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y",
    "%d %b %y %H:%M:%S", "%d %b %y", "%d %b %Y %H:%M:%S", "%d %b %Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y",
)


def _to_datetime(v):
    """Parse a datetime, ALWAYS returning a naive one.

    Every DateTime column in this schema is naive (`TIMESTAMP WITHOUT TIME ZONE`), and
    asyncpg refuses an aware value for one — its encoder subtracts a naive epoch and
    raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. An LCC
    account export stamps its transaction date with an offset
    (`2026-08-15T01:49:20.513+0000`), which dateutil quite correctly parses as aware.

    Left unconverted, that does not surface as an error: `lcc_tasks._flush` catches the
    bulk-insert failure and retries row by row under SAVEPOINTs, and since every row of
    such a file carries the same format, EVERY row is skipped and the batch reports
    "completed" with zero rows. Hence the normalisation here, at the single point every
    datetime in this spec passes through, rather than at the call sites.
    """
    from datetime import datetime as _dt, timezone as _tz
    s = _clean(v)
    if not s:
        return None
    parsed = None
    for fmt in _DT_FORMATS:
        try:
            parsed = _dt.strptime(s, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            from dateutil import parser as dateparser
            parsed = dateparser.parse(s, dayfirst=True)
        except Exception:  # noqa: BLE001
            return None
    if parsed is not None and parsed.tzinfo is not None:
        parsed = parsed.astimezone(_tz.utc).replace(tzinfo=None)
    return parsed


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
    # Set here only so every built row carries the SAME key set — the chunked
    # executemany in workers/lcc_tasks.py requires that. The merge is what actually
    # knows these values, and the worker overwrites them per row.
    row["row_kind"] = None
    row["movement_kind"] = None
    # A MAPPED lump-sum tax wins over the derived sum. An account-style export ships
    # one `Tax` column and no per-code columns, so deriving unconditionally (as this
    # did) would overwrite the only tax figure the file has with None.
    if row.get("taxes_total") is None:
        row["taxes_total"] = sum((Decimal(str(t["amount"])) for t in taxes), Decimal("0")) if taxes else None
    dep = next((s["dep_date"] for s in segments if s.get("dep_date")), None)
    row["departure_date"] = _to_date(dep)
    row["raw_data"] = {str(k): _clean(v) for k, v in raw_row.items() if _clean(v) is not None} or None
    return row
