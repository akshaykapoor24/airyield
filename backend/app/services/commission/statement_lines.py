"""A third-party statement, line by line, with what each line earned against your deals.

The Commission income screen for a consolidator statement (Third Party GDS / LCC) answers one
question: what the vendor's statement says it paid you, against what your deals say you should
have been paid. So it lists every TICKET line of the statement — whether or not a commission
run has reached it yet — with the statement's own columns, and beside each:

    statement commission   the vendor's Agent Commission + Incentive, signed by the line's
                           kind (earned on a sale, given back on a refund) — third_party
                           ._by_kind, so Brightsun's negative print and TripJack's positive
                           one mean the same thing
    expected commission    what the matched deal computes: incentive + IATA commission
    difference             expected − statement. Positive: the vendor paid you less than
                           your deal says (they owe you). Negative: they paid more.

The statement's own OLD / BALANCE / TOTAL lines (services/statement_balance.py) are not
tickets and are left out.

THE CARDS ADD UP. Statement, expected and difference are summed over the lines a run has
calculated, so expected − statement = difference on screen to the paisa. What the vendor
printed on lines not calculated yet is reported beside it (`statement_pending`), never mixed in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services import flat_statement, statement_balance
from app.services.commission import third_party as tpc
from app.services.statement_display import display_columns, flatten_record

# Where a line stands, from its calculation's status. "pending" = no run has reached it.
MATCHED = frozenset({"calculated", "reversed"})          # a deal was found and applied
UNMATCHED = frozenset({"unmatched", "needs_data"})       # no deal (or none that can be judged)
OTHER = frozenset({"excluded", "skipped"})               # a deal's rule left it out / not a sale

# What a card filters the table to.
BUCKETS = ("all", "matched", "unmatched", "other", "pending", "statement", "iata", "expected",
           "difference")

# A gap smaller than a rupee is the two sides rounding differently (590.277 printed, 590.28
# computed), not a short-payment — the Payment Module's own tolerance.
DIFF_TOLERANCE = 1.0

# Amounts in the statement's columns, for the grid to right-align. Comm % and Pax Count are
# numbers but not money.
_MONEY = frozenset(flat_statement._MONEY_FIELDS) - {"commission_rate", "passenger_count"}


def bucket_of(status: str | None) -> str:
    if not status or status == "pending":
        return "pending"
    if status in MATCHED:
        return "matched"
    if status in UNMATCHED:
        return "unmatched"
    return "other"


@dataclass
class Line:
    line_id: int
    values: dict
    kind: str                       # issue | refund | skip (third_party.classify)
    airline: str | None
    invoice_type: str | None
    statement: float | None         # vendor commission + incentive, signed by kind
    expected: float | None          # None until a run reaches the line
    difference: float | None
    net_ok: bool | None             # did the vendor's own figures add up to its Net Amount
    calc: Any = None                # the CommissionCalculation, or None
    search_text: str = ""

    @property
    def bucket(self) -> str:
        return bucket_of(getattr(self.calc, "status", None))


def _money(v) -> float:
    return float(v) if v is not None else 0.0


def build_line(slug: str, row, calc) -> Line:
    """One statement line and its calculation (or None) → a Line."""
    data = row.data or {}
    kind, _reason = tpc.classify(data, cancelled_as_refund=True)
    declared = tpc.build_declared(data, kind)
    statement = (None if declared.commission is None and declared.incentive is None
                 else round(_money(declared.commission) + _money(declared.incentive), 2))
    expected = difference = None
    if calc is not None and bucket_of(calc.status) != "pending":
        expected = round(_money(calc.incentive) + _money(calc.iata_commission), 2)
        difference = round(expected - (statement or 0.0), 2)
    values = flatten_record(slug, row)
    search = " ".join(str(data.get(k) or "") for k in (
        "ticket_number", "pnr", "gds_pnr", "airline_pnr", "passenger_name", "first_name",
        "last_name", "invoice_number"))
    if calc is not None:
        search += f" {calc.matched_deal_name or ''} {calc.matched_deal_no or ''}"
    return Line(
        line_id=row.id, values=values, kind=kind,
        airline=data.get("airline_master_name") or data.get("airline_name") or None,
        invoice_type=data.get("ticket_status") or None,
        statement=statement, expected=expected, difference=difference,
        net_ok=declared.net_ok, calc=calc, search_text=search.lower(),
    )


def is_ticket(row) -> bool:
    """Not the statement's own OLD / BALANCE / TOTAL line — including a TOTAL saved before
    statement_balance learned to see one in the Ticket No column."""
    return not statement_balance.is_balance_row(row.data or {})


def in_bucket(line: Line, bucket: str) -> bool:
    if bucket in ("", "all"):
        return True
    if bucket == "statement":
        return abs(line.statement or 0.0) >= 0.01
    if bucket == "iata":
        return abs(_money(getattr(line.calc, "iata_commission", None))) >= 0.01
    if bucket == "expected":
        return abs(line.expected or 0.0) >= 0.01
    if bucket == "difference":
        return line.difference is not None and abs(line.difference) >= DIFF_TOLERANCE
    return line.bucket == bucket


def matches(line: Line, *, search: str = "", air: str = "", txn: str = "") -> bool:
    if search and search.strip().lower() not in line.search_text:
        return False
    if air and (line.airline or "") != air:
        return False
    if txn and (line.invoice_type or "") != txn:
        return False
    return True


def totals(lines: list[Line]) -> dict:
    """The cards. Money over calculated lines only — see the module docstring."""
    counts = {"matched": 0, "unmatched": 0, "other": 0, "pending": 0}
    statement = expected = iata = statement_pending = 0.0
    differing = unverified = with_iata = 0
    for ln in lines:
        b = ln.bucket
        counts[b] += 1
        if b == "pending":
            statement_pending += ln.statement or 0.0
            continue
        statement += ln.statement or 0.0
        expected += ln.expected or 0.0
        line_iata = _money(getattr(ln.calc, "iata_commission", None))
        iata += line_iata
        if abs(line_iata) >= 0.01:
            with_iata += 1
        if ln.difference is not None and abs(ln.difference) >= DIFF_TOLERANCE:
            differing += 1
        if ln.net_ok is False:
            unverified += 1
    statement, expected = round(statement, 2), round(expected, 2)
    return {
        "tickets": len(lines), **counts,
        "statement_commission": statement,
        "statement_pending": round(statement_pending, 2),
        "expected_commission": expected,
        # The deal's IATA % on the basic fare (commission/runner.py) — part of expected, and
        # its own card, since it is a different entitlement from the deal's incentive.
        "iata_commission": round(iata, 2),
        "incentive": round(expected - iata, 2),
        "with_iata": with_iata,
        "difference": round(expected - statement, 2),
        "differing": differing,
        "unverified": unverified,
    }


def columns(slug: str, lines: list[Line]) -> list[dict]:
    """The statement's own columns, in the statement view's order — only those this file
    fills on at least one ticket line: vendors print 25 to 40 of the 50-odd, and a grid of
    empty columns hides the ones that matter."""
    out = []
    for c in display_columns(slug):
        f = c["field"]
        if f.startswith("__"):
            continue
        if not any(ln.values.get(f) not in (None, "") for ln in lines):
            continue
        out.append({"field": f, "header": c["header"], "kind": "money" if f in _MONEY else None})
    return out
