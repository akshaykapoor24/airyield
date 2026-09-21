"""What an agency charges US, and what WE charge an agency, on top of the fare.

TWO DIRECTIONS, ONE SHAPE — and the direction is the entire reason this exists as
its own module rather than a single pair of columns on `agencies`.

ONE AGENCY ROW IS READ FROM BOTH SIDES OF THE BUSINESS:

    Vendors data   `deals.supplier_agency_id`          we BUY FROM them
                   -> their SERVICE CHARGE is a COST to us

    Customer data  `deals.agency_id`, `billings.agency_id`
                   -> our SERVICE FEE on them is INCOME

The codebase already states this opposition — see the migration
`deal_supplier_agency_01`: "It also means the opposite thing — 'we sell TO them'
rather than 'we buy FROM them'." A single stored rate would therefore be read as a
cost on one screen and as income on another, with nothing on either saying which
was meant, so `agencies` carries the two independently and this module resolves
whichever one a caller is entitled to.

NOTHING BILLS FROM THIS YET, deliberately. The rates are collected in User master →
Agency Master and stored; no invoice, deal or statement changes its numbers because
of them. `api/v1/agency_billing.py` still hardcodes its markup at 0.0. That wiring is
a separate pass, and this module is the seam it will use when it happens, which is
why the arithmetic is here and tested now rather than inlined into a router later.

WHY NOT IN `billing_calc.py`, where the billing routers already import from: that
module is shared with the AGENCY billing router, and `party_markup.py` records the
reason for keeping party-rate vocabulary out of it — putting it there "would be an
invitation to wire it in". The same applies here, doubly so while nothing bills yet.
"""
from __future__ import annotations

from typing import Optional

# How a rate is QUOTED — 'percentage' | 'fixed'. The same two values
# `billing_calc.compute_markup` branches on, imported rather than restated:
# markup_categories.py is already "the one definition those two import, rather than
# a third copy", and a service fee is quoted exactly the way a markup is.
from app.services.markup_categories import MARKUP_TYPES as SERVICE_FEE_TYPES

__all__ = [
    "SERVICE_FEE_TYPES", "GST_TREATMENTS", "GST_INCLUSIVE", "GST_EXCLUSIVE",
    "DEFAULT_GST_TREATMENT", "norm_service_fee", "service_fee_from_cells",
    "vendor_service_charge", "customer_service_fee", "service_amount",
    "taxable_and_gst", "describe",
]

# ── whether the rate already contains its tax ─────────────────────────────────
#
# NOT COSMETIC. For an amount A at rate r:
#
#   exclusive  taxable = A             gst = A x r         gross = A x (1 + r)
#   inclusive  taxable = A / (1 + r)   gst = A - taxable   gross = A
#
# A ₹1,000 fee entered inclusive of 18% is ₹847.46 of service and ₹152.54 of tax;
# entered exclusive it is ₹1,000 of service and ₹180 of tax on top. The two differ
# by ₹180 on every single line, so the flag has to be stored beside the value and
# can never be inferred from it.
#
# Lowercase slugs, plain strings, no DB Enum — the rule models/gst_configuration.py
# states for this schema: "adding a fourth basis is a code change, never a migration".
GST_EXCLUSIVE = "exclusive"   # the value is net; tax is added on top
GST_INCLUSIVE = "inclusive"   # the value already contains tax; back it out

GST_TREATMENTS: tuple[str, ...] = (GST_EXCLUSIVE, GST_INCLUSIVE)

# WHAT AN UNANSWERED ROW MEANS. Every agency created before this existed has NULL
# here, and so does any row whose rate was typed without the question being
# answered. Exclusive is the safe reading: it adds tax on top, whereas treating a
# blank as inclusive would quietly DIVIDE the taxable value of every such line by
# 1.18 — money silently removed from the tax base with nothing on screen to show it.
DEFAULT_GST_TREATMENT = GST_EXCLUSIVE


