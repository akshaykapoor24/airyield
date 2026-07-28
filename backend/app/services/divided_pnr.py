"""LCC Divided PNR Statement — normalizer.

One known format (a parent→child PNR split ledger):
  ``BookingDate · ParentPNR · DividedDate · ChildPNR · PaymentAmount · CurrencyCode ·
    PaymentMethodCode · SourceOrganizationCode · BookingPromoCode · SourceAgentCode``

Normalizes into canonical fields (`data`) + `raw_data` (verbatim). Flat ledger — no
taxes / segments / SSR. Same parser-hook shape as ``di_statement`` (`build_col_map` +
`build_row`) so the generic router/UI handle it uniformly; the alias map keeps it
tolerant of future header variants.
"""
from __future__ import annotations

import math
import re


def norm(header) -> str:
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


CANONICAL_COLUMNS: list[tuple[str, str]] = [
    ("booking_date",              "Booking Date"),
    ("parent_pnr",                "Parent PNR"),
    ("divided_date",             "Divided Date"),
    ("child_pnr",                 "Child PNR"),
    ("payment_amount",            "Payment Amount"),
    ("currency",                  "Currency"),
    ("payment_method",            "Payment Method"),
    ("source_organization_code",  "Source Org Code"),
    ("booking_promo_code",        "Promo Code"),
    ("source_agent_code",         "Source Agent Code"),
]
DISPLAY_COLUMNS: list[dict] = [{"header": h, "field": f} for f, h in CANONICAL_COLUMNS]

DIVIDED_PNR_ALIASES: dict[str, list[str]] = {
    "booking_date":             ["bookingdate", "booking_date"],
    "parent_pnr":               ["parentpnr", "parent_pnr"],
    "divided_date":            ["divideddate", "divided_date"],
    "child_pnr":                ["childpnr", "child_pnr", "dividedpnr"],
    "payment_amount":           ["paymentamount", "amount"],
    "currency":                 ["currencycode", "currency"],
    "payment_method":           ["paymentmethodcode", "payment_method"],
    "source_organization_code": ["sourceorganizationcode"],
    "booking_promo_code":       ["bookingpromocode", "promocode"],
    "source_agent_code":        ["sourceagentcode"],
}

_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in DIVIDED_PNR_ALIASES.items():
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
    return "divided-pnr"


def build_row(row, columns: list[str]) -> dict:
    """Normalize one raw Divided-PNR row (pandas Series or dict) into the canonical shape."""
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
