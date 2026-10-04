"""Payment Module: what a consolidator billed, against what our own books say.

THE TWO SIDES ARE RECORDS OF THE SAME PURCHASE. The VENDOR side is one `tp-gds` upload —
the exact rows Statements → Third Party → GDS shows and Commission income prices. The MO
side is one `mo-gds` upload, the workspace's mid-office record, parsed by the same builder
(services/flat_statement.py). Unlike sell_reconciliation there is no markup to allow for:
every figure is expected to agree, so the tolerance is ₹1 with no percentage.

SIGN CONVENTION: `variance = vendor - mo`. Positive = the vendor billed more than our books
record. Passed to the shared `_compare(spec, buy, sell)` as (mo, vendor) to get it.

BOTH SIDES ARE NETTED PER TICKET before they meet. A consolidator prints a cancellation as
a second, negative row against the same ticket number; comparing rows rather than tickets
would turn one cancellation into two huge, opposite, meaningless variances. Same reasoning
as `sell_reconciliation._group_buy_rows`, and the drill-down lists the rows behind each
figure so nothing is hidden by the netting.

THE STATEMENT'S OWN BALANCE LINES ARE NOT TICKETS. The real export is a running account: an
`OLD <opening>` line above the header (dropped at ingest) and a `BALANCE <closing>` line
after the last ticket, which ingest stores as a row — `{"cancellation_markup": "BALANCE",
"net_amount": "960428.43"}`. Matched as a ticket it would be a ₹9.6 lakh "vendor only" at
the top of every page; it is lifted out instead and reported as the closing balance.

COMMISSION comes from `commission_calculations` for source `tp-gds`, joined ROW TO ROW on
`source_row_id` — the vendor side IS the commission engine's input, so nothing is matched
by ticket number here. Only rows a deal actually priced count (`MATCHED_STATUSES`), and the
shortfall on a row is the engine's own gross-to-gross `variance_total`, used only when the
vendor's arithmetic closed. A skipped row (CANCELLED / VOID) contributes nothing to EITHER
side: its negative Agent Commission is the vendor correctly clawing commission back, and
reading it against a calculated zero would claim the vendor owes us that claw-back.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_calculation import CommissionCalculation
from app.models.commission_run import SOURCE_TP_GDS, CommissionRun
from app.models.payment_reconciliation import (
    COMMISSION_NONE, COMMISSION_NOT_RUN, COMMISSION_PARTIAL, COMMISSION_PRICED,
    COMMISSION_SKIPPED, COMMISSION_UNPRICED, ENGINE_VERSION, MO_VENDOR_CORRECTED,
    MO_VENDOR_NONE, MO_VENDOR_OK, MO_VENDOR_OTHER, PAYMENT_RECON_STATUSES,
    STATUS_MATCHED, STATUS_MINOR_DIFF, STATUS_MISMATCH, STATUS_MO_ONLY, STATUS_POSSIBLE,
    STATUS_VENDOR_ONLY, PaymentReconciliation, PaymentReconciliationRun,
)
from app.models.payment_ledger import MoVendorCorrection, PaymentItem
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import STATEMENT_MODELS
from app.services import statement_balance
from app.services.commission.calc_row import KIND_ISSUE, KIND_REFUND
from app.services.commission.runner import MATCHED_STATUSES
from app.services.commission.third_party import classify as classify_status
from app.services.reconciliation.adapters import _iso_date, _norm, _s, _split_joined
from app.services.reconciliation.buy_row import to_decimal
from app.services.sell_reconciliation import (
    ZERO, FieldSpec, _compare, _d, _f, _status_from_issues,
)

VENDOR_SLUG = "tp-gds"
MO_SLUG = "mo-gds"

# Only these pair the two sides, so only these carry a variance.
PAIRED_STATUSES = (STATUS_MATCHED, STATUS_MINOR_DIFF, STATUS_MISMATCH)

_TOL = Decimal("1.00")
_NO_PCT = Decimal("0")

# Display order in the drill-down. Net last: it is the figure the payment is made on.
PAYMENT_FIELD_SPECS: list[FieldSpec] = [
    FieldSpec("fare",                "Basic fare",          "critical", _TOL, _NO_PCT),
    FieldSpec("yq",                  "YQ",                  "warning",  _TOL, _NO_PCT),
    FieldSpec("tax",                 "Total tax",           "warning",  _TOL, _NO_PCT),
    FieldSpec("ssr",                 "SSR",                 "warning",  _TOL, _NO_PCT),
    FieldSpec("reschedule",          "Reschedule charges",  "warning",  _TOL, _NO_PCT),
    FieldSpec("gross",               "Total fare",          "critical", _TOL, _NO_PCT),
    FieldSpec("commission",          "Agent commission",    "warning",  _TOL, _NO_PCT),
    FieldSpec("incentive",           "Incentive",           "warning",  _TOL, _NO_PCT),
    FieldSpec("tds",                 "TDS",                 "warning",  _TOL, _NO_PCT),
    FieldSpec("service_charge",      "Service charge",      "warning",  _TOL, _NO_PCT),
    FieldSpec("service_fee",         "Service fee (SF)",    "warning",  _TOL, _NO_PCT),
    FieldSpec("gst_on_sf",           "GST on SF",           "warning",  _TOL, _NO_PCT),
    FieldSpec("agent_penalty",       "Agent penalty",       "warning",  _TOL, _NO_PCT),
    FieldSpec("cancellation_markup", "Cancellation markup", "warning",  _TOL, _NO_PCT),
    FieldSpec("net",                 "Net amount",          "critical", _TOL, _NO_PCT),
]
PAYMENT_FIELDS = tuple(s.key for s in PAYMENT_FIELD_SPECS)

# The `data` key behind each figure. `tax` is built, not read — see `_tax_total`.
_DATA_KEY = {
    "fare": "base_fare", "yq": "yq", "ssr": "ssr_amount",
    "reschedule": "reschedule_charges", "gross": "total_fare",
    "commission": "commission_amount", "incentive": "incentive_amount", "tds": "tds",
    "service_charge": "service_charge", "service_fee": "service_fee",
    "gst_on_sf": "gst_on_sf", "agent_penalty": "agent_penalty",
    "cancellation_markup": "cancellation_markup", "net": "net_amount",
}

# ── balance / total lines ────────────────────────────────────────────────────
# One definition, shared with ingest (which stamps `row_kind`), the statements router and
# commission income — see services/statement_balance.py. Re-exported under the old name.
balance_kind = statement_balance.balance_kind

_TITLES = {"MR", "MRS", "MS", "MSTR", "MISS", "DR", "MASTER", "PROF", "SMT", "SHRI"}

# A ticket's row is a SALE when the commission engine would price it as an issue — the
# same Status vocabulary (services/commission/third_party.classify). Cancellations and
# refunds are never sales, so they can never make a ticket a duplicate.
KIND_SALE, KIND_CANCEL, KIND_REFUND_ROW = "sale", "cancel", "refund"


def _pax_key(name: str | None) -> str | None:
    """'MR. SAHOTA/VIKAS' and 'Mr Vikas Sahota' → 'SAHOTA VIKAS'.

    Titles dropped, punctuation ignored, words sorted — the two systems order surname and
    given name differently, and neither is wrong.
    """
    if not name:
        return None
    words = [w for w in re.split(r"[^A-Z]+", name.upper()) if w and w not in _TITLES]
    return " ".join(sorted(words)) or None


def _tax_total(yq: Decimal | None, other: Decimal | None, taxes: Decimal | None):
    """YQ plus the rest of the tax bill — None only when neither is printed.

    `taxes` stands in for `other_taxes`, never beside it: the same rule ingest uses to
    derive `total_fare` (flat_statement._derive_tp_gds), so the two can never disagree.
    """
    rest = other if other is not None else taxes
    parts = [p for p in (yq, rest) if p is not None]
    return sum(parts) if parts else None


# ── one statement row, normalised ────────────────────────────────────────────
@dataclass
class PayRow:
    row_id: int
    ticket_key: str | None = None
    ticket_prefix: str | None = None
    ticket_number: str | None = None
    pnr: str | None = None
    pax_name: str | None = None
    airline_name: str | None = None
    airline_code: str | None = None
    issue_date: date | None = None
    sector: str | None = None
    status: str | None = None                 # the file's own Status column
    kind: str = KIND_SALE                     # sale | cancel | refund
    booking_id: str | None = None             # MO: the booking/invoice it was billed under
    booking_class: str | None = None
    travel_date: date | None = None
    segment_type: str | None = None
    # MO rows only: which upload and which vendor this row belongs to, and whether it is
    # filed here by a correction (step 6C).
    origin: dict | None = None
    amounts: dict[str, Decimal | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def pnr_pax_key(self) -> str | None:
        pax = _pax_key(self.pax_name)
        return f"{self.pnr.upper()}|{pax}" if self.pnr and pax else None


def _row_kind(data: dict) -> str:
    kind, _reason = classify_status(data)
    if kind == KIND_ISSUE:
        return KIND_SALE
    return KIND_REFUND_ROW if kind == KIND_REFUND else KIND_CANCEL


def build_pay_row(row_id: int, data: dict | None, *, origin: dict | None = None) -> PayRow:
    """A `third_party_gds` / `mid_office_gds` row's `data` blob as a PayRow."""
    data = dict(data or {})
    notes: list[str] = []

    def money(key: str) -> Decimal | None:
        raw = data.get(key)
        val = to_decimal(raw)
        if val is None and raw not in (None, ""):
            notes.append(f"'{key}' was {raw!r}, which is not a number — not compared.")
        return val

    amounts: dict[str, Decimal | None] = {k: money(dk) for k, dk in _DATA_KEY.items()}
    amounts["tax"] = _tax_total(amounts["yq"], money("other_taxes"), money("taxes"))

    tn = _s(data.get("ticket_number"))
    prefix = _s(data.get("ticket_prefix"))
    # Some exports write the two joined into one cell ("607 5808583279"). Splitting fails
    # closed and is idempotent, exactly as in the buy-vs-sell adapter.
    if tn and not prefix:
        code, serial = _split_joined(tn)
        if code:
            prefix, tn = code, serial
    prefix = prefix.zfill(3) if prefix else None

    issue = None
    for k in ("issue_date", "booking_date", "transaction_date"):
        issue = _iso_date(data.get(k))
        if issue:
            break

    return PayRow(
        row_id=row_id,
        ticket_key=_norm(tn),
        ticket_prefix=prefix,
        ticket_number=tn,
        pnr=_s(data.get("airline_pnr")) or _s(data.get("pnr")) or _s(data.get("gds_pnr")),
        pax_name=_s(data.get("passenger_name")),
        # The airline master's spelling where ingest resolved one, else the file's.
        airline_name=_s(data.get("airline_master_name")) or _s(data.get("airline_name")),
        airline_code=_s(data.get("airline_code")),
        issue_date=issue,
        sector=_s(data.get("sector")),
        status=_s(data.get("ticket_status")),
        kind=_row_kind(data),
        booking_id=_s(data.get("booking_id")) or _s(data.get("invoice_number")),
        booking_class=_s(data.get("booking_class")),
        travel_date=_iso_date(data.get("travel_date")),
        segment_type=_s(data.get("segment_type")),
        origin=origin,
        amounts=amounts,
        notes=notes,
    )


