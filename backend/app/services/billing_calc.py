"""Shared pure helpers for billing math (customer + agency billing).

These were originally private to `api/v1/customers.py`; they are extracted here
so the agency-billing router can reuse the exact same markup/GST/date logic and
keep a single source of truth.
"""
from datetime import date
from typing import Optional

from dateutil import parser as _du

GST_RATE = 0.18


def to_float(value) -> float:
    """Coerce a possibly-None Decimal/str to float (0.0 on failure)."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_markup(base: float, markup_type: Optional[str], markup_value) -> float:
    """Markup amount for a base fare: percentage of base, a fixed amount, or none."""
    mtype = (markup_type or "").lower()
    mval = to_float(markup_value)
    if mtype == "percentage":
        return base * mval / 100.0
    if mtype == "fixed":
        return mval
    return 0.0


def compute_gst(base: float, markup: float, billing_type: Optional[str], discount: float = 0.0) -> float:
    """GST (18%) base depends on billing type. The discount reduces the taxable
    amount BEFORE GST is applied (clamped at 0 so a large discount can't create
    negative tax):
      - reseller: GST on (gross + markup − discount)
      - agency:   GST on (markup − discount)
      - unset/other: no GST applied
    """
    bt = (billing_type or "").lower()
    if bt == "reseller":
        return max(0.0, base + markup - discount) * GST_RATE
    if bt == "agency":
        return max(0.0, markup - discount) * GST_RATE
    return 0.0


def safe_date(*raws) -> Optional[date]:
    """Parse a ticket date string to a date. Handles ISO YYYY-MM-DD and dayfirst formats.
    Mirrors the parser used in services/deal_matching.py.
    """
    for raw in raws:
        if not raw:
            continue
        try:
            s = str(raw).strip()
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return date.fromisoformat(s[:10])
            return _du.parse(s, dayfirst=True).date()
        except Exception:
            continue
    return None


def passenger_name(t) -> str:
    """Best passenger name from an UploadedTicket (pax_name, else first+last)."""
    if getattr(t, "pax_name", None):
        return t.pax_name
    name = f"{getattr(t, 'first_name', '') or ''} {getattr(t, 'last_name', '') or ''}".strip()
    return name or "—"