def _num(value) -> Optional[float]:
    """A rate value as a float, or None. `bool` is excluded because `True` is 1.0."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out          # NaN != NaN; float("nan") parses


def norm_service_fee(ftype, value, gst) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """Whatever a caller sent → what may be stored, as (type, value, gst_treatment).

    A HALF-SET RATE IS STORED AS NOTHING. A type with no value, or a value with no
    type, is dropped in full — the call `party_markup.norm_category_markups` already
    makes, and for its reason: a rate that survives half-filled is "a category
    silently priced at nothing, which is a revenue leak nothing on screen would
    report". Here it would be worse, because the half that survives would look
    deliberate on the Agency Master row.

    `value = 0` IS KEPT. A deliberate "we charge them nothing" is a real answer and
    reads differently from "nobody has been asked" — the same distinction
    `agencies.gst_registered` is stored for. Hence `is None`, never `not value`.

    The GST treatment is only meaningful once there IS a rate, so it is dropped with
    the rest and defaulted on the way back out. An unrecognised treatment beside a
    valid rate falls back to the default rather than voiding the rate — the rate is
    the commercial fact, the treatment is only how it is presented.
    """
    kind = str(ftype).strip().lower() if ftype is not None else None
    amount = _num(value)
    if kind not in SERVICE_FEE_TYPES or amount is None:
        return None, None, None

    treatment = str(gst).strip().lower() if gst is not None else None
    if treatment not in GST_TREATMENTS:
        treatment = DEFAULT_GST_TREATMENT
    return kind, amount, treatment


def service_fee_from_cells(cell, prefix: str) -> tuple[tuple, Optional[str]]:
    """One spreadsheet row's three columns → ((type, value, gst), problem).

    `cell(column)` returns a cell's trimmed text, or None when blank or absent.
    `prefix` is "VENDOR_SERVICE_CHARGE" or "CUSTOMER_SERVICE_FEE", so a sheet made
    before these columns existed gives ((None, None, None), None) and imports
    exactly as it always did.

    UNLIKE `norm_service_fee`, A HALF-FILLED PAIR HERE IS A PROBLEM, NOT A SILENT
    DROP — the same split `party_markup` draws between its form path and its import
    path. The form cannot produce one; a spreadsheet easily can, and someone who
    typed 250 under _VALUE and forgot _TYPE must hear about it rather than discover
    later that the agency was saved carrying no rate at all.
    """
    raw_type, raw_value, raw_gst = (
        cell(f"{prefix}_TYPE"), cell(f"{prefix}_VALUE"), cell(f"{prefix}_GST"),
    )
    if not raw_type and not raw_value:
        # A GST treatment alone says nothing without a rate to treat, and is not
        # worth failing an import over.
        return (None, None, None), None

    kind = str(raw_type).strip().lower() if raw_type else None
    if raw_type and kind not in SERVICE_FEE_TYPES:
        return (None, None, None), f"{prefix}_TYPE '{raw_type}' must be percentage or fixed."
    if not raw_value:
        return (None, None, None), f"{prefix}_VALUE is required when {prefix}_TYPE is filled in."
    amount = _num(raw_value)
    if amount is None:
        return (None, None, None), f"{prefix}_VALUE '{raw_value}' is not a number."
    if amount < 0:
        return (None, None, None), f"{prefix}_VALUE cannot be negative."
    if not kind:
        return (None, None, None), (
            f"{prefix}_TYPE (percentage or fixed) is required when {prefix}_VALUE is filled in."
        )

    treatment = str(raw_gst).strip().lower() if raw_gst else None
    if raw_gst and treatment not in GST_TREATMENTS:
        return (None, None, None), f"{prefix}_GST '{raw_gst}' must be inclusive or exclusive."
    return (kind, amount, treatment or DEFAULT_GST_TREATMENT), None


def vendor_service_charge(agency) -> tuple[Optional[str], Optional[float], str]:
    """What THIS AGENCY CHARGES US when we buy from them — a COST.

    Read on the Vendors data side, where the agency is reached through
    `deals.supplier_agency_id`. Never read this for a bill we raise TO an agency.
    """
    return _resolve(agency, "vendor_service_charge")


def customer_service_fee(agency) -> tuple[Optional[str], Optional[float], str]:
    """What WE CHARGE THIS AGENCY when we sell to them — INCOME.

    Read on the Customer data side, where the agency is reached through
    `deals.agency_id` / `billings.agency_id`. Never read this for what we owe them.
    """
    return _resolve(agency, "customer_service_fee")


def _resolve(agency, prefix: str) -> tuple[Optional[str], Optional[float], str]:
    """One direction's stored triple, guarded again on read.

    `norm_service_fee` prunes on write, but this runs on every line of every bill
    and the columns are plain nullable ones a psql session can put anything into —
    the same defence `party_markup.markup_for` keeps for the JSONB it reads.

    The treatment always comes back as a real value (never None) so callers never
    have to know the default; see DEFAULT_GST_TREATMENT for why it is exclusive.
    """
    kind = getattr(agency, f"{prefix}_type", None)
    kind = str(kind).strip().lower() if kind else None
    amount = _num(getattr(agency, f"{prefix}_value", None))
    if kind not in SERVICE_FEE_TYPES or amount is None:
        return None, None, DEFAULT_GST_TREATMENT

    treatment = getattr(agency, f"{prefix}_gst", None)
    treatment = str(treatment).strip().lower() if treatment else None
    return kind, amount, (treatment if treatment in GST_TREATMENTS else DEFAULT_GST_TREATMENT)


def service_amount(base: float, ftype: Optional[str], fvalue) -> float:
    """The quoted service charge/fee on a base amount — a percentage of it, or a flat sum.

    Delegates to `billing_calc.compute_markup` rather than restating the arithmetic,
    so a service fee inherits its sign rule for free: a refund is a negative base and
    a flat ₹500 fee on it must come back as −500, or the credit note charges the
    party a fee on a ticket they gave back.

    WHAT COMES BACK IS THE QUOTED AMOUNT, NOT THE TAXABLE ONE. Whether it already
    contains GST is `taxable_and_gst`'s question, and the two are kept apart because
    the quoted figure is what an invoice line shows and the taxable one is only what
    the tax is computed on.

    A FIXED FEE IS PER LINE HERE, NOT PER PASSENGER. `party_markup.line_markup`
    multiplies a fixed MARKUP by `pax_count`; whether a service fee works the same way
    is a billing decision that belongs with the wiring, not with this arithmetic, and
    nothing bills from this yet. Decide it there, in one place, as `line_markup` does.

    Imported inside the function the way `party_markup.line_markup` does it —
    billing_calc imports the models, and this module is reached from the schemas.
    """
    from app.services.billing_calc import compute_markup

    return compute_markup(base, ftype, fvalue)


def taxable_and_gst(amount: float, treatment: Optional[str], rate: Optional[float] = None) -> dict:
    """Split a quoted service amount into what tax is charged ON and the tax itself.

    THIS IS THE WHOLE POINT OF THE INCLUSIVE/EXCLUSIVE FLAG:

        exclusive   taxable = amount             gst = taxable x rate
        inclusive   taxable = amount / (1+rate)  gst = amount - taxable

    `gross` is what the party actually pays either way, so a caller adds `gross` to a
    line total and reports `taxable` / `gst` on the invoice — never re-deriving one
    from the other, the discipline `billing_calc.split_gst` already states about its
    own `gst_amount`.

    `rate` defaults to `billing_calc.GST_RATE`, the same 18% every other figure on the
    invoice uses, so a bill cannot be internally inconsistent. It is a parameter
    because `gst_configurations` can carry other rates, and the day billing reads them
    this takes the rate rather than growing a second source of truth.

    THE HEADS ARE NOT DECIDED HERE. CGST+SGST vs IGST is place of supply, and
    `billing_calc.split_gst` owns it. This returns the taxable value that feeds it.
    """
    from app.services.billing_calc import GST_RATE

    r = GST_RATE if rate is None else float(rate)
    amt = _num(amount) or 0.0
    kind = str(treatment).strip().lower() if treatment else DEFAULT_GST_TREATMENT
    if kind not in GST_TREATMENTS:
        kind = DEFAULT_GST_TREATMENT

    if kind == GST_INCLUSIVE:
        # A rate of −100% would divide by zero. No such rate is real, but the branch
        # has to be defined rather than raising from inside a billing loop.
        taxable = amt / (1.0 + r) if (1.0 + r) else amt
        gst = amt - taxable
        gross = amt
    else:
        taxable = amt
        gst = amt * r
        gross = amt + gst

    return {
        "amount": round(amt, 2),
        "taxable": round(taxable, 2),
        "gst": round(gst, 2),
        "gross": round(gross, 2),
        "gst_treatment": kind,
    }


def describe(ftype: Optional[str], fvalue, gst: Optional[str]) -> str:
    """"2% · GST extra" / "₹250 · incl. GST" — one cell's worth, for a list or a chip.

    Empty string when nothing is set, so a screen shows its own em-dash rather than
    this module inventing one.
    """
    kind, amount, treatment = norm_service_fee(ftype, fvalue, gst)
    if kind is None or amount is None:
        return ""
    shown = f"{amount:g}%" if kind == "percentage" else f"₹{amount:g}"
    return f"{shown} · " + ("incl. GST" if treatment == GST_INCLUSIVE else "GST extra")