# ── one ticket, netted across its rows ───────────────────────────────────────
@dataclass
class TicketGroup:
    key: str
    rows: list[PayRow] = field(default_factory=list)
    amounts: dict[str, Decimal | None] = field(
        default_factory=lambda: {k: None for k in PAYMENT_FIELDS})

    def _first(self, attr: str):
        for r in self.rows:
            v = getattr(r, attr)
            if v:
                return v
        return None

    @property
    def row_ids(self) -> list[int]:
        return [r.row_id for r in self.rows]

    @property
    def ticket_key(self) -> str | None:
        return self._first("ticket_key")

    @property
    def ticket_prefix(self) -> str | None:
        return self._first("ticket_prefix")

    @property
    def ticket_number(self) -> str | None:
        return self._first("ticket_number")

    @property
    def pnr(self) -> str | None:
        return self._first("pnr")

    @property
    def pax_name(self) -> str | None:
        return self._first("pax_name")

    @property
    def pnr_pax_key(self) -> str | None:
        return self._first("pnr_pax_key")

    @property
    def airline_name(self) -> str | None:
        return self._first("airline_name")

    @property
    def airline_code(self) -> str | None:
        return self._first("airline_code")

    @property
    def sector(self) -> str | None:
        return self._first("sector")

    @property
    def issue_date(self) -> date | None:
        # The earliest date is the issue; a later row on the same ticket is the change.
        dates = [r.issue_date for r in self.rows if r.issue_date]
        return min(dates) if dates else None

    @property
    def booking_id(self) -> str | None:
        return self._first("booking_id")

    @property
    def booking_class(self) -> str | None:
        return self._first("booking_class")

    @property
    def travel_date(self) -> date | None:
        return self._first("travel_date")

    @property
    def segment_type(self) -> str | None:
        return self._first("segment_type")

    @property
    def origin(self) -> dict | None:
        """MO groups: the upload and vendor the ticket's rows came from."""
        return self._first("origin")

    @property
    def sale_rows(self) -> int:
        return sum(1 for r in self.rows if r.kind == KIND_SALE)

    def amount(self, key: str) -> Decimal | None:
        return self.amounts.get(key)

    def notes(self, side: str) -> list[str]:
        out: list[str] = []
        for r in self.rows:
            for n in r.notes:
                if n not in out:
                    out.append(n)
        if len(self.rows) > 1:
            statuses = ", ".join(sorted({(r.status or "no status").upper() for r in self.rows}))
            out.append(f"The {side} figures are the net of {len(self.rows)} rows for this "
                       f"ticket ({statuses}).")
        return out


