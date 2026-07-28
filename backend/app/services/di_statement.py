"""LCC DI (Deposit) Statement — unified normalizer for the deposit-ledger formats.

Two known formats, same business entity (a deposit / account transaction):
  A. `DEPOSIT_DATE · TYPE · DETAIL · AMOUNT · CURRENCY`         (deposit ledger)
  B. `Agency Code · AgentName · Date · Details · Amount`        (agency ledger)

Normalizes either into canonical fields (`data`) + `raw_data` (verbatim). No taxes /
segments / SSR — DI is a flat ledger. Same parser-hook shape as ``lcc_statement`` so the
generic router/UI handle it uniformly (`build_row` returns empty taxes/segments/ssr).
"""
from __future__ import annotations

import math
import re


def norm(header) -> str:
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


CANONICAL_COLUMNS: list[tuple[str, str]] = [
    ("deposit_date", "Date"),
    ("type",         "Type"),
    ("agency_code",  "Agency Code"),
    ("agent_name",   "Agent"),
    ("detail",       "Detail"),
    ("amount",       "Amount"),
    ("currency",     "Currency"),
]
DISPLAY_COLUMNS: list[dict] = [{"header": h, "field": f} for f, h in CANONICAL_COLUMNS]

DI_ALIASES: dict[str, list[str]] = {
    "deposit_date": ["deposit_date", "date"],
    "type":         ["type"],
    "agency_code":  ["agency_code", "agencycode"],
    "agent_name":   ["agentname", "agent_name"],
    "detail":       ["detail", "details"],
    "amount":       ["amount"],
    "currency":     ["currency"],
}

_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in DI_ALIASES.items():
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
    nz = {norm(c) for c in columns}
    if "agency_code" in nz or "agentname" in nz:
        return "agency-ledger"
    if "deposit_date" in nz:
        return "deposit-ledger"
    return "di"


def build_row(row, columns: list[str]) -> dict:
    """Normalize one raw DI row (pandas Series or dict) into the canonical shape."""
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
