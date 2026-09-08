"""Evaluate a GstConfiguration row against real money.

Pure functions over plain numbers — nothing here touches the DB or a request, so
the arithmetic can be unit-tested and reused from any caller (ticket calculation,
customer billing, agency billing, an invoice PDF) once the business decides where
it belongs.

THE ONE RULE THIS FILE EXISTS TO ENFORCE
────────────────────────────────────────
CGST + SGST and IGST are mutually exclusive. A supply is either intra-state (the
place of supply is the supplier's own state → CGST + SGST, half the rate each) or
inter-state (→ IGST at the full rate). NEVER both. The config row carries all
three rates because the row does not know where the supply lands; `compute_gst`
takes `interstate` and zeroes the pair that does not apply. Reading cgst_pct,
sgst_pct and igst_pct off the model and summing them would tax every rupee twice.

Distinct from services/billing_calc.compute_gst, which is the ORIGINAL hardcoded
18%-on-markup rule still wired into customer / corporate / agency billing. That
one stays as it is until the business says which screens should move onto this
configurable master.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from app.models.gst_configuration import (
    BASIS_BASIC_FARE, BASIS_SERVICE_CHARGE, BASIS_TOTAL_COST, BASIS_MARKUP,
    CATEGORY_ABATEMENT, CATEGORY_NORMAL,
)

# Indian tax amounts are carried to 2 dp, half-up — the convention every other
# Numeric(14, 2) money column in this schema already round-trips.
_CENTS = Decimal("0.01")


def _dec(value) -> Decimal:
    """Coerce a possibly-None float / Decimal / str to Decimal (0 on failure).

    Goes through str() for floats on purpose: Decimal(0.7) is 0.6999…, while
    Decimal("0.7") is exact and compares equal to the Decimal("0.700") a
    Numeric column hands back. The same trick schemas/iata_commission.py uses.
    """
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


def _money(value: Decimal) -> float:
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def basis_amount(
    basis: str,
    *,
    basic_fare=0,
    taxes=0,
    service_charge=0,
    markup=0,
) -> Decimal:
    """The money a rate is charged on, for one basis.

    `markup` is the agency's own margin on the sale, and BASIS_MARKUP returns it
    PLUS any service charge — the business's rule is "the service charge added
    into the markup, otherwise the markup". A rule taxing `service_charge` alone
    computes nothing on most real sales, because that column is populated only by
    B2B consolidator statements and is NULL on every LCC and hand-punched row.

    `total_cost` is fare + taxes + service charge, exactly as the business stated
    it. Callers that hold a ticket row should pass the pieces (sell_fare, the sum
    of the tax columns, serv_charge) rather than total_amt: total_amt already has
    commission, discount and TDS folded in, which are not part of this base.
    """
    fare = _dec(basic_fare)
    tax = _dec(taxes)
    charge = _dec(service_charge)
    margin = _dec(markup)

    if basis == BASIS_BASIC_FARE:
        return fare
    if basis == BASIS_SERVICE_CHARGE:
        return charge
    if basis == BASIS_TOTAL_COST:
        return fare + tax + charge
    if basis == BASIS_MARKUP:
        return margin + charge
    raise ValueError(f"Unknown GST basis: {basis!r}")


def compute_gst(
    config,
    *,
    interstate: bool,
    basic_fare=0,
    taxes=0,
    service_charge=0,
    markup=0,
    discount=0,
) -> dict:
    """Apply one GstConfiguration row to one transaction.

    Returns every intermediate step, not just the total, because an invoice has
    to print the taxable value beside the tax and a reviewer has to be able to
    see WHY a figure came out as it did.

    `interstate` is the place-of-supply decision, made by the caller from the
    supplier's state vs the customer's: True → IGST only, False → CGST + SGST.
    """
    basis = config.basis
    base = basis_amount(
        basis, basic_fare=basic_fare, taxes=taxes,
        service_charge=service_charge, markup=markup,
    )

    # The discount reduces what is taxable BEFORE the rate applies, and the result
    # is clamped at zero — the same order billing_calc.compute_gst has always used.
    # Without the clamp a refund (a negative base; live data has one at -745.00)
    # would emit negative CGST and SGST, i.e. a credit of tax nobody paid.
    taxable_pct = _dec(config.taxable_value_pct)
    taxable_value = max(
        Decimal(0), (base - _dec(discount)) * taxable_pct / Decimal(100),
    )

    cgst_pct = _dec(config.cgst_pct)
    sgst_pct = _dec(config.sgst_pct)
    igst_pct = _dec(config.igst_pct)

    # The exclusivity. One branch or the other is always all-zero.
    if interstate:
        cgst = sgst = Decimal(0)
        igst = taxable_value * igst_pct / Decimal(100)
        applied = "igst"
        effective_pct = igst_pct
    else:
        cgst = taxable_value * cgst_pct / Decimal(100)
        sgst = taxable_value * sgst_pct / Decimal(100)
        igst = Decimal(0)
        applied = "cgst_sgst"
        effective_pct = cgst_pct + sgst_pct

    return {
        "config_id": getattr(config, "id", None),
        "code": getattr(config, "code", None),
        "basis": basis,
        "basis_amount": _money(base),
        "taxable_value_pct": float(taxable_pct),
        "taxable_value": _money(taxable_value),
        "interstate": bool(interstate),
        # Which pair actually applied — so a caller can never mistake a zero for
        # "no tax" when it really means "the other pair carried it".
        "applied": applied,
        "effective_gst_pct": float(effective_pct),
        "cgst": _money(cgst),
        "sgst": _money(sgst),
        "igst": _money(igst),
        "total_gst": _money(cgst + sgst + igst),
    }


def formula_text(config) -> str:
    """The row's rule as the sentence a human would write it.

    Rendered server-side so the API, an export and the screen all describe a row
    the same way. Mirrors the label map in frontend/src/app/(dashboard)/masters/
    gst-configuration/page.tsx — keep the two in step.
    """
    labels = {
        BASIS_BASIC_FARE: "Basic Fare",
        BASIS_SERVICE_CHARGE: "Service Charge",
        BASIS_TOTAL_COST: "Total Cost (Fare + Taxes + Service Charge)",
        BASIS_MARKUP: "Markup + Service Charge",
    }
    base = labels.get(config.basis, config.basis)
    slice_ = _dec(config.taxable_value_pct)
    # A 100% slice is the identity — printing "× 100%" would only add noise.
    prefix = f"{base} × {_pct(slice_)}" if slice_ != Decimal(100) else base
    return (
        f"CGST = {prefix} × {_pct(_dec(config.cgst_pct))} · "
        f"SGST = {prefix} × {_pct(_dec(config.sgst_pct))} · "
        f"IGST = {prefix} × {_pct(_dec(config.igst_pct))}"
    )


def _pct(value: Decimal) -> str:
    """Format a percentage without trailing zeros: 9, 12.5, 0.75."""
    s = format(value.normalize(), "f")
    return f"{s}%"


def resolve_config(
    configs: Iterable,
    *,
    category: str,
    sub_category: Optional[str] = None,
    on_date: Optional[date] = None,
):
    """Pick the one rule that applies, from rows already loaded.

    Takes an iterable rather than a session so the caller controls the query and
    this stays testable. Filters to active rows of the right category whose
    validity window contains `on_date` (an open end means still in force), and
    returns the LATEST-starting match — so a rate change dated next month does
    not take effect until it does.

    Returns None when nothing matches; callers must treat that as "not
    configured" and say so, never as zero tax.
    """
    when = on_date or date.today()
    best = None
    for cfg in configs:
        if not cfg.is_active:
            continue
        if cfg.category != category:
            continue
        # Both categories are subdivided — abatement by domestic/international,
        # normal by agency/reseller — so the sub-category always has to match.
        # Passing None therefore matches nothing, which is the point: "abatement"
        # alone is not a rule, and silently picking domestic would under-tax
        # every international ticket by half.
        if cfg.sub_category != sub_category:
            continue
        if cfg.valid_from and cfg.valid_from > when:
            continue
        if cfg.valid_to and cfg.valid_to < when:
            continue
        if best is None:
            best = cfg
            continue
        # An open valid_from sorts earliest, so a dated row always wins over it.
        if (cfg.valid_from or date.min) >= (best.valid_from or date.min):
            best = cfg
    return best


__all__ = [
    "basis_amount",
    "compute_gst",
    "formula_text",
    "resolve_config",
    "CATEGORY_ABATEMENT",
    "CATEGORY_NORMAL",
]