def group_rows(rows: list[PayRow]) -> list[TicketGroup]:
    """Net one side's rows per ticket.

    Key priority: the document serial, else PNR + passenger, else the row itself. A row
    with neither is never pooled with anything — pooling on a blank key would invent a
    ticket out of unrelated rows.
    """
    groups: dict[str, TicketGroup] = {}
    order: list[str] = []
    for r in rows:
        if r.ticket_key:
            key = f"k:{r.ticket_key}"
        elif r.pnr_pax_key:
            key = f"p:{r.pnr_pax_key}"
        else:
            key = f"r:{r.row_id}"
        g = groups.get(key)
        if g is None:
            g = groups[key] = TicketGroup(key=key)
            order.append(key)
        g.rows.append(r)
        for f_ in PAYMENT_FIELDS:
            v = r.amounts.get(f_)
            if v is None:
                continue
            g.amounts[f_] = v if g.amounts[f_] is None else g.amounts[f_] + v
    return [groups[k] for k in order]


# ── pairing ──────────────────────────────────────────────────────────────────
@dataclass
class Pairing:
    vendor: TicketGroup | None
    mo: TicketGroup | None
    method: str = "none"           # ticket_number | pnr_pax | none
    possible: bool = False         # same serial, different airline


def pair_groups(vendor: list[TicketGroup], mo: list[TicketGroup]) -> list[Pairing]:
    """Pair vendor tickets with MO tickets.

    1. The document serial, exactly. THE PREFIX IS THE CHECK, NOT THE KEY: a serial is only
       unique within one airline, so the same serial under two accounting codes is a
       `possible` pairing — shown side by side, never reconciled, never counted.
    2. PNR + passenger, but only where one side prints no ticket number at all, and only
       when exactly one candidate remains. Two tickets of one passenger on one PNR (an
       outbound and a return issued separately) must not be paired by guesswork.
    3. Whatever is left is one-sided.
    """
    consumed: set[int] = set()
    paired: dict[int, Pairing] = {}

    mo_by_ticket = {g.ticket_key: g for g in mo if g.ticket_key}
    for i, v in enumerate(vendor):
        if not v.ticket_key:
            continue
        m = mo_by_ticket.get(v.ticket_key)
        if m is None or id(m) in consumed:
            continue
        vp, mp = v.ticket_prefix, m.ticket_prefix
        consumed.add(id(m))
        paired[i] = Pairing(v, m, "ticket_number", possible=bool(vp and mp and vp != mp))

    mo_by_pnr: dict[str, list[TicketGroup]] = {}
    for g in mo:
        if id(g) not in consumed and g.pnr_pax_key:
            mo_by_pnr.setdefault(g.pnr_pax_key, []).append(g)
    for i, v in enumerate(vendor):
        if i in paired or not v.pnr_pax_key:
            continue
        cands = [g for g in mo_by_pnr.get(v.pnr_pax_key, [])
                 if id(g) not in consumed and (not v.ticket_key or not g.ticket_key)]
        if len(cands) == 1:
            consumed.add(id(cands[0]))
            paired[i] = Pairing(v, cands[0], "pnr_pax")

    out = [paired.get(i) or Pairing(v, None) for i, v in enumerate(vendor)]
    out += [Pairing(None, g) for g in mo if id(g) not in consumed]
    return out


def attach_other_vendor(pairings: list[Pairing], other_mo: list[TicketGroup]) -> None:
    """Step 6C: a vendor ticket our own MO file for this vendor does not have, found in
    ANOTHER vendor's MO file — the mid-office booked it against the wrong vendor.

    Paired in place (so its figures can still be compared) with method `other_vendor`; the
    result row says which vendor's file it sits in, and a correction files it here on the
    next run. Exact serial only, prefix-checked, and only when exactly one other MO ticket
    claims it — a guess across vendors would be worse than no answer.
    """
    by_serial: dict[str, list[TicketGroup]] = {}
    for g in other_mo:
        if g.ticket_key:
            by_serial.setdefault(g.ticket_key, []).append(g)
    taken: set[int] = set()
    for p in pairings:
        if p.mo is not None or p.vendor is None or not p.vendor.ticket_key:
            continue
        vp = p.vendor.ticket_prefix
        cands = [g for g in by_serial.get(p.vendor.ticket_key, [])
                 if id(g) not in taken
                 and not (vp and g.ticket_prefix and vp != g.ticket_prefix)]
        if len(cands) == 1:
            taken.add(id(cands[0]))
            p.mo, p.method = cands[0], "other_vendor"


# ── commission ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CalcFigure:
    """The parts of one `commission_calculations` row this module reads."""
    status: str
    reason: str | None = None
    incentive: Decimal | None = None
    iata: Decimal | None = None
    variance_total: Decimal | None = None
    net_ok: bool | None = None
    deal_no: str | None = None
    deal_name: str | None = None


def commission_for_group(g: TicketGroup | None, calcs: dict[int, CalcFigure], *,
                         commission_ran: bool) -> dict:
    """The deal-computed commission, the shortfall and the payable for one vendor ticket."""
    if g is None:
        return {"vendor_commission": None, "calc_commission": None,
                "commission_shortfall": None, "payable_after_commission": None,
                "commission_status": COMMISSION_NONE, "commission_detail": []}

    detail: list[dict] = []
    calc_sum: Decimal | None = None
    short_sum: Decimal | None = None
    with_calc = priced = unpriced = unverified = 0

    for r in g.rows:
        c = calcs.get(r.row_id)
        entry: dict = {
            "source_row_id": r.row_id,
            "ticket_status": r.status,
            "declared_commission": _f(r.amounts.get("commission")),
            "declared_incentive": _f(r.amounts.get("incentive")),
            "declared_tds": _f(r.amounts.get("tds")),
        }
        if c is None:
            if commission_ran:
                unpriced += 1
                entry.update(status="missing", reason=(
                    "No commission figure for this row — it was added or re-processed "
                    "after the last commission run. Run commission income again."))
            else:
                entry.update(status="not_run", reason=(
                    "Commission income has not been run for this statement yet."))
            detail.append(entry)
            continue

        with_calc += 1
        entry.update(status=c.status, reason=c.reason, deal_no=c.deal_no,
                     deal_name=c.deal_name, iata=_f(c.iata), incentive=_f(c.incentive),
                     net_ok=c.net_ok)
        if c.status in MATCHED_STATUSES:
            priced += 1
            calc = (c.incentive or ZERO) + (c.iata or ZERO)
            entry["calc_commission"] = _f(calc)
            calc_sum = calc if calc_sum is None else calc_sum + calc
            if c.net_ok is True and c.variance_total is not None:
                entry["shortfall"] = _f(c.variance_total)
                short_sum = (c.variance_total if short_sum is None
                             else short_sum + c.variance_total)
            else:
                unverified += 1
                entry["note"] = ("The vendor's own figures on this row do not add up to its "
                                 "Net Amount, so no shortfall is claimed on it.")
        elif c.status != "skipped":
            unpriced += 1
        detail.append(entry)

    if with_calc == 0:
        status = COMMISSION_UNPRICED if commission_ran else COMMISSION_NOT_RUN
    elif priced == 0 and unpriced == 0:
        status = COMMISSION_SKIPPED
    elif priced == 0:
        status = COMMISSION_UNPRICED
    elif unpriced == 0 and unverified == 0:
        status = COMMISSION_PRICED
    else:
        status = COMMISSION_PARTIAL

    declared = [v for r in g.rows
                for v in (r.amounts.get("commission"), r.amounts.get("incentive"))
                if v is not None]
    vendor_net = g.amount("net")
    payable = (vendor_net - (short_sum or ZERO)) if vendor_net is not None else None
    return {
        "vendor_commission": _f(sum(declared)) if declared else None,
        "calc_commission": _f(calc_sum),
        "commission_shortfall": _f(short_sum),
        "payable_after_commission": _f(payable),
        "commission_status": status,
        "commission_detail": detail,
    }


