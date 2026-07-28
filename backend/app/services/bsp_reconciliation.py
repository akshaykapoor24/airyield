"""BSP reconciliation engine.

Compares each internal UploadedTicket (EXPECTED) against its matched BSP
settlement row (ACTUAL) and writes one ``ticket_reconciliation`` row per
reconciled unit (matched settlement event, missing-in-BSP ticket, or
unexpected extra BSP row). Recompute is wholesale + idempotent (delete the
user's rows, re-insert) so it is safe to auto-run after every BSP upload.

Design notes:
- Row per settlement event: each BSP row (TKTT / ADM / ACM / RFND) is its own
  reconciliation row matched to the ticket, so ADM/ACM/Refund are filterable.
- Comprehensive, data-driven field comparison (see FIELD_SPECS); the full
  per-field diff is stored in ``field_diffs`` (a list, order-preserving), while
  the headline seven fields are also mirrored into explicit columns for summary.
- BSP rows carry no passenger/PNR columns, so matching keys on ticket_number
  (normalised: strip non-alphanumerics + leading zeros, per _classify_ticket),
  with a last-10-digit fallback surfaced as ``possible_match`` (never auto-linked).
- All money handled as Decimal.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dateutil import parser as _dateparser
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bsp_statement import BspStatementRow, BspTaxBreakup
from app.models.ticket_reconciliation import TicketReconciliation
from app.models.uploaded_ticket import UploadedTicket

Q = Decimal("0.01")
ZERO = Decimal("0")

# Expected earnings the calculation engine writes (from incentive_breakdown) — no
# BSP counterpart, shown expected-only. Mirrors tickets.INCENTIVE_TYPE_KEYS.
INCENTIVE_TYPE_KEYS = [
    "PLB", "Super PLB", "Transaction Fee", "Deposit Incentive (DI)",
    "Marketing Fund", "Ancillary", "Frontend", "Backend", "Cashback",
    "Segment Incentive", "Push Action",
]

# Ticket charge columns with no BSP counterpart — shown expected-only for full visibility.
EXPECTED_ONLY_CHARGES = [
    ("rei_sell", "REI"), ("seat_selection", "Seat Selection"), ("excess_baggage", "Excess Baggage"),
    ("meals", "Meals"), ("rfd_sell", "RFD"), ("can_charge", "Cancellation"),
    ("booking_fee_sell", "Booking Fee"), ("cgst_sell", "CGST"), ("sgst_sell", "SGST"),
    ("igst_sell", "IGST"), ("adm", "ADM (ticket)"), ("incentive_sell", "Incentive (reported)"),
    ("dis_sell", "Discount"), ("tds_sell", "TDS"), ("paid_by_credit_card", "Paid by Credit Card"),
]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    severity: str          # 'critical' | 'warning'
    abs_tol: Decimal
    pct_tol: Decimal
    headline: bool = False  # mirrored into explicit expected_/actual_ columns


# Compared fields (a BSP counterpart exists). Order = drilldown display order.
FIELD_SPECS: list[FieldSpec] = [
    FieldSpec("fare",        "Fare",               "critical", Decimal("1.00"), Decimal("0.005"), True),
    FieldSpec("yq",          "YQ Tax",             "warning",  Decimal("1.00"), Decimal("0"),     True),
    FieldSpec("yr",          "YR Tax",             "warning",  Decimal("1.00"), Decimal("0"),     True),
    FieldSpec("k3",          "K3 / GST Tax",       "warning",  Decimal("1.00"), Decimal("0"),     False),
    FieldSpec("tax",         "Total Tax",          "warning",  Decimal("1.00"), Decimal("0"),     True),
    FieldSpec("transaction", "Transaction Amount", "critical", Decimal("1.00"), Decimal("0.005"), True),
    FieldSpec("commission",  "Commission",         "warning",  Decimal("1.00"), Decimal("0"),     True),
    FieldSpec("iata_comm",   "IATA Commission",    "warning",  Decimal("1.00"), Decimal("0"),     False),
    FieldSpec("balance",     "Balance / Net",      "warning",  Decimal("1.00"), Decimal("0"),     True),
]
HEADLINE_KEYS = [s.key for s in FIELD_SPECS if s.headline]


def _d(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def norm_tn(s) -> str | None:
    """Normalise a ticket/document number for joining: drop non-alphanumerics and
    leading zeros (consistent with tickets._classify_ticket's lstrip('0'))."""
    if not s:
        return None
    core = re.sub(r"[^0-9A-Za-z]", "", str(s))
    core = core.lstrip("0") or "0"
    return core.upper() or None


def _alt_key(s) -> str | None:
    """Fallback join key: last 10 alphanumerics (handles stock/airline prefixes)."""
    n = norm_tn(s)
    if not n or len(n) < 10:
        return None
    return n[-10:]


def _parse_date(*vals) -> date | None:
    for v in vals:
        if isinstance(v, date):
            return v
        if v:
            try:
                return _dateparser.parse(str(v), dayfirst=True).date()
            except (ValueError, OverflowError, TypeError):
                continue
    return None


def _ticket_expected(t: UploadedTicket, commission_source: str) -> dict[str, Decimal | None]:
    return {
        "fare":        _d(t.sell_fare),
        "yq":          _d(t.sell_tax_yq),
        "yr":          _d(t.sale_yr),
        "k3":          _d(t.sale_k3),
        "tax":         _d(t.sell_tax),
        "transaction": _d(t.total_amt),
        "commission":  _d(t.iata_commission) if commission_source == "iata" else _d(t.comm_sell),
        "iata_comm":   _d(t.iata_commission),
        "balance":     _d(t.net_amt),
    }


def _bsp_actual(row: BspStatementRow, agg: dict | None) -> dict[str, Decimal | None]:
    by_code: dict[str, Decimal] = (agg or {}).get("by_code", {})
    tax_total: Decimal | None = (agg or {}).get("tax_total")

    def csum(*codes) -> Decimal | None:
        vals = [by_code[c] for c in codes if c in by_code]
        return sum(vals, ZERO) if vals else None

    fare = _d(row.fare_amount)
    if fare is None:
        fare = _d(row.gross)
    txn = _d(row.transaction_amount)
    if txn is None:
        txn = _d(row.gross)
    comm = _d(row.standard_commission_amount)
    if comm is None:
        comm = _d(row.commission)
    bal = _d(row.balance_payable)
    if bal is None:
        bal = _d(row.net_due)
    return {
        "fare":        fare,
        "yq":          csum("YQ"),
        "yr":          csum("YR"),
        "k3":          csum("K3", "IN", "GST"),
        "tax":         tax_total,
        "transaction": txn,
        "commission":  comm,
        "iata_comm":   comm,
        "balance":     bal,
    }


def _compare(spec: FieldSpec, exp: Decimal | None, act: Decimal | None):
    """Return (variance, match, is_issue). None on both sides → skipped."""
    if exp is None and act is None:
        return None, None, False
    e = exp if exp is not None else ZERO
    a = act if act is not None else ZERO
    variance = (e - a).quantize(Q)
    tol = spec.abs_tol + spec.pct_tol * abs(e)
    match = abs(variance) <= tol
    return variance, match, (not match)


@dataclass
class RunSummary:
    run_id: str
    reconciled_at: datetime
    total: int = 0
    matched: int = 0
    minor_diff: int = 0
    mismatch: int = 0
    missing_bsp: int = 0
    extra_bsp: int = 0
    possible_match: int = 0
    total_abs_variance: float = 0.0


class BspReconciliationService:

    @staticmethod
    async def run(
        db: AsyncSession,
        *,
        tenant_id: int,
        created_by_id: int,
        commission_source: str = "reported",
        statement_id: str | None = None,   # echoed onto rows; compute is always global
    ) -> RunSummary:
        run_id = str(uuid.uuid4())
        reconciled_at = datetime.utcnow()
        commission_source = "iata" if commission_source == "iata" else "reported"

        scope = (UploadedTicket.tenant_id == tenant_id, UploadedTicket.created_by_id == created_by_id)
        tickets = (await db.execute(select(UploadedTicket).where(*scope))).scalars().all()

        bsp_scope = (BspStatementRow.tenant_id == tenant_id, BspStatementRow.created_by_id == created_by_id)
        bsp_rows = (await db.execute(select(BspStatementRow).where(*bsp_scope))).scalars().all()

        # One grouped query for all tax breakups (no N+1).
        agg: dict[int, dict] = {}
        row_ids = [r.id for r in bsp_rows]
        if row_ids:
            tax_q = (
                select(
                    BspTaxBreakup.bsp_row_id,
                    BspTaxBreakup.component_type,
                    BspTaxBreakup.component_code,
                    func.sum(BspTaxBreakup.amount),
                )
                .where(BspTaxBreakup.bsp_row_id.in_(row_ids))
                .group_by(BspTaxBreakup.bsp_row_id, BspTaxBreakup.component_type, BspTaxBreakup.component_code)
            )
            for rid, ctype, ccode, amt in (await db.execute(tax_q)).all():
                a = _d(amt) or ZERO
                d = agg.setdefault(rid, {"by_code": {}, "tax_total": ZERO})
                if ccode:
                    code = ccode.upper()
                    d["by_code"][code] = d["by_code"].get(code, ZERO) + a
                if (ctype or "").upper() in ("TAX", "FEE"):
                    d["tax_total"] += a

        # Index tickets by normalised number (primary) and last-10 (fallback).
        by_tn: dict[str, list[UploadedTicket]] = {}
        by_alt: dict[str, list[UploadedTicket]] = {}
        for t in tickets:
            k = norm_tn(t.ticket_number)
            if k:
                by_tn.setdefault(k, []).append(t)
            ak = _alt_key(t.ticket_number)
            if ak:
                by_alt.setdefault(ak, []).append(t)

        new_rows: list[TicketReconciliation] = []
        accounted_tickets: set[int] = set()
        summary = RunSummary(run_id=run_id, reconciled_at=reconciled_at)

        def _pick(cands: list[UploadedTicket], bsp_txn: str | None) -> UploadedTicket:
            # Prefer a ticket whose adm_acm_ra aligns with the BSP transaction type.
            want = (bsp_txn or "").upper()
            if want in ("ADM", "ACM", "RA"):
                for c in cands:
                    if (c.adm_acm_ra or "").upper() == want:
                        return c
            if want in ("TKTT", "", None):
                for c in cands:
                    if not c.adm_acm_ra:
                        return c
            return cands[0]

        # ── each BSP row → one reconciliation row ────────────────────────────
        for row in bsp_rows:
            key = norm_tn(row.document_number or row.ticket_number)
            actual = _bsp_actual(row, agg.get(row.id))
            bsp_txn = (row.transaction_type or "").upper() or "TKTT"

            cands = by_tn.get(key or "", [])
            if cands:
                ticket = _pick(cands, bsp_txn)
                accounted_tickets.add(ticket.id)
                rec = _build_row(
                    ticket=ticket, row=row, actual=actual, commission_source=commission_source,
                    match_method="ticket_number", forced_status=None,
                    tenant_id=tenant_id, created_by_id=created_by_id, run_id=run_id,
                    reconciled_at=reconciled_at, statement_id=statement_id, bsp_txn=bsp_txn,
                )
                # link the BSP row
                row.matched_ticket_id = ticket.id
                row.match_status = "matched"
                # sibling settlement events on the same ticket → related_bsp context
                rec.related_bsp = [
                    {"bsp_row_id": o.id, "txn_type": (o.transaction_type or "").upper() or "TKTT",
                     "amount": _f(_d(o.transaction_amount) or _d(o.gross))}
                    for o in bsp_rows if o is not row and norm_tn(o.document_number or o.ticket_number) == key
                ][:20]
            else:
                alt = by_alt.get(_alt_key(row.document_number or row.ticket_number) or "", [])
                if len(alt) == 1:
                    ticket = alt[0]
                    accounted_tickets.add(ticket.id)
                    rec = _build_row(
                        ticket=ticket, row=row, actual=actual, commission_source=commission_source,
                        match_method="heuristic", forced_status="possible_match",
                        tenant_id=tenant_id, created_by_id=created_by_id, run_id=run_id,
                        reconciled_at=reconciled_at, statement_id=statement_id, bsp_txn=bsp_txn,
                    )
                    row.match_status = "ambiguous"   # not auto-linked
                else:
                    rec = _build_extra(
                        row=row, actual=actual, tenant_id=tenant_id, created_by_id=created_by_id,
                        run_id=run_id, reconciled_at=reconciled_at, statement_id=statement_id, bsp_txn=bsp_txn,
                    )
                    row.match_status = "unmatched"
            new_rows.append(rec)

        # ── internal tickets with no matched BSP row → missing_bsp ───────────
        for t in tickets:
            if t.id in accounted_tickets:
                continue
            new_rows.append(_build_missing(
                ticket=t, commission_source=commission_source, tenant_id=tenant_id,
                created_by_id=created_by_id, run_id=run_id, reconciled_at=reconciled_at,
            ))

        # ── persist (idempotent recompute) ───────────────────────────────────
        await db.execute(delete(TicketReconciliation).where(
            TicketReconciliation.tenant_id == tenant_id,
            TicketReconciliation.created_by_id == created_by_id,
        ))
        db.add_all(new_rows)
        await db.commit()

        # tally
        for r in new_rows:
            summary.total += 1
            setattr(summary, r.match_status, getattr(summary, r.match_status) + 1)
            summary.total_abs_variance += float(r.abs_variance or 0)
        summary.total_abs_variance = round(summary.total_abs_variance, 2)
        return summary


def _status_from_issues(issues: list[dict]) -> tuple[str, str]:
    if any(i["severity"] == "critical" for i in issues):
        return "mismatch", "critical"
    if any(i["severity"] == "warning" for i in issues):
        return "minor_diff", "warning"
    return "matched", "ok"


def _expected_only_diffs(ticket: UploadedTicket) -> list[dict]:
    diffs: list[dict] = []
    bd = ticket.incentive_breakdown or {}
    for key in INCENTIVE_TYPE_KEYS:
        v = _d(bd.get(key))
        if v is not None:
            diffs.append({"field": f"inc_{key}", "label": key, "expected": _f(v),
                          "actual": None, "variance": None, "match": None, "severity": None, "kind": "expected_only"})
    ci = _d(ticket.calculated_incentive)
    if ci is not None:
        diffs.append({"field": "calculated_incentive", "label": "Calculated Incentive (total)", "expected": _f(ci),
                      "actual": None, "variance": None, "match": None, "severity": None, "kind": "expected_only"})
    if ticket.comm_sell is not None or ci is not None:
        delta = (_d(ticket.comm_sell) or ZERO) - (ci or ZERO)
        diffs.append({"field": "delta_comm", "label": "Delta Comm", "expected": _f(delta.quantize(Q)),
                      "actual": None, "variance": None, "match": None, "severity": None, "kind": "expected_only"})
    for attr, label in EXPECTED_ONLY_CHARGES:
        v = _d(getattr(ticket, attr, None))
        if v is not None:
            diffs.append({"field": attr, "label": label, "expected": _f(v),
                          "actual": None, "variance": None, "match": None, "severity": None, "kind": "expected_only"})
    return diffs


def _build_row(*, ticket, row, actual, commission_source, match_method, forced_status,
               tenant_id, created_by_id, run_id, reconciled_at, statement_id, bsp_txn) -> TicketReconciliation:
    expected = _ticket_expected(ticket, commission_source)
    field_diffs: list[dict] = []
    issues: list[dict] = []
    headline: dict[str, tuple] = {}

    for spec in FIELD_SPECS:
        exp, act = expected.get(spec.key), actual.get(spec.key)
        variance, match, is_issue = _compare(spec, exp, act)
        field_diffs.append({
            "field": spec.key, "label": spec.label,
            "expected": _f(exp), "actual": _f(act), "variance": _f(variance),
            "match": match, "severity": spec.severity if is_issue else None, "kind": "compared",
        })
        if spec.headline:
            headline[spec.key] = (exp, act, variance, match)
        if is_issue:
            issues.append({
                "rule_id": f"{spec.key.upper()}_MISMATCH", "field": spec.key, "severity": spec.severity,
                "message": f"{spec.label} differs by {_f(variance)}", "expected": _f(exp),
                "actual": _f(act), "variance": _f(variance),
            })

    field_diffs.extend(_expected_only_diffs(ticket))

    status, severity = _status_from_issues(issues)
    if forced_status:
        status = forced_status
        severity = "critical" if any(i["severity"] == "critical" for i in issues) else "warning"

    exp_txn = expected.get("transaction") or ZERO
    act_txn = actual.get("transaction") or ZERO
    net = (exp_txn - act_txn).quantize(Q)

    rec = TicketReconciliation(
        tenant_id=tenant_id, created_by_id=created_by_id, run_id=run_id, statement_id=statement_id,
        ticket_id=ticket.id, bsp_row_id=row.id,
        ticket_number=ticket.ticket_number, airline_name=ticket.airline_name,
        airline_code=ticket.airlines_code or row.airline_code,
        issue_date=_parse_date(row.issue_date, ticket.ticket_date),
        txn_type=bsp_txn, pax_name=ticket.pax_name or _joinname(ticket),
        match_status=status, severity=severity, match_method=match_method,
        commission_source=commission_source,
        net_variance=_f(net), abs_variance=_f(abs(net)),
        field_diffs=field_diffs, issues=issues, related_bsp=[], remarks=None,
        reconciled_at=reconciled_at,
    )
    for key, (exp, act, variance, match) in headline.items():
        setattr(rec, f"expected_{key}", _f(exp))
        setattr(rec, f"actual_{key}", _f(act))
        setattr(rec, f"{key}_variance", _f(variance))
        setattr(rec, f"{key}_match", match)
    return rec


def _build_missing(*, ticket, commission_source, tenant_id, created_by_id, run_id, reconciled_at) -> TicketReconciliation:
    expected = _ticket_expected(ticket, commission_source)
    field_diffs = [{
        "field": s.key, "label": s.label, "expected": _f(expected.get(s.key)),
        "actual": None, "variance": None, "match": None, "severity": None, "kind": "compared",
    } for s in FIELD_SPECS]
    field_diffs.extend(_expected_only_diffs(ticket))
    exp_txn = expected.get("transaction") or ZERO
    rec = TicketReconciliation(
        tenant_id=tenant_id, created_by_id=created_by_id, run_id=run_id, statement_id=None,
        ticket_id=ticket.id, bsp_row_id=None,
        ticket_number=ticket.ticket_number, airline_name=ticket.airline_name, airline_code=ticket.airlines_code,
        issue_date=_parse_date(ticket.ticket_date),
        txn_type=(ticket.adm_acm_ra or "TKTT").upper(), pax_name=ticket.pax_name or _joinname(ticket),
        match_status="missing_bsp", severity="critical", match_method="none",
        commission_source=commission_source,
        net_variance=_f(exp_txn.quantize(Q)), abs_variance=_f(abs(exp_txn).quantize(Q)),
        field_diffs=field_diffs, issues=[{"rule_id": "TICKET_UNMATCHED", "field": "ticket", "severity": "critical",
                                          "message": "No BSP settlement row found for this ticket."}],
        related_bsp=[], remarks="Ticket not found in any BSP statement.", reconciled_at=reconciled_at,
    )
    for key in HEADLINE_KEYS:
        setattr(rec, f"expected_{key}", _f(expected.get(key)))
    return rec


def _build_extra(*, row, actual, tenant_id, created_by_id, run_id, reconciled_at, statement_id, bsp_txn) -> TicketReconciliation:
    field_diffs = [{
        "field": s.key, "label": s.label, "expected": None, "actual": _f(actual.get(s.key)),
        "variance": None, "match": None, "severity": None, "kind": "compared",
    } for s in FIELD_SPECS]
    act_txn = actual.get("transaction") or ZERO
    rec = TicketReconciliation(
        tenant_id=tenant_id, created_by_id=created_by_id, run_id=run_id, statement_id=statement_id or row.statement_id,
        ticket_id=None, bsp_row_id=row.id,
        ticket_number=row.document_number or row.ticket_number, airline_name=None, airline_code=row.airline_code,
        issue_date=_parse_date(row.issue_date), txn_type=bsp_txn, pax_name=None,
        match_status="extra_bsp", severity="critical", match_method="none", commission_source=None,
        net_variance=_f((-act_txn).quantize(Q)), abs_variance=_f(abs(act_txn).quantize(Q)),
        field_diffs=field_diffs, issues=[{"rule_id": "BSP_UNEXPECTED", "field": "ticket", "severity": "critical",
                                          "message": "BSP settlement row with no matching internal ticket."}],
        related_bsp=[], remarks="Unexpected BSP row — no internal ticket.", reconciled_at=reconciled_at,
    )
    for key in HEADLINE_KEYS:
        setattr(rec, f"actual_{key}", _f(actual.get(key)))
    return rec


def _joinname(t: UploadedTicket) -> str | None:
    parts = [p for p in (t.first_name, t.last_name) if p]
    return " ".join(parts) or None
