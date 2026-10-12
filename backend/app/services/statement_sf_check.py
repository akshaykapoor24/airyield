"""Check a third-party statement's service fee against what the agency agreed to charge.

When an agency is onboarded (User master → Agency Master) the user records its VENDOR
service charge — what this consolidator adds when we buy from them: a flat ₹ or a % of
fare, GST inclusive or exclusive (models/agency.py, services/service_fee.py). The
consolidator's statement prints what it actually charged, per ticket, in its "SF" (or
"Service Charge") and "GST On SF" columns. This compares the two and says which rows
disagree, so an overcharge is visible on the statement itself instead of only in the bill.

WHAT IS COMPARED, AND ON WHICH ROWS
  * Only issued tickets (CONFIRMED / TICKETED / blank status). A cancelled or refunded
    row is the REVERSAL of an issue: its SF is a cancellation charge with its own rate
    (the sample's cancellations carry ₹500 against ₹100 on issue), which the agency's
    issue-time service charge says nothing about. Those rows are tagged `refund`, not
    checked.
  * SF: a fixed charge is per ticket line; a percentage is of the Basic Fare.
  * GST On SF: 18% of the taxable part (services/service_fee.taxable_and_gst). With an
    INCLUSIVE agreement the quoted figure already contains the tax, so the statement's SF
    column — the taxable part — is expected to be quote / 1.18.
  * A tolerance of ₹1 absorbs the vendor's rounding.

An agency with no vendor service charge on record is not checked at all — "nobody has
been asked" (NULL) is not "we agreed zero", see models/agency.py.

Pure: no database, so every rule here is unit-tested directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TOLERANCE = 1.0

ISSUE = "issue"
REFUND = "refund"
OTHER = "other"

_REFUND_STATUS = {"CANCELLED", "CANCELED", "CANCEL", "REFUNDED", "REFUND", "RFND",
                  "REFUND PROCESSED", "REFUNDED-FULL", "REFUNDED-PARTIAL"}
_ISSUE_STATUS = {"", "CONFIRMED", "TICKETED", "ISSUED", "OK", "ACTIVE", "COMPLETED"}


def row_kind(data: dict) -> str:
    status = str(data.get("ticket_status") or "").strip().upper()
    if status in _REFUND_STATUS:
        return REFUND
    if status in _ISSUE_STATUS:
        return ISSUE
    return OTHER


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        n = float(re.sub(r"[^\d.\-]", "", s))
    except ValueError:
        return None
    return -n if neg else n


@dataclass(frozen=True)
class Agreement:
    """The agency's vendor service charge, resolved."""
    ftype: str            # "fixed" | "percentage"
    value: float
    gst: str              # "exclusive" | "inclusive"
    label: str            # "₹200 · GST extra"


def agreement_for(agency) -> Agreement | None:
    """The agency's vendor service charge, or None when none is on record."""
    from app.services.service_fee import describe, vendor_service_charge

    if agency is None:
        return None
    ftype, value, gst = vendor_service_charge(agency)
    if not ftype or value is None:
        return None
    return Agreement(ftype=ftype, value=float(value), gst=gst, label=describe(ftype, value, gst))


def expected(data: dict, ag: Agreement) -> tuple[float, float]:
    """(expected SF column, expected GST On SF column) for one issued row."""
    from app.services.service_fee import service_amount, taxable_and_gst

    base = _num(data.get("base_fare")) or 0.0
    quoted = service_amount(base, ag.ftype, ag.value) if ag.ftype == "percentage" else ag.value
    split = taxable_and_gst(quoted, ag.gst)
    return round(split["taxable"], 2), round(split["gst"], 2)


def _money(n: float) -> str:
    return f"₹{n:,.2f}".rstrip("0").rstrip(".")


def check_row(data: dict, ag: Agreement | None) -> dict:
    """The derived keys one statement row gains: its kind, and per-field verdicts.

    `__checks__` maps a FIELD the view renders (service_fee, service_charge, gst_on_sf)
    to {"status": "ok" | "mismatch", "expected": str, "note": str}. Absent when there
    is nothing to check — no agreement, not an issued ticket, or no SF printed.
    """
    kind = row_kind(data)
    out: dict = {"__kind__": kind}
    if ag is None or kind != ISSUE:
        return out

    # Vendors print the per-ticket fee as "SF"; some put it under "Service Charge"
    # instead. Whichever column the row actually filled is the one judged.
    sf_field = "service_fee" if _num(data.get("service_fee")) is not None else (
        "service_charge" if _num(data.get("service_charge")) is not None else None)
    if sf_field is None:
        return out

    exp_sf, exp_gst = expected(data, ag)
    checks: dict = {}
    got_sf = _num(data.get(sf_field)) or 0.0
    checks[sf_field] = {
        "status": "ok" if abs(got_sf - exp_sf) <= TOLERANCE else "mismatch",
        "expected": _money(exp_sf),
        "note": f"Agency charges {ag.label} — expected {_money(exp_sf)}, statement says {_money(got_sf)}.",
    }
    got_gst = _num(data.get("gst_on_sf"))
    if got_gst is not None:
        checks["gst_on_sf"] = {
            "status": "ok" if abs(got_gst - exp_gst) <= TOLERANCE else "mismatch",
            "expected": _money(exp_gst),
            "note": f"GST on {_money(exp_sf)} at 18% is {_money(exp_gst)}, statement says {_money(got_gst)}.",
        }
    out["__checks__"] = checks
    return out


def summarize(rows: list[dict]) -> dict:
    """Counts over annotated rows, for the batch header."""
    checked = [r for r in rows if r.get("__checks__")]
    mism = [r for r in checked
            if any(c.get("status") == "mismatch" for c in r["__checks__"].values())]
    return {
        "issued": sum(1 for r in rows if r.get("__kind__") == ISSUE),
        "refunds": sum(1 for r in rows if r.get("__kind__") == REFUND),
        "checked": len(checked),
        "mismatched": len(mism),
    }