# ── one result row ───────────────────────────────────────────────────────────
def _money(v: Decimal | None) -> str:
    return "—" if v is None else f"{v.quantize(Decimal('0.01')):,}"


def _same(a, b) -> bool:
    """Class/sector/date compared as people write them: case, spaces and '-' vs '/' aside."""
    def norm(x):
        return re.sub(r"\s+", "", str(x).upper().replace("-", "/"))
    return norm(a) == norm(b)


def process_checks(p: Pairing, *, prior_sales: dict[str, dict], mo_has_booking: bool,
                   vendor_supplier: dict | None) -> dict:
    """Steps 6A–6E for one reconciled ticket: duplicate, MO vendor, booking id, enrichment.

    Returns the columns plus `issues` to append. None of these change the money verdict —
    a duplicate whose amounts agree is still `matched`; what it changes is whether it is
    payable (services/payment_ledger.py).
    """
    v, m = p.vendor, p.mo
    issues: list[dict] = []
    notes: list[str] = []

    def issue(severity: str, message: str, field: str | None = None):
        issues.append({"field": field, "label": None, "severity": severity, "message": message,
                       "vendor": None, "mo": None, "variance": None})

    # ── 6A/6B duplicates ─────────────────────────────────────────────────────
    duplicate_info = None
    if v is not None and v.ticket_key and v.sale_rows:
        prior = prior_sales.get(v.ticket_key)
        if prior and not (v.ticket_prefix and prior.get("prefix")
                          and v.ticket_prefix != prior["prefix"]):
            duplicate_info = {"kind": "earlier", **{k: prior.get(k) for k in (
                "batch_id", "source_file", "uploaded_at", "paid")}}
            when = str(prior.get("uploaded_at") or "")[:10]
            issue("critical",
                  f"Billed before, on {prior.get('source_file') or 'an earlier statement'}"
                  f"{f' (uploaded {when})' if when else ''}"
                  f"{' — and already paid' if prior.get('paid') else ''}. Marked duplicate "
                  f"and ignored for payout unless Operations decides otherwise.")
        elif v.sale_rows >= 2:
            duplicate_info = {"kind": "within", "sale_rows": v.sale_rows}
            issue("critical",
                  f"Billed {v.sale_rows} times in this statement — {v.sale_rows} sale rows for "
                  f"one ticket. Marked duplicate and ignored for payout unless Operations "
                  f"decides otherwise.")

    # ── 6C vendor mapping in MO ──────────────────────────────────────────────
    origin = (m.origin or {}) if m is not None else {}
    if m is None:
        mo_status, mo_info = MO_VENDOR_NONE, None
    elif p.method == "other_vendor":
        mo_status = MO_VENDOR_OTHER
        mo_info = {k: origin.get(k) for k in ("batch_id", "supplier_id", "supplier_name",
                                             "source_file")}
        issue("critical",
              f"Not in this vendor's MO statement — found in "
              f"{origin.get('supplier_name') or 'another vendor'}'s MO file "
              f"({origin.get('source_file') or origin.get('batch_id')}). The mid office booked "
              f"this ticket against the wrong vendor; correct it to file it here.")
    elif origin.get("vendor_status") == MO_VENDOR_CORRECTED:
        mo_status = MO_VENDOR_CORRECTED
        mo_info = {k: origin.get(k) for k in ("batch_id", "supplier_id", "supplier_name",
                                             "source_file", "corrected_from")}
        notes.append(f"Filed under this vendor by a correction — the mid office had it in "
                     f"{origin.get('corrected_from') or 'another vendor'}'s file "
                     f"({origin.get('source_file') or origin.get('batch_id')}).")
    else:
        mo_status = MO_VENDOR_OK
        mo_info = dict(vendor_supplier) if vendor_supplier else None

    # ── 6D booking id ────────────────────────────────────────────────────────
    # A possible match (same serial, another airline) is not this ticket — nothing of the MO
    # side is mapped onto it.
    booking_id = m.booking_id if m is not None and not p.possible else None
    not_billed = bool(v is not None and m is not None and not p.possible
                      and not booking_id and mo_has_booking)
    if not_billed:
        issue("warning",
              "The MO statement shows no booking ID for this ticket — it may never have been "
              "billed to a customer.", field="booking_id")

    # ── 6E class / sector / travel date ──────────────────────────────────────
    enrichment: dict = {}
    if v is not None and m is not None and not p.possible:
        for key, label, vv, mv in (
            ("booking_class", "Class", v.booking_class, m.booking_class),
            ("sector", "Sector", v.sector, m.sector),
            ("travel_date", "Travel date", v.travel_date, m.travel_date),
        ):
            if mv in (None, ""):
                continue
            shown = mv.isoformat() if isinstance(mv, date) else str(mv)
            if vv in (None, ""):
                enrichment[key] = {"value": shown, "source": "mo"}
            elif not _same(vv, mv):
                vshown = vv.isoformat() if isinstance(vv, date) else str(vv)
                issue("warning", f"{label} differs: vendor {vshown}, MO {shown}.", field=key)
        if enrichment:
            labels = {"booking_class": "class", "sector": "sector", "travel_date": "travel date"}
            notes.append(f"The vendor prints no {', '.join(labels[k] for k in enrichment)}; "
                         f"the MO statement's is used for income — Calculate income applies it.")

    return {
        "is_duplicate": duplicate_info is not None,
        "duplicate_info": duplicate_info,
        "mo_vendor_status": mo_status,
        "mo_vendor_info": mo_info,
        "booking_id": booking_id,
        "not_billed": not_billed,
        "enrichment": enrichment or None,
        "issues": issues,
        "notes": notes,
    }


