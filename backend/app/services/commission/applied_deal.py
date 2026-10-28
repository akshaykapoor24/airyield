"""The deal one statement line was priced with — for the popup behind the Matched deal chip.

Three questions, in the order a reviewer asks them:

    which deal     its number, supplier, airline, validity and IATA %
    why it applied every criterion the matcher tested — airline, contract validity, supplier,
                   flight type, class, travel window — and the inclusion / exclusion rules,
                   each with the ticket's value against the deal's
    what it pays   each incentive's base (Basic, + YQ, + YR as the deal's calc columns say)
                   × its rate; IATA % × the BASIC FARE only (commission/runner.py); their
                   sum, against the vendor's statement, and the gap

The criteria and the arithmetic come from DealMatchingService.diagnose_match — the engine's
own trace, run on the calculation's input snapshot — narrowed to the one deal that applied.
The ⓘ popup keeps the long view (every deal considered). If the deal has changed since the
line was calculated, the trace no longer adds up to the stored figure, and that is said.
"""
from __future__ import annotations

from app.services.commission.runner import _pct

# A criterion the statement could not supply is reported as skipped, not as proven.
_NOT_PRINTED = "not printed"


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _step(s, group: str) -> dict:
    skipped = (s.ticket_value or "") == _NOT_PRINTED
    return {"group": group, "step": s.step, "passed": bool(s.passed), "skipped": skipped,
            "ticket_value": s.ticket_value, "deal_value": s.deal_value, "detail": s.detail}


def _rule(diag, kind: str) -> dict | None:
    """An inclusion / exclusion trace. `is_excluded` True means the rule blocks the payout,
    for both kinds (services/exclusion_evaluator); `undecided` that it could not be judged.
    A step's `matched` stays None when the ticket did not carry what it needed — "not
    known" is not "no match", and the popup says which."""
    if diag is None or not diag.steps:
        return None
    return {
        "kind": kind, "name": getattr(diag, "rule_name", None) or kind,
        "passed": not diag.is_excluded,
        "undecided": bool(getattr(diag, "undecided", False)), "reason": diag.reason,
        "steps": [{"field": s.field, "label": getattr(s, "label", None) or s.field,
                   "rule_value": s.rule_value, "ticket_value": s.ticket_value,
                   "matched": s.matched} for s in diag.steps],
    }


def _incentive(p, stored: dict) -> dict:
    bd = p.incentive_breakdown or {}
    return {
        "incentive_type": p.plb_key,
        "applied": bool(p.plb_overall_match),
        "calc_on": bd.get("targetCalcCols") or "Basic",
        "basic": bd.get("sell_fare"),
        "yq": bd.get("sell_tax_yq_value") if bd.get("sell_tax_yq_added") else None,
        "yr": bd.get("sale_yr_value") if bd.get("sale_yr_added") else None,
        "base": bd.get("base_total"),
        "rate": bd.get("incentiveAmtPct"),
        "rate_kind": bd.get("incentive_num_pct") or "Percentage",
        "formula": bd.get("formula"),
        "amount": bd.get("result"),
        "stored": _f(stored.get(p.plb_key)) if p.plb_key in stored else None,
        "slab": ({"period": bd.get("slab_period"), "range": bd.get("slab_period_range"),
                  "achieved": bd.get("slab_achieved"), "target": bd.get("slab_target"),
                  "cell": bd.get("slab_cell")} if bd.get("is_slab") else None),
    }


def build(calc, deal, diag, statement: float | None, read_as: dict | None = None) -> dict:
    """The popup's payload. `diag` is this deal's DealDiagnostic, or None when the engine
    could not trace it (no airline / issue date, or the deal is no longer approved);
    `statement` is the vendor's commission on the line (statement_lines), None if unknown;
    `read_as` how the engine read the class and sector (api/v1/commission._read_as)."""
    read_as = read_as or {}
    reversed_ = calc.status == "reversed"
    incentive = _f(calc.incentive) or 0.0
    iata_amount = _f(calc.iata_commission) or 0.0
    expected = round(incentive + iata_amount, 2)

    pct = _pct(getattr(deal, "iata_commission", None)) if deal is not None else 0.0
    basic = _f(calc.fare_amount) or 0.0
    iata = {
        "pct": pct or None,
        "basic_fare": basic,
        "amount": iata_amount,
        "formula": f"{basic:,.2f} × {pct:g}% = {round(pct / 100.0 * basic, 2):,.2f}" if pct else None,
    }

    criteria: list[dict] = [{
        "group": "Deal", "step": "Airline", "passed": True, "skipped": False,
        "ticket_value": calc.airline_name or "—",
        "deal_value": getattr(deal, "airline_name", None) or "—",
        "detail": "deals are looked up by the ticket's airline, as the Airline Master names it",
    }]
    rules: list[dict] = []
    incentives: list[dict] = []
    stale = False
    if diag is not None:
        criteria.append(_step(diag.deal_validity_step, "Deal"))
        # The incentive configs that applied — or all of them, when none did (an excluded
        # line still has its deal, and the reader needs to see which config fell short).
        plbs = [p for p in diag.plbs if p.plb_overall_match] or list(diag.plbs)
        for p in plbs:
            criteria += [_step(s, p.plb_key) for s in p.steps]
        rules = [r for r in (_rule(diag.inclusion_diagnostic, "Inclusion"),
                             _rule(diag.exclusion_diagnostic, "Exclusion")) if r]
        stored = calc.incentive_breakdown or {}
        incentives = [_incentive(p, stored) for p in plbs]
        # The trace re-prices the line against the deal AS IT IS NOW. A refund's figure is
        # the original sale's reversed, so it is not re-derived here.
        if calc.status == "calculated":
            traced = sum(float(i["amount"] or 0) for i in incentives if i["applied"])
            stale = abs(traced - incentive) > 0.01

    return {
        "calc_id": calc.id,
        "status": calc.status,
        "reason": calc.reason,
        "reversal": reversed_,
        "ticket": {
            "ticket_number": calc.ticket_number, "pnr": calc.pnr,
            "passenger_name": calc.passenger_name, "airline": calc.airline_name,
            "issue_date": calc.issue_date, "travel_date": calc.travel_date,
            "segment_type": calc.segment_type, "booking_class": calc.booking_class,
            "cabin": read_as.get("cabin"),
            "sector": calc.sector, "route": read_as.get("route"),
            "route_missing_airports": read_as.get("route_missing_airports") or [],
            "invoice_type": calc.transaction_type,
            "basic_fare": _f(calc.fare_amount), "yq": _f(calc.yq), "yr": _f(calc.yr),
        },
        "deal": None if deal is None else {
            "id": deal.id, "deal_no": calc.matched_deal_no,
            "supplier_name": deal.supplier_name, "airline_name": deal.airline_name,
            "valid_from": deal.valid_from, "valid_to": deal.valid_to,
            "iata_pct": deal.iata_commission, "match_by": calc.supplier_match_by,
        },
        "traced": diag is not None,
        "criteria": criteria,
        "rules": rules,
        "incentives": incentives,
        "incentive_total": incentive,
        "iata": iata,
        "expected": expected,
        "statement": statement,
        "difference": None if statement is None else round(expected - statement, 2),
        "stale": stale,
    }