def build_result(p: Pairing, commission: dict, *, prior_sales: dict[str, dict] | None = None,
                 mo_has_booking: bool = False, vendor_supplier: dict | None = None) -> dict:
    """One `payment_reconciliations` row dict, whichever sides exist."""
    v, m = p.vendor, p.mo
    both = v is not None and m is not None
    diffs: list[dict] = []
    issues: list[dict] = []

    for spec in PAYMENT_FIELD_SPECS:
        vv = v.amount(spec.key) if v else None
        mv = m.amount(spec.key) if m else None
        if both:
            # (mo, vendor) → variance = vendor - mo. See the module docstring.
            variance, match, is_issue = _compare(spec, mv, vv)
        else:
            variance, match, is_issue = None, None, False
        if p.possible:
            # Shown for the user to judge, but a suggestion raises no verdict of its own.
            is_issue = False
        diffs.append({
            "key": spec.key, "label": spec.label,
            "vendor": _f(vv), "mo": _f(mv), "variance": _f(variance),
            "match": match, "severity": spec.severity if is_issue else None,
        })
        if is_issue:
            issues.append({
                "field": spec.key, "label": spec.label, "severity": spec.severity,
                "vendor": _f(vv), "mo": _f(mv), "variance": _f(variance),
                "message": (f"{spec.label}: vendor {_money(vv)}, MO {_money(mv)} — "
                            f"difference {_money(variance)}."),
            })

    notes: list[str] = []
    if v:
        notes += v.notes("vendor")
    if m:
        notes += m.notes("MO")

    vendor_net = v.amount("net") if v else None
    mo_net = m.amount("net") if m else None
    net_variance = abs_variance = None

    if p.possible:
        status, severity = STATUS_POSSIBLE, "critical"
        issues.insert(0, {
            "field": "ticket_number", "label": "Ticket number", "severity": "critical",
            "vendor": None, "mo": None, "variance": None,
            "message": (f"Same document serial, different airline: the vendor plates it to "
                        f"{v.ticket_prefix}, the MO statement to {m.ticket_prefix}. A serial "
                        f"is only unique within one airline, so this is a suggestion, not a "
                        f"match — nothing is reconciled from it."),
        })
    elif both:
        status, severity = _status_from_issues(issues)
        if not (vendor_net is None and mo_net is None):
            net_variance = ((vendor_net or ZERO) - (mo_net or ZERO)).quantize(Decimal("0.01"))
            abs_variance = abs(net_variance)
        if p.method == "pnr_pax":
            notes.append("Paired on PNR and passenger name — one of the two statements "
                         "prints no ticket number for it.")
        elif p.method == "other_vendor":
            notes.append("Paired with the ticket in another vendor's MO file so its figures "
                         "can still be compared.")
    elif v:
        status, severity = STATUS_VENDOR_ONLY, "critical"
        abs_variance = abs(vendor_net) if vendor_net is not None else None
        issues.append({
            "field": None, "label": None, "severity": "critical",
            "vendor": None, "mo": None, "variance": None,
            "message": ("Billed on the vendor's statement but not in the MO statement. "
                        "Check it before paying."
                        if v.ticket_key or v.pnr_pax_key else
                        "This vendor row carries no ticket number or PNR, so it cannot be "
                        "matched to anything in the MO statement."),
        })
    else:
        status, severity = STATUS_MO_ONLY, "warning"
        abs_variance = abs(mo_net) if mo_net is not None else None
        issues.append({
            "field": None, "label": None, "severity": "warning",
            "vendor": None, "mo": None, "variance": None,
            "message": ("In the MO statement but not on this vendor statement. It may be "
                        "billed in a later statement."),
        })

    def pick(attr: str):
        return (getattr(v, attr) if v else None) or (getattr(m, attr) if m else None)

    mo_comm = None
    if m:
        parts = [x for x in (m.amount("commission"), m.amount("incentive")) if x is not None]
        mo_comm = sum(parts) if parts else None

    # Steps 6A–6E. Appended AFTER the money verdict, which they never change.
    checks = process_checks(p, prior_sales=prior_sales or {}, mo_has_booking=mo_has_booking,
                            vendor_supplier=vendor_supplier)
    issues.extend(checks.pop("issues"))
    notes.extend(checks.pop("notes"))

    return {
        "ticket_key": (v.key if v else None) or (m.key if m else None),
        **checks,
        "vendor_row_ids": v.row_ids if v else [],
        "mo_row_ids": m.row_ids if m else [],
        "vendor_rows": len(v.rows) if v else 0,
        "mo_rows": len(m.rows) if m else 0,
        "ticket_number": pick("ticket_number"),
        "ticket_prefix": pick("ticket_prefix"),
        "airline_name": pick("airline_name"),
        "airline_code": pick("airline_code"),
        "issue_date": pick("issue_date"),
        "pax_name": pick("pax_name"),
        "sector": pick("sector"),
        "pnr": pick("pnr"),
        "match_status": status,
        "severity": severity,
        "match_method": p.method if both else "none",
        "vendor_gross": _f(v.amount("gross")) if v else None,
        "mo_gross": _f(m.amount("gross")) if m else None,
        "vendor_net": _f(vendor_net),
        "mo_net": _f(mo_net),
        "net_variance": _f(net_variance),
        "abs_net_variance": _f(abs_variance),
        "mo_commission": _f(mo_comm),
        "field_diffs": diffs,
        "issues": issues,
        "notes": notes,
        **commission,
    }


def group_by_upload(rows: list[PayRow]) -> list[TicketGroup]:
    """Group MO rows per upload first — the same ticket in two uploads is two candidates,
    never one ticket with doubled money."""
    by_batch: dict[str | None, list[PayRow]] = {}
    for r in rows:
        by_batch.setdefault((r.origin or {}).get("batch_id"), []).append(r)
    out: list[TicketGroup] = []
    for batch_rows in by_batch.values():
        out.extend(group_rows(batch_rows))
    return out


def reconcile(vendor_rows: list[PayRow], mo_rows: list[PayRow],
              calcs: dict[int, CalcFigure], *, commission_ran: bool,
              prior_sales: dict[str, dict] | None = None,
              other_mo_rows: list[PayRow] | None = None,
              vendor_supplier: dict | None = None) -> list[dict]:
    """The whole answer for one pair, before persistence — every rule above, in order.

    `mo_rows` is the MO pool for this vendor (its MO upload, adjusted by corrections);
    `other_mo_rows` every other vendor's MO rows, searched for this vendor's leftovers;
    `prior_sales` the sale rows of this vendor's earlier uploads, keyed by serial.
    """
    pairings = pair_groups(group_rows(vendor_rows), group_rows(mo_rows))
    # A ticket corrected in from another MO file belongs to this VENDOR, not to this
    # statement: it pairs where the vendor billed it, and is no "in MO, not billed" line on
    # the vendor's other statements.
    pairings = [p for p in pairings if p.vendor is not None or not _corrected_in(p.mo)]
    if other_mo_rows:
        attach_other_vendor(pairings, group_by_upload(other_mo_rows))
    # Per MO upload: a file that prints booking IDs makes a blank one telling; a file that
    # prints none says nothing — and neither speaks for the other.
    booking_uploads = {_upload_of(r.origin) for r in (*mo_rows, *(other_mo_rows or ()))
                       if r.booking_id}
    return [
        build_result(p, commission_for_group(p.vendor, calcs, commission_ran=commission_ran),
                     prior_sales=prior_sales,
                     mo_has_booking=p.mo is not None and _upload_of(p.mo.origin) in booking_uploads,
                     vendor_supplier=vendor_supplier)
        for p in pairings
    ]


def _upload_of(origin: dict | None) -> str | None:
    """The MO upload a row or ticket came from. None for rows built without an origin —
    tests, and pools that are a single upload."""
    return (origin or {}).get("batch_id")


def _corrected_in(g: TicketGroup | None) -> bool:
    return g is not None and (g.origin or {}).get("vendor_status") == MO_VENDOR_CORRECTED


# ── roll-up ──────────────────────────────────────────────────────────────────
def tally(rows: list[dict]) -> dict:
    """Run totals, recomputed from the rows themselves, in Decimal.

    `vendor_net_total` is the whole bill (every vendor ticket, whatever its verdict);
    `net_variance_total` counts only paired rows; a possible match is in neither one-sided
    total, because it is not reconciled and not known to be missing either.
    """
    counts = {s: 0 for s in PAYMENT_RECON_STATUSES}
    sums = {k: ZERO for k in ("vendor_net", "mo_net", "net_variance", "vendor_only",
                              "mo_only", "calc", "vendor_comm", "shortfall", "payable")}
    for r in rows:
        st = r["match_status"]
        counts[st] = counts.get(st, 0) + 1
        vn, mn = _d(r.get("vendor_net")), _d(r.get("mo_net"))
        if r.get("vendor_row_ids"):
            sums["vendor_net"] += vn or ZERO
        if r.get("mo_row_ids"):
            sums["mo_net"] += mn or ZERO
        if st in PAIRED_STATUSES:
            sums["net_variance"] += _d(r.get("net_variance")) or ZERO
        elif st == STATUS_VENDOR_ONLY:
            sums["vendor_only"] += vn or ZERO
        elif st == STATUS_MO_ONLY:
            sums["mo_only"] += mn or ZERO
        sums["calc"] += _d(r.get("calc_commission")) or ZERO
        sums["vendor_comm"] += _d(r.get("vendor_commission")) or ZERO
        sums["shortfall"] += _d(r.get("commission_shortfall")) or ZERO
        sums["payable"] += _d(r.get("payable_after_commission")) or ZERO
    flags = {
        "duplicates": sum(1 for r in rows if r.get("is_duplicate")),
        "not_billed": sum(1 for r in rows if r.get("not_billed")),
        "other_vendor": sum(1 for r in rows if r.get("mo_vendor_status") == MO_VENDOR_OTHER),
        "corrected": sum(1 for r in rows if r.get("mo_vendor_status") == MO_VENDOR_CORRECTED),
        "enriched": sum(1 for r in rows if r.get("enrichment")),
    }
    return {"counts": counts, "flags": flags, **{k: _f(v) for k, v in sums.items()}}


def split_rows(rows) -> tuple[list[PayRow], list[dict]]:
    """`[(row_id, data), …]` in file order → (ticket rows, balance lines)."""
    tickets: list[PayRow] = []
    lines: list[dict] = []
    for rid, data in rows:
        kind = balance_kind(data)
        if kind is not None:
            raw = to_decimal((data or {}).get("net_amount"))
            # `amount` is for display; `raw` (a string, so it survives JSONB) is what the
            # derived opening is computed from — see balance_figures.
            lines.append({"kind": kind[0], "label": kind[1], "row_id": rid,
                          "amount": _f(raw), "raw": str(raw) if raw is not None else None})
            continue
        tickets.append(build_pay_row(rid, data))
    return tickets, lines


def exact_net(rows: list[PayRow]) -> Decimal:
    """Σ net over a side's ticket rows, unrounded — the statement's own arithmetic."""
    return sum((r.amounts["net"] for r in rows if r.amounts.get("net") is not None), ZERO)


def balance_figures(lines: list[dict], ticket_net_total: Decimal) -> dict:
    """Opening/closing balance from a side's balance lines.

    The closing balance is the statement's own last BALANCE line, and the payments its
    LESS PAYMENT lines. The opening is printed only when the file kept its OLD line as a
    row — ingest normally drops it with the preamble — so otherwise it is DERIVED from how
    the statement itself is built: opening + Σ net − payments = closing.

    Pass the UNROUNDED net (`exact_net`) and every figure stays unrounded until the end:
    a statement carrying -28267.7162 drifts a paisa if each ticket is rounded first, and
    the derived opening would then disagree with the OLD line the vendor printed.
    """
    fig = statement_balance.account_figures(
        (ln["kind"], ln.get("raw") if ln.get("raw") is not None else ln.get("amount"))
        for ln in lines)
    opening, closing, payments = fig["opening"], fig["closing"], fig["payments"]
    derived = False
    if opening is None and closing is not None:
        opening, derived = closing - ticket_net_total + (payments or ZERO), True
    return {"closing": _f(closing), "opening": _f(opening), "opening_derived": derived,
            "payments": _f(payments)}


# ── the service ──────────────────────────────────────────────────────────────
@dataclass
class PaymentRunSummary:
    run_id: int
    reconciled_at: datetime
    total: int
    counts: dict
    totals: dict
    vendor_closing_balance: float | None
    mo_closing_balance: float | None


class StatementNotFound(LookupError):
    """The vendor or MO upload is not one of this user's."""


class PaymentReconciliationService:
    """Recompute one (vendor upload, MO upload) pair, wholesale and idempotently."""

    @staticmethod
    async def upload_file(db: AsyncSession, slug: str, tenant_id: int, user_id: int,
                          batch_id: str) -> tuple[bool, str | None]:
        """(exists, source_file) for one upload of this user."""
        m = STATEMENT_MODELS[slug]
        row = (await db.execute(
            select(func.count(), func.max(m.source_file))
            .where(m.tenant_id == tenant_id, m.created_by_id == user_id,
                   m.batch_id == batch_id)
        )).one()
        return (row[0] or 0) > 0, row[1]

    @staticmethod
    async def load_side(db: AsyncSession, slug: str, tenant_id: int, user_id: int,
                        batch_id: str) -> tuple[list[PayRow], list[dict]]:
        """(ticket rows, balance lines) of one upload, in file order."""
        m = STATEMENT_MODELS[slug]
        rows = (await db.execute(
            select(m.id, m.data)
            .where(m.tenant_id == tenant_id, m.created_by_id == user_id,
                   m.batch_id == batch_id)
            .order_by(m.id.asc())
        )).all()
        return split_rows(rows)

    @staticmethod
    async def suppliers_for(db: AsyncSession, slug: str, tenant_id: int,
                            batch_ids) -> dict[str, StatementBatchSupplier]:
        ids = list(batch_ids)
        if not ids:
            return {}
        rows = (await db.execute(select(StatementBatchSupplier).where(
            StatementBatchSupplier.slug == slug, StatementBatchSupplier.tenant_id == tenant_id,
            StatementBatchSupplier.batch_id.in_(ids)))).scalars().all()
        return {r.batch_id: r for r in rows}

    @classmethod
    async def load_context(cls, db: AsyncSession, tenant_id: int, user_id: int,
                           vendor_batch_id: str, mo_batch_id: str) -> dict:
        """Everything beyond the two uploads that steps 6A and 6C need.

        `pool`        the MO tickets this vendor's statement is reconciled against: the
                      chosen MO upload, minus tickets corrected away to another vendor, plus
                      tickets from other MO uploads corrected TO this vendor.
        `mo_own`      the chosen MO upload's own tickets (its balance arithmetic).
        `other_mo`    every other vendor's MO tickets, for the wrong-vendor lookup. The same
                      vendor's other MO uploads are left out: another period's file of the
                      right vendor is not a mis-mapping.
        `prior_sales` sale rows of this vendor's EARLIER uploads, keyed by serial — the
                      duplicate check — with whether that earlier ticket has been paid.
        """
        V, M = STATEMENT_MODELS[VENDOR_SLUG], STATEMENT_MODELS[MO_SLUG]
        v_link = (await cls.suppliers_for(db, VENDOR_SLUG, tenant_id, [vendor_batch_id])
                  ).get(vendor_batch_id)
        supplier_id = v_link.supplier_id if v_link else None
        vendor_supplier = ({"supplier_id": v_link.supplier_id, "supplier_name": v_link.supplier_name,
                            "supplier_code": v_link.supplier_code} if v_link else None)
        vendor_uploaded_at = await db.scalar(select(func.max(V.uploaded_at)).where(
            V.tenant_id == tenant_id, V.created_by_id == user_id, V.batch_id == vendor_batch_id))

        # ── MO side ──────────────────────────────────────────────────────────
        mo_rows = (await db.execute(
            select(M.id, M.batch_id, M.source_file, M.data)
            .where(M.tenant_id == tenant_id, M.created_by_id == user_id)
            .order_by(M.id.asc())
        )).all()
        links = await cls.suppliers_for(db, MO_SLUG, tenant_id, {b for _i, b, _sf, _d in mo_rows})
        corr = {(c.mo_batch_id, c.ticket_key): c for c in (await db.execute(
            select(MoVendorCorrection).where(MoVendorCorrection.tenant_id == tenant_id,
                                             MoVendorCorrection.created_by_id == user_id)
        )).scalars().all()}

        own_raw = [(rid, data) for rid, b, _sf, data in mo_rows if b == mo_batch_id]
        mo_own, mo_lines = split_rows(own_raw)
        own_ids = {r.row_id for r in mo_own}

        pool: list[PayRow] = []
        other: list[PayRow] = []
        for rid, batch, source_file, data in mo_rows:
            if statement_balance.is_balance_row(data):
                continue
            link = links.get(batch)
            row = build_pay_row(rid, data)
            gkey = (f"k:{row.ticket_key}" if row.ticket_key
                    else f"p:{row.pnr_pax_key}" if row.pnr_pax_key else f"r:{rid}")
            c = corr.get((batch, gkey))
            upload_supplier = link.supplier_id if link else None
            upload_name = link.supplier_name if link else None
            effective = c.to_supplier_id if c else upload_supplier
            row.origin = {
                "batch_id": batch, "source_file": source_file,
                "supplier_id": effective,
                "supplier_name": (c.to_supplier_name if c else upload_name),
                "vendor_status": MO_VENDOR_OK,
            }
            if batch == mo_batch_id and rid in own_ids:
                if c is not None and c.to_supplier_id != supplier_id:
                    other.append(row)          # corrected away: another vendor's ticket now
                else:
                    pool.append(row)
            elif c is not None and supplier_id is not None and c.to_supplier_id == supplier_id:
                row.origin.update(vendor_status=MO_VENDOR_CORRECTED, corrected_from=upload_name)
                pool.append(row)
            elif effective is not None and effective == supplier_id:
                continue                       # the same vendor's other MO upload
            else:
                other.append(row)

        # ── earlier sales of this vendor (step 6A) ───────────────────────────
        prior: dict[str, dict] = {}
        if supplier_id is not None and vendor_uploaded_at is not None:
            same_vendor = [l.batch_id for l in (await db.execute(
                select(StatementBatchSupplier).where(
                    StatementBatchSupplier.slug == VENDOR_SLUG,
                    StatementBatchSupplier.tenant_id == tenant_id,
                    StatementBatchSupplier.supplier_id == supplier_id)
            )).scalars().all() if l.batch_id != vendor_batch_id]
            if same_vendor:
                earlier = (await db.execute(
                    select(V.id, V.batch_id, V.source_file, V.uploaded_at, V.data)
                    .where(V.tenant_id == tenant_id, V.created_by_id == user_id,
                           V.batch_id.in_(same_vendor), V.uploaded_at < vendor_uploaded_at)
                    .order_by(V.uploaded_at.asc(), V.id.asc())
                )).all()
                paid = {(b, k) for b, k in (await db.execute(
                    select(PaymentItem.vendor_batch_id, PaymentItem.ticket_key).where(
                        PaymentItem.tenant_id == tenant_id,
                        PaymentItem.created_by_id == user_id,
                        PaymentItem.vendor_batch_id.in_(same_vendor),
                        PaymentItem.payment_id.isnot(None))
                )).all()}
                for rid, batch, source_file, uploaded_at, data in earlier:
                    if statement_balance.is_balance_row(data):
                        continue
                    row = build_pay_row(rid, data)
                    if not row.ticket_key or row.kind != KIND_SALE:
                        continue
                    prior.setdefault(row.ticket_key, {
                        "batch_id": batch, "source_file": source_file,
                        "uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
                        "prefix": row.ticket_prefix,
                        "paid": (batch, f"k:{row.ticket_key}") in paid,
                    })

        return {
            "vendor_supplier": vendor_supplier, "vendor_uploaded_at": vendor_uploaded_at,
            "pool": pool, "mo_own": mo_own, "mo_lines": mo_lines, "other_mo": other,
            "prior_sales": prior,
        }

    @staticmethod
    async def load_commission(db: AsyncSession, tenant_id: int, user_id: int,
                              batch_id: str) -> tuple[dict[int, CalcFigure], CommissionRun | None]:
        """Commission income's current figures for the vendor upload, by statement row id."""
        C = CommissionCalculation
        rows = (await db.execute(
            select(C.source_row_id, C.status, C.reason, C.incentive, C.iata_commission,
                   C.variance_total, C.declared_net_ok, C.matched_deal_no,
                   C.matched_deal_name)
            .where(C.tenant_id == tenant_id, C.created_by_id == user_id,
                   C.source == SOURCE_TP_GDS, C.batch_id == batch_id)
        )).all()
        calcs = {
            r.source_row_id: CalcFigure(
                status=r.status, reason=r.reason,
                incentive=_d(r.incentive), iata=_d(r.iata_commission),
                variance_total=_d(r.variance_total), net_ok=r.declared_net_ok,
                deal_no=r.matched_deal_no, deal_name=r.matched_deal_name,
            )
            for r in rows
        }
        run = await latest_commission_run(db, tenant_id, user_id, batch_id)
        return calcs, run

    @classmethod
    async def run(cls, db: AsyncSession, *, tenant_id: int, created_by_id: int,
                  vendor_batch_id: str, mo_batch_id: str) -> PaymentRunSummary:
        v_ok, v_file = await cls.upload_file(db, VENDOR_SLUG, tenant_id, created_by_id,
                                             vendor_batch_id)
        if not v_ok:
            raise StatementNotFound("Vendor statement not found.")
        m_ok, m_file = await cls.upload_file(db, MO_SLUG, tenant_id, created_by_id,
                                             mo_batch_id)
        if not m_ok:
            raise StatementNotFound("MO statement not found.")

        started = datetime.utcnow()
        run = PaymentReconciliationRun(
            tenant_id=tenant_id, created_by_id=created_by_id,
            vendor_batch_id=vendor_batch_id, mo_batch_id=mo_batch_id,
            engine_version=ENGINE_VERSION, status="processing", started_at=started,
        )
        db.add(run)
        await db.flush()

        v_rows, v_lines = await cls.load_side(db, VENDOR_SLUG, tenant_id, created_by_id,
                                              vendor_batch_id)
        ctx = await cls.load_context(db, tenant_id, created_by_id, vendor_batch_id, mo_batch_id)
        m_rows, m_lines = ctx["mo_own"], ctx["mo_lines"]
        calcs, comm_run = await cls.load_commission(db, tenant_id, created_by_id,
                                                    vendor_batch_id)
        commission_ran = bool(calcs) or comm_run is not None

        out = reconcile(v_rows, ctx["pool"], calcs, commission_ran=commission_ran,
                        prior_sales=ctx["prior_sales"], other_mo_rows=ctx["other_mo"],
                        vendor_supplier=ctx["vendor_supplier"])

        now = datetime.utcnow()
        for r in out:
            r.update(run_id=run.id, tenant_id=tenant_id, created_by_id=created_by_id,
                     vendor_batch_id=vendor_batch_id, mo_batch_id=mo_batch_id,
                     reconciled_at=now, created_at=now)

        # Wholesale recompute, SCOPED TO THE PAIR — another pair's answer is untouched.
        await db.execute(delete(PaymentReconciliation).where(
            PaymentReconciliation.tenant_id == tenant_id,
            PaymentReconciliation.created_by_id == created_by_id,
            PaymentReconciliation.vendor_batch_id == vendor_batch_id,
            PaymentReconciliation.mo_batch_id == mo_batch_id,
        ))
        if out:
            db.add_all([PaymentReconciliation(**r) for r in out])
        await db.flush()

        t = tally(out)
        counts = t["counts"]
        v_bal = balance_figures(v_lines, exact_net(v_rows))
        m_bal = balance_figures(m_lines, exact_net(m_rows))
        priced_rows = sum(1 for c in calcs.values() if c.status in MATCHED_STATUSES)

        run.status = "completed"
        run.completed_at = now
        run.total_rows = len(out)
        run.matched_rows = counts[STATUS_MATCHED]
        run.minor_diff_rows = counts[STATUS_MINOR_DIFF]
        run.mismatch_rows = counts[STATUS_MISMATCH]
        run.possible_match_rows = counts[STATUS_POSSIBLE]
        run.vendor_only_rows = counts[STATUS_VENDOR_ONLY]
        run.mo_only_rows = counts[STATUS_MO_ONLY]
        run.vendor_net_total = t["vendor_net"]
        run.mo_net_total = t["mo_net"]
        run.net_variance_total = t["net_variance"]
        run.vendor_only_total = t["vendor_only"]
        run.mo_only_total = t["mo_only"]
        run.calc_commission_total = t["calc"]
        run.vendor_commission_total = t["vendor_comm"]
        run.shortfall_total = t["shortfall"]
        run.payable_total = t["payable"]
        run.vendor_closing_balance = v_bal["closing"]
        run.mo_closing_balance = m_bal["closing"]
        run.commission_run_id = comm_run.id if comm_run else None
        run.commission_completed_at = comm_run.completed_at if comm_run else None
        run.commission_priced_rows = priced_rows
        run.commission_unpriced_rows = sum(
            1 for r in v_rows
            if (c := calcs.get(r.row_id)) is None
            or (c.status not in MATCHED_STATUSES and c.status != "skipped"))
        run.params = {
            "vendor_slug": VENDOR_SLUG, "mo_slug": MO_SLUG,
            "vendor_source_file": v_file, "mo_source_file": m_file,
            "vendor_ticket_rows": len(v_rows), "mo_ticket_rows": len(m_rows),
            "vendor_balance_lines": v_lines, "mo_balance_lines": m_lines,
            "vendor_balance": v_bal, "mo_balance": m_bal,
            "flags": t["flags"], "vendor_supplier": ctx["vendor_supplier"],
            "commission_ran": commission_ran,
        }

        # Step 10 onwards: every billed ticket gets (or keeps) its payment item. The decision
        # and payment fields on an existing item survive; only the snapshot is refreshed.
        from app.services import payment_ledger
        await payment_ledger.sync_items(
            db, tenant_id=tenant_id, user_id=created_by_id, vendor_batch_id=vendor_batch_id,
            mo_batch_id=mo_batch_id, vendor_supplier=ctx["vendor_supplier"],
            vendor_file=v_file, vendor_uploaded_at=ctx["vendor_uploaded_at"],
            results=out, commission_ran=commission_ran, now=now)
        await db.commit()

        return PaymentRunSummary(
            run_id=run.id, reconciled_at=now, total=len(out), counts=counts,
            totals={k: t[k] for k in ("vendor_net", "mo_net", "net_variance", "vendor_only",
                                      "mo_only", "calc", "vendor_comm", "shortfall",
                                      "payable")},
            vendor_closing_balance=v_bal["closing"], mo_closing_balance=m_bal["closing"],
        )


async def latest_commission_run(db: AsyncSession, tenant_id: int, user_id: int,
                                batch_id: str) -> CommissionRun | None:
    """The most recent Commission income run on this vendor upload, if any."""
    return (await db.execute(
        select(CommissionRun)
        .where(CommissionRun.tenant_id == tenant_id,
               CommissionRun.created_by_id == user_id,
               CommissionRun.source == SOURCE_TP_GDS,
               CommissionRun.batch_id == batch_id)
        .order_by(CommissionRun.started_at.desc().nullslast(), CommissionRun.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def latest_run(db: AsyncSession, tenant_id: int, user_id: int, vendor_batch_id: str,
                     mo_batch_id: str) -> PaymentReconciliationRun | None:
    """The most recent completed reconciliation of this pair."""
    R = PaymentReconciliationRun
    return (await db.execute(
        select(R)
        .where(R.tenant_id == tenant_id, R.created_by_id == user_id,
               R.vendor_batch_id == vendor_batch_id, R.mo_batch_id == mo_batch_id,
               R.status == "completed")
        .order_by(R.completed_at.desc().nullslast(), R.id.desc())
        .limit(1)
    )).scalar_one_or_none()
