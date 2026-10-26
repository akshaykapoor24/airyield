"""Vendor ↔ Internal reconciliation: a consolidator's statement against our own.

The vendor side is a Third Party GDS statement (third_party_gds — e.g. Globe's
weekly "TRIUMPHH BSP STATEMENT"), the internal side is Internal Statement
(internal_uploaded_tickets — e.g. "GLOBE OUR …", or tickets punched in Create
Ticket). Both describe the same tickets; this lines them up and says where, and
why, they disagree — vendor by vendor, statement by statement.

WHICH VENDOR. Every line belongs to a vendor of Agency Master (User master → Agency Master):
    vendor     the Agency Master row its statement was uploaded under
               (statement_batch_suppliers.agency_id)
    internal   the ticket's Payable To when it names a B2B vendor (Create Ticket), else the
               B2B agency it was filed under — Internal Statement's "who were these tickets
               sold to", which is where a vendor's own monthly statement is filed
Agency Master keeps one row per branch per channel; rows with the same name and branch are ONE
vendor here (`Vendor`), so a vendor onboarded on GDS and on LCC is one choice in the filter.

MATCHING IS ACROSS EVERY VENDOR; the filters only narrow what is shown. A ticket number is the
airline's and unique, so a line is paired wherever its partner is — a ticket billed by Lords but
booked under Globe in your books is matched, and says so — and choosing one weekly statement
never turns the other weeks' tickets into "only in your books".

WHAT IS MATCHED. One LINE against one line: a SALE with a sale, a REFUND with a
refund, of the same ticket. A ticket sold and refunded is two pairs, never one —
netting them would hide a wrong refund behind a right sale.

THE KEY IS THE DOCUMENT SERIAL ALONE. Both sides already store the 3-digit airline
code apart from the serial, but the vendor parser does not always read that code
right (5808758877 arrives as "75" on one side and "125" on the other), so a code
mismatch is reported as a hint, never allowed to break a match.

SALE OR REFUND, per side, from every signal that side has — a single field is not
enough on either:
    vendor     ticket_status CANCELLED, or a negative net
    internal   invoice type Credit Note / Refund, an "IR…" Doc No, or a negative
               invoice amount (an uploaded refund line is not always typed)

WHAT IS COMPARED — the figures both statements print, mapped onto each other:
    Fare + taxes   vendor total_fare                 internal basic + every tax column
                   (the two split basic from tax differently — 33,465 + 21,604 on
                   one, 36,045 + 19,017 on the other, for the same 55,069 / 55,062 —
                   so only the total is comparable)
    Commission     vendor commission_amount          internal Discount (dis_sell)
    Charges        vendor service_fee + cancellation internal Serv. Chrgs 1–3 + RAF
                   markup                            (RAF on a refund = the vendor's
                                                     markup plus its service fee)
    GST            vendor gst_on_sf                  internal GST (one figure or heads)
    TDS            vendor tds                        internal TDS
    Net            vendor net_amount                 internal Invoice Amt (total_amt)
The internal net is rounded to the rupee (the statement's BillAmount is), so a net
within ROUND_TOLERANCE is a match, not a difference.

THE EIGHT CASES — the reconciling items between "billed as per vendor" and "as per your books",
each an amount of books − vendor (negative: LESS — the vendor's figure is higher; positive: ADD):
    1 extra_fare         a sale billed higher than your books (fare, taxes, charges, GST)
    2 less_fare          a sale billed lower
    3 extra_refund       a refund credited lower — higher cancellation / refund charges
    4 less_refund        a refund credited higher
    5 extra_commission   the vendor passed on less commission (or took more back on a refund)
    6 less_commission    the vendor passed on more commission
    7 vendor_only        billed by the vendor, not in your books
    8 internal_only      in your books, not billed by the vendor
A line whose net differs is split in two: its commission part — commission net of TDS, worked
out per side with the sign it moves that side's net (a vendor prints a refund's commission
reversal either way round: −155.88 on one line, +135.30 on the next) — and the rest, which is
its fare or refund part. Both are taken off the printed nets, so they add up to the line's net
difference exactly, whatever a statement's own columns add up to (a vendor line's columns do not
always reach its net). A sold-and-refunded ticket compared whole is a refund here.

HINTS. Every row that is not a clean match says why in words — which figure moved
and by how much, a code or name that disagrees, a period the other side does not
cover, a likely partner when the ticket number itself finds nothing, a ticket billed
twice, a ticket booked under another vendor, or (for a ticket sold and refunded on
one side and booked once on the other) both tickets' net side by side.

THE FOUR STATUSES, and what each asks of the user:
    matched        settled — nothing to look at again when the next statement loads
    difference     on both, figures disagree — the user RESOLVES it: the GDS statement
                   is wrong, the internal statement is wrong, or the difference is accepted
    vendor_only    on the GDS statement only — carried forward, re-checked against every
                   internal statement loaded after it
    internal_only  on the internal statement only — carried forward the same way
Carrying forward needs no state: every load reconciles everything loaded, so a line
waiting for its partner meets it the moment that statement arrives. `pending` says
whether it is still EXPECTED there (dated after everything the other side has loaded
for its vendor) or already MISSING (the other side's statements cover its date).

THE BALANCE. A Third Party GDS statement is a running account — opening + Σ net − payments =
closing (statement_batch_controls). For one vendor, the balance payable as per the vendor is a
statement's closing balance, as at the end of its period; the balance as per your books is that
figure with every reconciling item of the vendor dated from its first statement up to then. The
opening balance and the payments are taken as agreed — what reconciling a statement against its
predecessor's closing means.

LINES LEFT OUT AT UPLOAD. A statement's file can carry lines an earlier statement already
saved; its upload leaves them out (services/tp_gds_reupload.py) and keeps them apart
(models/statement_row.ThirdPartyGdsLeftOut). They are shown with their own statement — the
"already_uploaded" view — each beside the row of the line it repeats, which is where it is
reconciled: matched with your books, resolved, or still open. They are never matched and never
counted, or a ticket billed once would be reconciled twice. Only a statement's balance counts
them, in what its file billed — its printed closing does.

RESOLUTIONS are the only thing stored (models/vendor_internal_recon.py), keyed by
ticket text so a re-upload keeps them, and checked against the figures they were taken
on so a corrected statement reopens them.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agency import Agency
from app.models.internal_ticket import InternalTicketStatement, InternalUploadedTicket
from app.models.statement_batch_control import StatementBatchControl
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import ThirdPartyGds, ThirdPartyGdsLeftOut
from app.models.third_party_statement import ThirdPartyStatement
from app.models.vendor_internal_recon import VendorInternalResolution
from app.services.tp_gds_reupload import DIFF_FIELDS

ROUND_TOLERANCE = 1.0     # rupees — the internal net is rounded to the rupee
FIELD_TOLERANCE = 0.5     # rupees — below this a component is "the same"

MATCHED = "matched"
DIFFERENCE = "difference"
VENDOR_ONLY = "vendor_only"
INTERNAL_ONLY = "internal_only"

SALE = "sale"
REFUND = "refund"

# A one-sided line's outlook, against the dates the OTHER side has loaded.
NEXT_STATEMENT = "next_statement"   # dated after all of them — expected in its next statement
IN_PERIOD = "in_period"             # they cover its date, and it is not there

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")

COMPARED = ("fare", "commission", "charges", "gst", "tds", "net")
LABEL = {
    "fare": "Fare + taxes", "commission": "Commission / discount", "charges": "Charges",
    "gst": "GST", "tds": "TDS", "net": "Net",
}

_NON_TICKET_KINDS = {"total", "payment", "closing", "opening", "balance"}
_TP_GDS = "tp-gds"


# ── the eight cases ──────────────────────────────────────────────────────────
EXTRA_FARE = "extra_fare"
LESS_FARE = "less_fare"
EXTRA_REFUND = "extra_refund"
LESS_REFUND = "less_refund"
EXTRA_COMMISSION = "extra_commission"
LESS_COMMISSION = "less_commission"


@dataclass(frozen=True)
class Case:
    id: str
    n: int
    label: str
    what: str


CASES: tuple[Case, ...] = (
    Case(EXTRA_FARE, 1, "Extra fare charged by vendor",
         "On a sale the vendor billed more than your books — fare, taxes, service charges or GST."),
    Case(LESS_FARE, 2, "Less fare charged by vendor",
         "On a sale the vendor billed less than your books."),
    Case(EXTRA_REFUND, 3, "Extra refund charges by vendor",
         "On a refund the vendor credited less than your books — higher cancellation or refund charges."),
    Case(LESS_REFUND, 4, "Less refund charges by vendor",
         "On a refund the vendor credited more than your books."),
    Case(EXTRA_COMMISSION, 5, "Extra commission charged by vendor",
         "The vendor passed on less commission than your books (or took more back on a refund), so it bills more."),
    Case(LESS_COMMISSION, 6, "Less commission charged by vendor",
         "The vendor passed on more commission than your books, so it bills less."),
    Case(VENDOR_ONLY, 7, "In vendor statement, not in your books",
         "Billed by the vendor and not in Internal Statement — booked late, missed, or not yours."),
    Case(INTERNAL_ONLY, 8, "In your books, not in vendor statement",
         "In Internal Statement and not billed by the vendor — billed late, missed, or booked in error."),
)
CASE_IDS: tuple[str, ...] = tuple(c.id for c in CASES)
# The lines of the statements' files left out at upload as repeats of saved lines (`Repeat`).
ALREADY_UPLOADED = "already_uploaded"
# What the view can be asked for besides one case.
# Every line that is not matched — open or resolved: "all" is "matched" and this together.
UNMATCHED = "unmatched"
VIEWS: tuple[str, ...] = ("summary", "all", MATCHED, UNMATCHED, "resolved", ALREADY_UPLOADED, *CASE_IDS)


def _f(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0.0


def _serial(v: Any) -> Optional[str]:
    """The document serial, digits only — what both sides store the ticket as."""
    if v is None:
        return None
    s = re.sub(r"[^0-9A-Za-z]", "", str(v))
    return s.lstrip("0") or None


def _code(v: Any) -> Optional[str]:
    s = re.sub(r"\D", "", str(v or ""))
    return s.lstrip("0") or None


def _surname(name: Optional[str]) -> str:
    """A comparable token from either side's spelling of a passenger."""
    n = re.sub(r"\b(MR|MRS|MS|MISS|MSTR|DR|INF|CHD)\b\.?", " ", (name or "").upper())
    parts = [p for p in re.split(r"[^A-Z]+", n) if len(p) > 1]
    return " ".join(sorted(parts))


def _route(sector: Optional[str]) -> str:
    codes = [c for c in re.split(r"[^A-Z]+", (sector or "").upper()) if len(c) == 3]
    out: list[str] = []
    for c in codes:
        if not out or out[-1] != c:
            out.append(c)
    return "/".join(out)


def _day(v: Any) -> Optional[str]:
    """A date as YYYY-MM-DD, or None when it is not one."""
    if v is None:
        return None
    s = v.isoformat() if isinstance(v, (date, datetime)) else str(v)
    s = s.strip()[:10]
    return s if _ISO.fullmatch(s) else None


@dataclass
class Line:
    side: str                      # "vendor" | "internal"
    id: int
    serial: Optional[str]
    code: Optional[str]
    kind: str
    pax: Optional[str]
    pnr: Optional[str]
    sector: str
    date: Optional[str]
    ref: Optional[str]             # vendor: the week / file; internal: Doc No
    source: Optional[str]
    amounts: dict[str, float] = field(default_factory=dict)
    loaded_at: Optional[str] = None    # when its statement was uploaded — "waiting since"
    booked: Optional[str] = None       # the booking date — what the period filter reads
    vendor_key: Optional[str] = None   # the Vendor it belongs to (see the module docstring)
    batches: list[str] = field(default_factory=list)   # the statement(s) it comes from
    n_lines: int = 1                   # >1 for a ticket's lines summed into one (netted)
    line_ids: list[int] = field(default_factory=list)  # the stored line(s) it is — every one, netted

    def public(self) -> dict:
        return {
            "id": self.id, "ticket_prefix": self.code, "pax": self.pax, "pnr": self.pnr,
            "sector": self.sector, "date": self.date, "booked": self.booked, "ref": self.ref,
            "source": self.source, "loaded_at": self.loaded_at, "vendor_key": self.vendor_key,
            "statements": list(self.batches), "lines": self.n_lines, "line_ids": list(self.line_ids),
            **{k: round(v, 2) for k, v in self.amounts.items()},
        }


def _iso(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v else None


def _vendor_commission(kind: str, commission: float, tds: float) -> float:
    """What commission net of TDS does to a vendor line's net. A sale's commission comes off;
    a refund's is taken back — added — whichever sign the vendor printed it with."""
    return (abs(commission) if kind == REFUND else -abs(commission)) + tds


def _vendor_line(row: ThirdPartyGds | ThirdPartyGdsLeftOut, source_file: Optional[str] = None,
                 uploaded_at: Optional[datetime] = None, vendor_key: Optional[str] = None) -> Optional[Line]:
    """`source_file` / `uploaded_at` are the statement's own (models/third_party_statement.py);
    the line's copies of them are the fallback — a left-out line has none."""
    d = row.data or {}
    if (d.get("row_kind") or "").lower() in _NON_TICKET_KINDS or not d.get("ticket_number"):
        return None
    net = _f(d.get("net_amount"))
    refund = (d.get("ticket_status") or "").upper() == "CANCELLED" or net < 0
    kind = REFUND if refund else SALE
    commission, tds = _f(d.get("commission_amount")), _f(d.get("tds"))
    return Line(
        side="vendor", id=row.id, serial=_serial(d.get("ticket_number")), code=_code(d.get("ticket_prefix")),
        kind=kind,
        pax=d.get("passenger_name") or d.get("first_name"), pnr=d.get("airline_pnr"),
        sector=_route(d.get("sector")), date=d.get("issue_date"),
        ref=d.get("week"), source=source_file or getattr(row, "source_file", None),
        loaded_at=_iso(uploaded_at or getattr(row, "uploaded_at", None)),
        booked=_day(d.get("booking_date")) or _day(d.get("issue_date")),
        vendor_key=vendor_key, batches=[row.batch_id] if row.batch_id else [], line_ids=[row.id],
        amounts={
            "fare": _f(d.get("total_fare")),
            "commission": commission,
            "charges": _f(d.get("service_fee")) + _f(d.get("cancellation_markup")),
            "gst": _f(d.get("gst_on_sf")),
            "tds": tds,
            "net": net,
            "commission_net": _vendor_commission(kind, commission, tds),
        },
    )


def books_agency(t: InternalUploadedTicket, statement: Optional[InternalTicketStatement] = None) -> Optional[int]:
    """The Agency Master row an internal ticket is booked under: its Payable To when that is a
    B2B vendor, else the B2B agency it — or its statement — was filed under."""
    if (t.payable_type or "") == "b2b" and t.payable_agency_id is not None:
        return t.payable_agency_id
    if (t.customer_type or "") == "agency" and t.customer_agency_id is not None:
        return t.customer_agency_id
    if statement is not None and (statement.customer_type or "") == "agency":
        return statement.customer_agency_id
    return None


def _internal_line(t: InternalUploadedTicket, statement_file: Optional[str],
                   loaded_at: Optional[datetime] = None, vendor_key: Optional[str] = None) -> Line:
    fare = sum(_f(getattr(t, c)) for c in
               ("sell_fare", "sell_tax_yq", "sale_yr", "sale_k3", "oc_tax", "other_tax", "wo_tax"))
    gst = _f(t.gst_sell) or (_f(t.cgst_sell) + _f(t.sgst_sell) + _f(t.igst_sell))
    net = _f(t.total_amt)
    refund = (
        (t.invoice_type or "") in ("Credit Note", "Refund")
        or (t.doc_no or "").strip().upper().startswith("IR")
        or net < 0
    )
    commission, tds = _f(t.dis_sell), _f(t.tds_sell)
    return Line(
        side="internal", id=t.id, serial=_serial(t.ticket_number), code=_code(t.ticket_prefix),
        kind=REFUND if refund else SALE,
        pax=t.pax_name or " ".join(x for x in (t.last_name, t.first_name) if x) or None,
        pnr=t.gds_pnr or t.air_pnr, sector=_route(t.sector),
        date=t.doc_date or t.ticket_date,
        ref=re.sub(r"\s+", " ", t.doc_no) if t.doc_no else None,
        source=statement_file, loaded_at=_iso(loaded_at),
        booked=_day(t.ticket_date) or _day(t.doc_date),
        vendor_key=vendor_key, batches=[t.batch_id] if t.batch_id else [], line_ids=[t.id],
        amounts={
            "fare": fare,
            "commission": commission,
            "charges": _f(t.serv_charge) + _f(t.serv_charge_2) + _f(t.serv_charge_3) + _f(t.raf),
            "gst": gst,
            "tds": tds,
            "net": net,
            # The books' own net is fare − discount + TDS + charges + GST, line for line.
            "commission_net": -commission + tds,
        },
    )


def _inr(v: float) -> str:
    return f"{v:,.2f}"


def _compare(v: Line, i: Line) -> tuple[str, dict[str, float], list[str]]:
    diffs = {k: round(i.amounts[k] - v.amounts[k], 2) for k in COMPARED}
    hints: list[str] = []
    for k in COMPARED[:-1]:
        if abs(diffs[k]) >= FIELD_TOLERANCE:
            hints.append(f"{LABEL[k]} differs by {_inr(diffs[k])} "
                         f"(vendor {_inr(v.amounts[k])} · internal {_inr(i.amounts[k])})")
    net_d = diffs["net"]
    if abs(net_d) < ROUND_TOLERANCE:
        status = MATCHED
        if abs(net_d) >= 0.005 and not any("differs" in h for h in hints):
            hints.append(f"Round-off only ({_inr(net_d)}) — the internal invoice is rounded to the rupee")
    else:
        status = DIFFERENCE
        if not hints:
            hints.append(f"Net differs by {_inr(net_d)} with no single figure explaining it")
    if v.code and i.code and v.code != i.code:
        hints.append(f"Airline code differs — vendor {v.code}, internal {i.code}")
    if v.pax and i.pax and _surname(v.pax) and _surname(i.pax):
        a, b = set(_surname(v.pax).split()), set(_surname(i.pax).split())
        if not (a & b):
            hints.append(f"Passenger differs — vendor “{v.pax}”, internal “{i.pax}”")
    return status, diffs, hints


def _pair(vs: list[Line], is_: list[Line]) -> tuple[list[tuple[Line, Line]], list[Line], list[Line]]:
    """Pair lines sharing a key, closest net first. Leftovers stay unmatched."""
    pairs: list[tuple[Line, Line]] = []
    vs, is_ = list(vs), list(is_)
    while vs and is_:
        v, i = min(((v, i) for v in vs for i in is_),
                   key=lambda p: abs(p[0].amounts["net"] - p[1].amounts["net"]))
        pairs.append((v, i))
        vs.remove(v)
        is_.remove(i)
    return pairs, vs, is_


# ── what is loaded: vendors, statements, both sides' lines ──────────────────
@dataclass
class Vendor:
    """One vendor — every Agency Master row with this name and branch, whatever its channel."""
    key: str
    name: str
    branch: Optional[str]
    channels: list[str] = field(default_factory=list)
    agency_ids: list[int] = field(default_factory=list)


def vendor_key(name: Optional[str], branch: Optional[str]) -> Optional[str]:
    n = " ".join((name or "").upper().split())
    if not n:
        return None
    return f"{n}|{' '.join((branch or '').upper().split())}"


@dataclass
class Stmt:
    """A Third Party GDS statement, with the vendor it was uploaded under and its balances."""
    batch_id: str
    file_name: Optional[str]
    uploaded_at: Optional[datetime]
    period_from: Optional[date]
    period_to: Optional[date]
    vendor_key: Optional[str]
    vendor_name: Optional[str]
    opening: Optional[float] = None
    closing: Optional[float] = None
    lines: int = 0
    billed: float = 0.0
    # The lines of its file its upload left out as repeats of saved lines (`Repeat`) — not
    # in `lines` / `billed`, which are the lines saved as its own — and how many more it left
    # out before they were kept (counted on the header only).
    repeats: int = 0
    repeats_net: float = 0.0
    unlisted: int = 0

    def public(self) -> dict:
        return {
            "batch_id": self.batch_id, "vendor_id": self.vendor_key, "vendor_name": self.vendor_name,
            "file_name": self.file_name, "uploaded_at": _iso(self.uploaded_at),
            "period_from": _day(self.period_from), "period_to": _day(self.period_to),
            "lines": self.lines, "billed": round(self.billed, 2),
            "repeats": self.repeats, "repeats_net": round(self.repeats_net, 2),
            "repeats_unlisted": self.unlisted,
            "opening": None if self.opening is None else round(self.opening, 2),
            "closing": None if self.closing is None else round(self.closing, 2),
        }


# Why a line of a statement's file was not saved — the upload's buckets (tp_gds_reupload).
LEFT_OUT = {"exact": "already uploaded", "partial": "partial duplicate", "in_file": "repeated in its file"}
DIFF_LABEL = dict(DIFF_FIELDS)


@dataclass
class Repeat:
    """A line of a statement's file its upload left out because it repeats a saved line
    (models/statement_row.ThirdPartyGdsLeftOut). Shown with the statement, never matched and
    never counted: its money and its reconciliation are the saved line's (`of_id`)."""
    line: Line
    kind: str                      # exact | partial | in_file — see LEFT_OUT
    of_id: Optional[int]           # the saved vendor line it repeats; None once that is deleted
    differs: list[str] = field(default_factory=list)
    file_row: Optional[int] = None


@dataclass
class Book:
    vendor: list[Line]
    internal: list[Line]
    vendors: dict[str, Vendor]
    stmts: dict[str, Stmt]
    internal_ends: dict[str, Optional[str]]     # internal statement batch → its declared end
    repeats: list[Repeat] = field(default_factory=list)


@dataclass(frozen=True)
class Scope:
    """What the screen is looking at. None everywhere: every vendor, every statement, all dates."""
    vendor: Optional[str] = None
    statement: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


async def _load(db: AsyncSession, tenant_id: int, user_id: int) -> Book:
    agencies = (await db.execute(
        select(Agency.id, Agency.name, Agency.branch_name, Agency.channels)
        .where(Agency.user_id == user_id).order_by(Agency.name, Agency.id)
    )).all()
    vendors: dict[str, Vendor] = {}
    by_agency: dict[int, str] = {}
    for a in agencies:
        k = vendor_key(a.name, a.branch_name)
        if not k:
            continue
        v = vendors.setdefault(k, Vendor(k, a.name.strip(), (a.branch_name or "").strip() or None))
        v.agency_ids.append(a.id)
        for c in str(a.channels or "").replace(",", " ").split():
            if c.upper() not in v.channels:
                v.channels.append(c.upper())
        by_agency[a.id] = k

    sq = (
        select(ThirdPartyStatement, StatementBatchSupplier, StatementBatchControl)
        .join(StatementBatchSupplier, and_(StatementBatchSupplier.batch_id == ThirdPartyStatement.batch_id,
                                           StatementBatchSupplier.slug == _TP_GDS), isouter=True)
        .join(StatementBatchControl, and_(StatementBatchControl.batch_id == ThirdPartyStatement.batch_id,
                                          StatementBatchControl.slug == _TP_GDS), isouter=True)
        .where(ThirdPartyStatement.tenant_id == tenant_id, ThirdPartyStatement.created_by_id == user_id,
               ThirdPartyStatement.slug == _TP_GDS)
    )
    stmts: dict[str, Stmt] = {}
    for h, sup, ctl in (await db.execute(sq)).all():
        key = by_agency.get(sup.agency_id) if sup and sup.agency_id is not None else None
        if key is None and sup and sup.supplier_name:
            # Uploaded under a vendor no longer in Agency Master: still its own vendor, by the
            # name the statement was filed under.
            key = vendor_key(sup.supplier_name, sup.supplier_branch)
            if key and key not in vendors:
                vendors[key] = Vendor(key, sup.supplier_name.strip(), (sup.supplier_branch or "").strip() or None)
        stmts[h.batch_id] = Stmt(
            batch_id=h.batch_id, file_name=h.source_file, uploaded_at=h.uploaded_at,
            period_from=h.period_from, period_to=h.period_to, vendor_key=key,
            vendor_name=(vendors[key].name if key in vendors else (sup.supplier_name if sup else None)),
            opening=None if ctl is None or ctl.opening_balance is None else float(ctl.opening_balance),
            closing=None if ctl is None or ctl.closing_balance is None else float(ctl.closing_balance),
            unlisted=h.duplicate_entries or 0,     # less the ones kept, below
        )

    # Ordered by id: when one ticket has two lines that tie, the same one must win every
    # time, or its item_key (and the decision stored against it) would flip between loads.
    vq = (select(ThirdPartyGds)
          .where(ThirdPartyGds.tenant_id == tenant_id, ThirdPartyGds.created_by_id == user_id,
                 ThirdPartyGds.batch_id.in_(list(stmts) or [""]))
          .order_by(ThirdPartyGds.id))
    vendor: list[Line] = []
    for (row,) in (await db.execute(vq)).all():
        st = stmts.get(row.batch_id)
        ln = _vendor_line(row, st.file_name if st else None, st.uploaded_at if st else None,
                          st.vendor_key if st else None)
        if ln is None:
            continue
        vendor.append(ln)
        if st:
            st.lines += 1
            st.billed += ln.amounts["net"]

    # The lines each statement's upload left out as repeats — shown with it, never matched.
    rq = (select(ThirdPartyGdsLeftOut)
          .where(ThirdPartyGdsLeftOut.tenant_id == tenant_id, ThirdPartyGdsLeftOut.created_by_id == user_id,
                 ThirdPartyGdsLeftOut.batch_id.in_(list(stmts) or [""]))
          .order_by(ThirdPartyGdsLeftOut.batch_id, ThirdPartyGdsLeftOut.id))
    repeats: list[Repeat] = []
    for (row,) in (await db.execute(rq)).all():
        st = stmts.get(row.batch_id)
        if st:
            st.unlisted = max(st.unlisted - 1, 0)
        ln = _vendor_line(row, st.file_name if st else None, st.uploaded_at if st else None,
                          st.vendor_key if st else None)
        if ln is None:
            continue
        repeats.append(Repeat(line=ln, kind=row.kind, of_id=row.repeat_of_id,
                              differs=[f for f in (row.differs or "").split(",") if f], file_row=row.file_row))
        if st:
            st.repeats += 1
            st.repeats_net += ln.amounts["net"]

    iq = (
        select(InternalUploadedTicket, InternalTicketStatement)
        .join(InternalTicketStatement, and_(
            InternalTicketStatement.batch_id == InternalUploadedTicket.batch_id,
            InternalTicketStatement.tenant_id == InternalUploadedTicket.tenant_id,
        ), isouter=True)
        .where(InternalUploadedTicket.tenant_id == tenant_id, InternalUploadedTicket.created_by_id == user_id)
        .order_by(InternalUploadedTicket.id)
    )
    internal: list[Line] = []
    internal_ends: dict[str, Optional[str]] = {}
    for t, s in (await db.execute(iq)).all():
        agency = books_agency(t, s)
        internal.append(_internal_line(t, s.file_name if s else None, (s.created_at if s else None) or t.created_at,
                                       by_agency.get(agency) if agency is not None else None))
        if s is not None:
            internal_ends[s.batch_id] = _day(s.valid_to)
    return Book(vendor=vendor, internal=internal, vendors=vendors, stmts=stmts, internal_ends=internal_ends,
                repeats=repeats)


# ── reconcile, and resolve ───────────────────────────────────────────────────
async def reconcile(db: AsyncSession, *, tenant_id: int, user_id: int,
                    scope: Scope = Scope(), view: str = "all") -> dict:
    book = await _load(db, tenant_id, user_id)
    rows = match_lines(book.vendor, book.internal)
    apply_resolutions(rows, await _resolutions(db, tenant_id, user_id))
    return build_view(rows, book, scope, view)


async def resolve(
    db: AsyncSession, *, tenant_id: int, user_id: int, keys: list[str], decision: str,
    note: Optional[str], scope: Scope = Scope(), view: str = "all",
) -> dict:
    """Record one decision on every line in `keys`, with the figures each shows now.

    The lines are looked up in a fresh reconciliation of everything loaded, never taken from
    the caller, so what is stored is what the statements say. Raises LookupError when a key
    is not an open line any more (a statement changed under the screen)."""
    book = await _load(db, tenant_id, user_id)
    rows = match_lines(book.vendor, book.internal)
    by_key = {r["key"]: r for r in rows}
    keys = list(dict.fromkeys(keys))     # one upsert cannot touch the same row twice
    gone = [k for k in keys if k not in by_key or by_key[k]["status"] == MATCHED]
    if gone:
        raise LookupError(gone)

    now = datetime.utcnow()
    values = []
    for k in keys:
        r = by_key[k]
        values.append({
            "tenant_id": tenant_id, "created_by_id": user_id, "item_key": k,
            "ticket_number": r["ticket_number"], "kind": r["kind"], "status": r["status"],
            "decision": decision, "note": (note or "").strip() or None,
            "vendor_net": r["vendor"]["net"] if r["vendor"] else None,
            "internal_net": r["internal"]["net"] if r["internal"] else None,
            "difference": r["diff"]["net"] if r["diff"] else None,
            "resolved_at": now,
        })
    stmt = pg_insert(VendorInternalResolution).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_vendor_internal_resolution_key",
        set_={c: stmt.excluded[c] for c in ("ticket_number", "kind", "status", "decision", "note",
                                            "vendor_net", "internal_net", "difference", "resolved_at")},
    )
    await db.execute(stmt)
    await db.commit()

    apply_resolutions(rows, await _resolutions(db, tenant_id, user_id))
    return build_view(rows, book, scope, view)


def _span(lines: list[Line]) -> tuple[Optional[str], Optional[str]]:
    """The first and last date a side's lines carry."""
    ds = sorted(d for d in (ln.date for ln in lines) if d and _ISO.match(d))
    return (ds[0], ds[-1]) if ds else (None, None)


def _pending(date: Optional[str], other_last: Optional[str]) -> Optional[str]:
    if not (date and other_last and _ISO.match(date)):
        return None
    return NEXT_STATEMENT if date > other_last else IN_PERIOD


def match_lines(vendor: list[Line], internal: list[Line]) -> list[dict]:
    """Every line of both sides, placed in exactly one row, each with a stable `key`."""
    # Which dates each side covers — for "outside the other side's period" hints, and for
    # whether a one-sided line is still expected in the other side's next statement.
    i_from, i_to = _span(internal)
    v_to = _span(vendor)[1]

    by_v: dict[tuple, list[Line]] = defaultdict(list)
    by_i: dict[tuple, list[Line]] = defaultdict(list)
    for ln in vendor:
        by_v[(ln.serial, ln.kind)].append(ln)
    for ln in internal:
        by_i[(ln.serial, ln.kind)].append(ln)
    # Everything each side has for a ticket, either kind — for ticket-level hints.
    v_ticket: dict[str, list[Line]] = defaultdict(list)
    i_ticket: dict[str, list[Line]] = defaultdict(list)
    for ln in vendor:
        v_ticket[ln.serial].append(ln)
    for ln in internal:
        i_ticket[ln.serial].append(ln)

    rows: list[dict] = []
    left_v: list[Line] = []
    left_i: list[Line] = []

    # SOLD AND VOIDED, BOOKED AS ONE NET LINE. One side sells a ticket and refunds it
    # (89,257 out, 89,257 back, charges kept); the other books a single line for what
    # was actually charged (354 + 100 + 18 = 472). Pairing that 472 with the 89,257
    # sale reports an 88,903 "difference" that is not one. Such a ticket is compared
    # whole — the netting side's two lines summed against the single line.
    netted: set[str] = set()
    for serial in sorted(set(v_ticket) & set(i_ticket), key=lambda s: s or ""):
        for full, single in ((v_ticket[serial], i_ticket[serial]), (i_ticket[serial], v_ticket[serial])):
            kinds = sorted(ln.kind for ln in full)
            if kinds == [REFUND, SALE] and len(single) == 1 and single[0].kind == SALE:
                sale = next(ln for ln in full if ln.kind == SALE)
                if abs(single[0].amounts["fare"]) < 0.5 * abs(sale.amounts["fare"]):
                    rows.append(_netted_row(serial, full, single[0]))
                    netted.add(serial)
                    break

    for key in sorted(set(by_v) | set(by_i), key=lambda k: (k[0] or "", k[1])):
        if key[0] in netted:
            continue
        pairs, lv, li = _pair(by_v.get(key, []), by_i.get(key, []))
        for v, i in pairs:
            status, diffs, hints = _compare(v, i)
            rows.append(_row(key, status, v, i, diffs, hints))
        left_v += lv
        left_i += li

    # Unpaired lines: say what the other side DOES have, or where it might be.
    unpaired_i = list(left_i)
    for v in left_v:
        rows.append(_row((v.serial, v.kind), VENDOR_ONLY, v, None, None,
                         _orphan_hints(v, v_ticket, i_ticket, unpaired_i, other_span=(i_from, i_to)),
                         pending=_pending(v.date, i_to)))
    unpaired_v = list(left_v)
    for i in left_i:
        rows.append(_row((i.serial, i.kind), INTERNAL_ONLY, None, i, None,
                         _orphan_hints(i, i_ticket, v_ticket, unpaired_v, other_span=None),
                         pending=_pending(i.date, v_to)))

    _charges_elsewhere_hints(rows, left_v, left_i)

    # Keys before the display sort, in the order rows were built (deterministic for the
    # same statements), so a tie between two identical keys always numbers the same way.
    _assign_keys(rows)
    rows.sort(key=lambda r: (_STATUS_ORDER[r["status"]], r["ticket_number"] or "", r["kind"]))
    return rows


def _item_key(r: dict) -> str:
    """Ticket + sale/refund + the vendor week + the internal Doc No: what a person would
    use to name the line, and what survives re-uploading either statement."""
    def ref(side: str) -> str:
        s = r[side]
        return (s["ref"] or s["source"] or "") if s else ""
    return "|".join((r["ticket_number"] or "", r["kind"], ref("vendor"), ref("internal")))[:480]


def _assign_keys(rows: list[dict]) -> None:
    seen: dict[str, int] = defaultdict(int)
    for r in rows:
        k = _item_key(r)
        seen[k] += 1
        r["key"] = k if seen[k] == 1 else f"{k}#{seen[k]}"


def _num(v: Any) -> Optional[float]:
    return None if v is None else float(v)


async def _resolutions(db: AsyncSession, tenant_id: int, user_id: int) -> dict[str, dict]:
    q = select(VendorInternalResolution).where(
        VendorInternalResolution.tenant_id == tenant_id, VendorInternalResolution.created_by_id == user_id)
    return {
        r.item_key: {
            "id": r.id, "decision": r.decision, "note": r.note, "status": r.status,
            "vendor_net": _num(r.vendor_net), "internal_net": _num(r.internal_net),
            "difference": _num(r.difference), "resolved_at": _iso(r.resolved_at),
        }
        for r in (await db.execute(q)).scalars()
    }


def _same(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < 0.005


def apply_resolutions(rows: list[dict], resolutions: dict[str, dict]) -> None:
    """Mark every row open or closed. Matched rows are closed by themselves; any other row
    is closed by a decision taken on the figures it still shows. A decision taken on
    different figures stays beside the row (`stale`), but the row is open again."""
    for r in rows:
        res = resolutions.get(r["key"]) if r["status"] != MATCHED else None
        if res:
            stale = (res["status"] != r["status"]
                     or not _same(res["vendor_net"], r["vendor"]["net"] if r["vendor"] else None)
                     or not _same(res["internal_net"], r["internal"]["net"] if r["internal"] else None))
            r["resolution"] = {**res, "stale": stale}
        else:
            r["resolution"] = None
        r["open"] = r["status"] != MATCHED and (r["resolution"] is None or r["resolution"]["stale"])


NETTED = "sale+refund"


def _netted_row(serial: str, full: list[Line], single: Line) -> dict:
    """One row for a ticket one side sold and refunded and the other booked once."""
    vendor_side = full[0].side == "vendor"
    total = Line(
        side=full[0].side, id=full[0].id, serial=serial, code=full[0].code, kind=NETTED,
        pax=full[0].pax, pnr=next((ln.pnr for ln in full if ln.pnr), None), sector=full[0].sector,
        date=full[0].date, ref=" + ".join(x for x in (ln.ref for ln in full) if x) or None,
        source=full[0].source, loaded_at=max((ln.loaded_at for ln in full if ln.loaded_at), default=None),
        booked=full[0].booked, vendor_key=next((ln.vendor_key for ln in full if ln.vendor_key), None),
        batches=list(dict.fromkeys(b for ln in full for b in ln.batches)), n_lines=len(full),
        line_ids=[x for ln in full for x in ln.line_ids],
        amounts={k: sum(ln.amounts.get(k, 0.0) for ln in full) for k in full[0].amounts},
    )
    v, i = (total, single) if vendor_side else (single, total)
    status, diffs, hints = _compare(v, i)
    who, other = ("vendor", "internal") if vendor_side else ("internal", "vendor")
    hints.insert(0, f"Sold and refunded on the {who} side ({len(full)} lines), booked as one net line "
                    f"on the {other} side — compared as whole tickets")
    return _row((serial, NETTED), status, v, i, diffs, hints)


def _charges_elsewhere_hints(rows: list[dict], left_v: list[Line], left_i: list[Line]) -> None:
    """A difference that is exactly an unmatched line with the same PNR — the money is
    there, booked against another ticket (e.g. a service fee on the EMD on one side,
    on its own charges-only ticket on the other)."""
    for r in rows:
        if r["status"] != DIFFERENCE or not r["vendor"] or not r["internal"]:
            continue
        pnrs = {p.upper() for p in (r["vendor"].get("pnr"), r["internal"].get("pnr")) if p}
        gap = r["diff"]["net"]                         # internal − vendor
        for side, pool in (("internal", left_i), ("vendor", left_v)):
            for o in pool:
                if not o.pnr or o.pnr.upper() not in pnrs:
                    continue
                # Missing on the internal side means it is an extra internal line, and vice versa.
                want = -gap if side == "internal" else gap
                if abs(o.amounts["net"] - want) < ROUND_TOLERANCE:
                    r["hints"].append(
                        f"The {_inr(abs(gap))} is on {side} ticket {o.code + ' ' if o.code else ''}{o.serial}"
                        f"{f' ({o.ref})' if o.ref else ''}, same PNR {o.pnr} — booked against another ticket")
                    break


_STATUS_ORDER = {DIFFERENCE: 0, VENDOR_ONLY: 1, INTERNAL_ONLY: 2, MATCHED: 3}


def _row(key, status, v: Optional[Line], i: Optional[Line], diffs, hints, pending: Optional[str] = None) -> dict:
    # "key" is set by _assign_keys once every row exists; "resolution" / "open" by
    # apply_resolutions; the vendor, the cases and the dates by annotate.
    return {
        "key": None,
        "ticket_number": key[0], "kind": key[1], "status": status,
        "vendor": v.public() if v else None,
        "internal": i.public() if i else None,
        "diff": diffs, "hints": hints, "pending": pending,
        "resolution": None, "open": status != MATCHED,
    }


def _orphan_hints(
    ln: Line, own_ticket: dict, other_ticket: dict, other_unpaired: list[Line],
    other_span: Optional[tuple[Optional[str], Optional[str]]],
) -> list[str]:
    other = "internal" if ln.side == "vendor" else "vendor"
    hints: list[str] = []
    theirs = other_ticket.get(ln.serial, [])
    if theirs:
        kinds = sorted({t.kind for t in theirs})
        hints.append(f"The {other} side has this ticket only as a {' and a '.join(kinds)} — "
                     f"no {ln.kind} line for it")
        mine = own_ticket.get(ln.serial, [])
        mine_net = sum(x.amounts["net"] for x in mine)
        their_net = sum(x.amounts["net"] for x in theirs)
        hints.append(f"Ticket net: {ln.side} {_inr(mine_net)} · {other} {_inr(their_net)} "
                     f"(difference {_inr(their_net - mine_net if ln.side == 'vendor' else mine_net - their_net)})")
        if ln.kind == REFUND and all(t.kind == SALE for t in theirs) and theirs and \
                all(abs(t.amounts["fare"]) < abs(ln.amounts["fare"]) for t in theirs):
            hints.append("The internal line looks like the cancellation charges only — "
                         "the refund may have been booked as a single net charge")
        return hints

    # Nothing under this ticket number at all — look for a likely partner.
    for o in other_unpaired:
        if o.kind != ln.kind:
            continue
        why = []
        if ln.pnr and o.pnr and ln.pnr.upper() == o.pnr.upper():
            why.append(f"same PNR {ln.pnr}")
        if abs(o.amounts["net"] - ln.amounts["net"]) < ROUND_TOLERANCE and ln.amounts["net"]:
            why.append("same net")
        if _surname(ln.pax) and _surname(ln.pax) == _surname(o.pax):
            why.append("same passenger")
        if len(why) >= 2 or (why and why[0].startswith("same PNR")):
            label = o.ref or o.source or ""
            hints.append(f"Possible match: {other} ticket {o.code + ' ' if o.code else ''}{o.serial} "
                         f"{f'({label}) ' if label else ''}— {', '.join(why)}. Check the ticket number")
            break

    if other_span and ln.date and other_span[0] and other_span[1] and \
            re.match(r"\d{4}-\d{2}-\d{2}", ln.date) and not (other_span[0] <= ln.date <= other_span[1]):
        hints.append(f"Dated {ln.date}, outside the {other} tickets loaded ({other_span[0]} → {other_span[1]})")
    if not hints:
        hints.append(f"Not in the {other} statements loaded — load the {other} statement covering it, "
                     f"or check it was booked")
    if ln.side == "internal" and not ln.amounts["fare"] and ln.amounts["charges"]:
        hints.append("A charges-only line (no fare) — vendor statements often carry these as part of another ticket")
    return hints


# ── the cases a row makes ────────────────────────────────────────────────────
def row_cases(r: dict) -> list[dict]:
    """The reconciling items one row makes, each `{case, amount}` with the amount books − vendor:
    negative is LESS (the vendor's figure is higher), positive is ADD. A difference in commission
    and in something else makes two; they add up to the row's net difference exactly. A matched
    row makes none — its paisa are the round-off."""
    st = r["status"]
    if st == VENDOR_ONLY:
        return [{"case": VENDOR_ONLY, "amount": round(-r["vendor"]["net"], 2)}]
    if st == INTERNAL_ONLY:
        return [{"case": INTERNAL_ONLY, "amount": round(r["internal"]["net"], 2)}]
    if st != DIFFERENCE:
        return []
    delta = round(r["internal"]["net"] - r["vendor"]["net"], 2)
    comm = round(r["internal"].get("commission_net", 0.0) - r["vendor"].get("commission_net", 0.0), 2)
    rest = round(delta - comm, 2)
    # A part below FIELD_TOLERANCE is the other part's round-off, not an item of its own.
    if abs(comm) < FIELD_TOLERANCE:
        comm, rest = 0.0, delta
    elif abs(rest) < FIELD_TOLERANCE:
        comm, rest = delta, 0.0
    out: list[dict] = []
    if rest:
        if r["kind"] == SALE:
            out.append({"case": LESS_FARE if rest > 0 else EXTRA_FARE, "amount": rest})
        else:     # a refund, or a ticket sold and refunded compared whole
            out.append({"case": LESS_REFUND if rest > 0 else EXTRA_REFUND, "amount": rest})
    if comm:
        out.append({"case": LESS_COMMISSION if comm > 0 else EXTRA_COMMISSION, "amount": comm})
    return out


def _side_net(r: dict, side: str) -> float:
    return r[side]["net"] if r[side] else 0.0


def annotate(rows: list[dict], book: Book) -> None:
    """Give every row its vendor, its dates and its cases — and the hints only the vendors
    show: a ticket booked under another vendor, a ticket billed twice, one with no vendor."""
    names = {k: v.name for k, v in book.vendors.items()}

    # How far each side has loaded, per vendor: a statement's declared period, else its dates.
    def cover(lines: list[Line], declared) -> dict[Optional[str], str]:
        out: dict[Optional[str], str] = {}
        for ln in lines:
            ends = [e for e in (declared(b) for b in ln.batches) if e]
            end = max(ends) if ends else _day(ln.date)
            if end:
                for k in (ln.vendor_key, None):    # None: every vendor at once
                    out[k] = max(out.get(k, ""), end)
        return out

    v_cover = cover(book.vendor, lambda b: _day(book.stmts[b].period_to) if b in book.stmts else None)
    i_cover = cover(book.internal, lambda b: book.internal_ends.get(b))

    billed: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["vendor"]:
            billed[(r["ticket_number"], r["kind"])].append(r)

    for r in rows:
        v, i = r["vendor"], r["internal"]
        # Who billed it, else who your books say it is from.
        r["vendor_id"] = v["vendor_key"] if v else i["vendor_key"]
        r["vendor_name"] = names.get(r["vendor_id"])
        r["books_vendor_id"] = i.get("vendor_key") if i else None
        r["books_vendor_name"] = names.get(r["books_vendor_id"])
        r["booked"] = (v or {}).get("booked") or (i or {}).get("booked")
        r["statements"] = list(v["statements"]) if v else []
        ends = [_day(book.stmts[b].period_to) for b in r["statements"] if b in book.stmts]
        # The date a row counts in a balance by: its vendor statement's end; else its own date.
        r["as_at"] = max([e for e in ends if e], default=None) or r["booked"]
        r["cases"] = row_cases(r)
        r["adjustment"] = round(_side_net(r, "internal") - _side_net(r, "vendor"), 2)

        if (r["status"] == DIFFERENCE and r["kind"] == SALE and v["fare"]
                and abs(i["fare"]) < 0.5 * abs(v["fare"])):
            # The books hold the ticket as one net line of charges: sold and cancelled, the
            # vendor's refund not loaded yet. Compared whole once it is.
            r["hints"].insert(0, "Your books have this ticket as one net line of charges only — "
                                 "if it was cancelled, the vendor's refund is still to come")
        if v and i and r["vendor_id"] and r["books_vendor_id"] and r["vendor_id"] != r["books_vendor_id"]:
            r["hints"].append(f"Billed by {r['vendor_name'] or 'another vendor'}, but booked under "
                              f"{r['books_vendor_name'] or 'another vendor'} in your books")
        if r["status"] == INTERNAL_ONLY and not r["books_vendor_id"]:
            r["hints"].append("No vendor for this ticket in your books — set its Payable To, or file its "
                              "statement under the vendor, and it is reconciled against that vendor")
        if r["status"] == VENDOR_ONLY:
            also = [o for o in billed[(r["ticket_number"], r["kind"])] if o is not r]
            if also:
                where = ", ".join(dict.fromkeys(
                    f"{o['vendor']['source'] or 'another statement'}" for o in also))
                r["hints"].insert(0, f"Billed more than once — this {r['kind']} is also on {where}")
        if r["status"] in (VENDOR_ONLY, INTERNAL_ONLY):
            # Against what the OTHER side has loaded for this vendor. Nothing at all for it
            # there: that side's statement for the vendor is still to come.
            line = v or i
            other = i_cover if r["status"] == VENDOR_ONLY else v_cover
            key = r["vendor_id"]
            if key is not None and key not in other:
                r["pending"] = NEXT_STATEMENT if _day(line.get("date")) else None
            else:
                r["pending"] = _pending(line.get("date"), other.get(key))


def in_scope(r: dict, scope: Scope, stmts: dict[str, Stmt]) -> bool:
    """Whether a row belongs to what the screen is looking at. One statement holds the lines it
    billed and the vendor's tickets in your books dated within its period that no statement
    billed — what it should have carried."""
    if scope.vendor and r["vendor_id"] != scope.vendor:
        return False
    if scope.statement:
        if r["vendor"]:
            if scope.statement not in r["statements"]:
                return False
        else:
            st = stmts.get(scope.statement)
            if (st is None or st.period_from is None or st.period_to is None or not r["booked"]
                    or r["vendor_id"] != st.vendor_key
                    or not (_day(st.period_from) <= r["booked"] <= _day(st.period_to))):
                return False
    if scope.date_from or scope.date_to:
        d = r["booked"]
        if not d or (scope.date_from and d < scope.date_from) or (scope.date_to and d > scope.date_to):
            return False
    return True


def summarize(rows: list[dict]) -> dict:
    """The reconciliation statement of these rows: billed as per vendor, the eight cases, and as
    per your books — which the cases and the round-off add up to exactly."""
    vendor_billed = sum(_side_net(r, "vendor") for r in rows)
    books = sum(_side_net(r, "internal") for r in rows)
    cases = {c: {"lines": 0, "tickets": set(), "amount": 0.0, "open": 0, "open_amount": 0.0,
                 "resolved": 0, "resolved_amount": 0.0} for c in CASE_IDS}
    matched = {"lines": 0, "amount": 0.0}
    open_rows = resolved_rows = 0
    open_amount = 0.0
    for r in rows:
        if r["status"] == MATCHED:
            matched["lines"] += 1
            matched["amount"] += _side_net(r, "vendor")
            continue
        if r["open"]:
            open_rows += 1
            open_amount += r["adjustment"]
        else:
            resolved_rows += 1
        for c in r["cases"]:
            agg = cases[c["case"]]
            agg["lines"] += 1
            agg["tickets"].add(r["ticket_number"])
            agg["amount"] += c["amount"]
            if r["open"]:
                agg["open"] += 1
                agg["open_amount"] += c["amount"]
            else:
                agg["resolved"] += 1
                agg["resolved_amount"] += c["amount"]
    total_cases = sum(round(a["amount"], 2) for a in cases.values())
    return {
        "vendor_billed": round(vendor_billed, 2),
        "vendor_lines": sum(r["vendor"]["lines"] for r in rows if r["vendor"]),
        "books": round(books, 2),
        "books_lines": sum(r["internal"]["lines"] for r in rows if r["internal"]),
        "tickets": len({r["ticket_number"] for r in rows if r["ticket_number"]}),
        "difference": round(books - vendor_billed, 2),
        "cases": {c: {**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in a.items() if k != "tickets"},
                      "tickets": len(a["tickets"])} for c, a in cases.items()},
        # The agreed lines' paisa, plus what each case loses to rounding — the remainder, so the
        # statement on screen adds up to the books exactly.
        "round_off": round(round(books - vendor_billed, 2) - total_cases, 2),
        "matched": {"lines": matched["lines"], "amount": round(matched["amount"], 2)},
        "open": {"lines": open_rows, "amount": round(open_amount, 2)},
        "resolved": resolved_rows,
        "lines": len(rows),
    }


def _statement_order(s: Stmt) -> tuple:
    return (s.period_to or date.min, s.uploaded_at or datetime.min)


def balance(vendor: str, book: Book, rows: list[dict],
            statement: Optional[str] = None, upto: Optional[str] = None) -> Optional[dict]:
    """The balance payable to one vendor as per its statement and as per your books, as at the
    end of `statement` — else of its latest statement with a closing balance (ending by `upto`,
    when given).

    Line by line, not row by row: what is in the vendor's balance is every line of its
    statements that ended by then, and what is in your books is every line of theirs dated by
    then — a ticket sold in one week and refunded in the next counts its sale and not yet its
    refund. Both from the vendor's first statement on; what came before is its opening balance,
    taken as agreed. `rows` (every row loaded) only count the open items."""
    stmts = book.stmts
    own = sorted((s for s in stmts.values() if s.vendor_key == vendor), key=_statement_order)
    if not own:
        return None
    if statement:
        target = stmts.get(statement)
        if target is None or target.vendor_key != vendor:
            return None
    else:
        closing = [s for s in own if s.closing is not None
                   and (not upto or not s.period_to or _day(s.period_to) <= upto)]
        target = (closing or [s for s in own if s.closing is not None] or [None])[-1]
        if target is None:
            latest = own[-1]
            return {"available": False, "statement": latest.public(),
                    "reason": "None of this vendor's statements prints a closing balance."}
    if target.closing is None:
        return {"available": False, "statement": target.public(),
                "reason": "This statement prints no closing balance."}
    as_at = _day(target.period_to)
    if not as_at:
        return {"available": False, "statement": target.public(),
                "reason": "This statement has no period, so its balance cannot be dated."}
    starts = [_day(s.period_from) for s in own if s.period_from and _day(s.period_to) and _day(s.period_to) <= as_at]
    since = min(starts) if starts else None
    # What its file billed: its own lines, and the ones its upload left out as already
    # uploaded — its printed closing counts them, so without them they would read as payments.
    file_billed = target.billed + target.repeats_net

    def counted(d: Optional[str]) -> Optional[bool]:
        """True: in this balance. False: after it. None: before the first statement, or undated."""
        if not d:
            return None
        if d > as_at:
            return False
        return None if since and d < since else True

    def vendor_day(ln: Line) -> Optional[str]:
        ends = [e for e in (_day(stmts[b].period_to) for b in ln.batches if b in stmts) if e]
        return max(ends) if ends else ln.booked

    billed = books = 0.0
    later = 0
    for ln, day in ([(ln, vendor_day(ln)) for ln in book.vendor if ln.vendor_key == vendor]
                    + [(ln, _day(ln.date) or ln.booked) for ln in book.internal if ln.vendor_key == vendor]):
        c = counted(day)
        if c is False:
            later += 1
        elif c:
            if ln.side == "vendor":
                billed += ln.amounts["net"]
            else:
                books += ln.amounts["net"]
    adjust = round(books - billed, 2) + 0.0
    return {
        "available": True,
        "statement": target.public(),
        "as_at": as_at, "since": since,
        "opening": None if target.opening is None else round(target.opening, 2),
        "billed": round(file_billed, 2),
        # Of which on lines already uploaded on an earlier statement — reconciled there, and
        # not in `vendor_upto`.
        "repeated": {"lines": target.repeats, "amount": round(target.repeats_net, 2)},
        # Payments and anything else the account moved by: opening + billed − closing. (+ 0.0
        # turns the −0.0 a balanced account rounds to into 0.0.)
        "payments": None if target.opening is None
        else round(target.opening + file_billed - target.closing, 2) + 0.0,
        "closing": round(target.closing, 2),
        # Every ticket line from the first statement to the balance date, on each side.
        "vendor_upto": round(billed, 2), "books_upto": round(books, 2),
        "items": adjust,
        "open_items": sum(1 for r in rows if r["vendor_id"] == vendor and r["open"]
                          and r["as_at"] and r["as_at"] <= as_at and (not since or r["as_at"] >= since)),
        "books": round(target.closing + adjust, 2),
        "later": later,
    }


def _sibling(r: dict) -> dict:
    return {"key": r["key"], "kind": r["kind"], "status": r["status"], "open": r["open"],
            "cases": [c["case"] for c in r["cases"]],
            "vendor_net": r["vendor"]["net"] if r["vendor"] else None,
            "internal_net": r["internal"]["net"] if r["internal"] else None,
            "vendor_ref": r["vendor"]["ref"] if r["vendor"] else None,
            "internal_ref": r["internal"]["ref"] if r["internal"] else None}


def _pick(rows: list[dict], view: str) -> list[dict]:
    if view in ("summary", ALREADY_UPLOADED):
        return []
    if view == MATCHED:
        return [r for r in rows if r["status"] == MATCHED]
    if view == UNMATCHED:
        return [r for r in rows if r["status"] != MATCHED]
    if view == "resolved":
        return [r for r in rows if r["status"] != MATCHED and not r["open"]]
    if view in CASE_IDS:
        return [r for r in rows if r["open"] and any(c["case"] == view for c in r["cases"])]
    return rows


def repeat_rows(book: Book, rows: list[dict]) -> list[dict]:
    """Every line a statement's upload left out as a repeat, as the screen shows it: the line
    as that statement's file had it, and the row of the saved line it repeats — where that
    line, and with it this one, is reconciled (`state`: matched, resolved, open, or unsaved
    once the line it repeats is deleted). Each saved line sent again says so in a hint.
    After `annotate`."""
    names = {k: v.name for k, v in book.vendors.items()}
    by_line = {lid: r for r in rows if r["vendor"] for lid in r["vendor"].get("line_ids", [])}
    home = {lid: ln.batches[0] for ln in book.vendor if ln.batches for lid in ln.line_ids}
    out = []
    for rep in book.repeats:
        ln = rep.line
        st = book.stmts.get(ln.batches[0]) if ln.batches else None
        orig = by_line.get(rep.of_id) if rep.of_id is not None else None
        first = book.stmts.get(home.get(rep.of_id)) if rep.of_id is not None else None
        state = ("unsaved" if orig is None else MATCHED if orig["status"] == MATCHED
                 else "open" if orig["open"] else "resolved")
        if orig is not None:
            orig["hints"].append(f"Sent again on {(st.file_name if st else None) or 'a later statement'} — "
                                 f"not saved there ({LEFT_OUT[rep.kind]})")
        out.append({
            "key": f"left_out:{ln.id}",
            "ticket_number": ln.serial, "kind": ln.kind, "left_out": rep.kind,
            "differs": [DIFF_LABEL.get(f, f) for f in rep.differs], "file_row": rep.file_row,
            "vendor": ln.public(), "vendor_id": ln.vendor_key, "vendor_name": names.get(ln.vendor_key),
            "booked": ln.booked,
            "statement": st.public() if st else None,
            "first_statement": first.public() if first else None,
            "state": state, "original": orig,
        })
    return out


def statement_table(vendor: str, book: Book, rows: list[dict]) -> list[dict]:
    """A vendor's statements, newest first — each one's own figures (what its file held, what
    it billed, its balances) and where its lines stand: the rows the screen shows once that
    statement is chosen (`in_scope`), whatever else is filtered. After `annotate`."""
    out = []
    for x in sorted((s for s in book.stmts.values() if s.vendor_key == vendor), key=_statement_order, reverse=True):
        sm = summarize([r for r in rows if in_scope(r, Scope(statement=x.batch_id), book.stmts)])
        out.append({**x.public(), "reconciled": {
            "matched": sm["matched"]["lines"], "open": sm["open"]["lines"], "open_amount": sm["open"]["amount"],
            "resolved": sm["resolved"], "difference": sm["difference"],
        }})
    return out


def repeat_in_scope(p: dict, scope: Scope) -> bool:
    """A left-out line is on the screen with its own statement — not the one it repeats."""
    if scope.vendor and p["vendor_id"] != scope.vendor:
        return False
    if scope.statement and (p["statement"] or {}).get("batch_id") != scope.statement:
        return False
    if scope.date_from or scope.date_to:
        d = p["booked"]
        if not d or (scope.date_from and d < scope.date_from) or (scope.date_to and d > scope.date_to):
            return False
    return True


def build_view(rows: list[dict], book: Book, scope: Scope, view: str = "all") -> dict:
    """What the screen shows for a scope: the filter options, the summary of the rows in scope,
    and the rows of one view — "summary" (none), "all", a case, "matched" or "resolved" — or,
    "already_uploaded", the statements' left-out lines (`repeats`)."""
    annotate(rows, book)
    left_out = repeat_rows(book, rows)
    here = [r for r in rows if in_scope(r, scope, book.stmts)]
    summary = summarize(here)
    rep_here = sorted((p for p in left_out if repeat_in_scope(p, scope)),
                      key=lambda p: ((p["statement"] or {}).get("period_to") or "",
                                     (p["statement"] or {}).get("batch_id") or "", p["file_row"] or 0))
    in_stmts = [x for x in book.stmts.values()
                if (not scope.statement or x.batch_id == scope.statement)
                and (not scope.vendor or x.vendor_key == scope.vendor)]
    # Not in the reconciliation statement: each is reconciled once, with the line it repeats.
    summary["already_uploaded"] = {
        "lines": len(rep_here),
        "amount": round(sum(p["vendor"]["net"] for p in rep_here), 2),
        **{s: sum(1 for p in rep_here if p["state"] == s) for s in (MATCHED, "resolved", "open", "unsaved")},
        # Left out by uploads made before those lines were kept — counted, not listed.
        "unlisted": sum(x.unlisted for x in in_stmts),
    }

    st = book.stmts.get(scope.statement) if scope.statement else None
    one = scope.vendor or (st.vendor_key if st else None)
    summary["balance"] = balance(one, book, rows, statement=scope.statement, upto=scope.date_to) if one else None
    # One vendor — chosen, or the one the chosen statement is from: every statement it has sent.
    summary["statements"] = statement_table(one, book, rows) if one else []
    # One statement: its own lines' total, apart from the lines of its tickets on other
    # statements that came with them (a ticket sold here and refunded in a later week is
    # compared whole), so "billed on this statement" is the statement's own figure.
    summary["statement"] = None
    if st is not None and not (scope.date_from or scope.date_to):
        summary["statement"] = {
            **st.public(),
            "other_billed": round(summary["vendor_billed"] - st.billed, 2),
            "other_lines": summary["vendor_lines"] - st.lines,
        }

    by_vendor = []
    if not one:
        groups: dict[Optional[str], list[dict]] = defaultdict(list)
        for r in here:
            groups[r["vendor_id"]].append(r)
        for k, rs in groups.items():
            s = summarize(rs)
            b = balance(k, book, rows, upto=scope.date_to) if k else None
            by_vendor.append({
                "vendor_id": k, "vendor_name": book.vendors[k].name if k in book.vendors else None,
                "statements": sum(1 for x in book.stmts.values() if x.vendor_key == k) if k else 0,
                "vendor_billed": s["vendor_billed"], "books": s["books"], "difference": s["difference"],
                "open": s["open"], "lines": s["lines"],
                "closing": b["closing"] if b and b.get("available") else None,
                "books_balance": b["books"] if b and b.get("available") else None,
                "as_at": b["as_at"] if b and b.get("available") else None,
            })
        by_vendor.sort(key=lambda x: (x["vendor_id"] is None, (x["vendor_name"] or "").upper()))
    summary["by_vendor"] = by_vendor
    summary["coverage"] = {
        "statements": sorted({b for r in here for b in r["statements"]}),
        "internal_statements": len({b for r in here if r["internal"] for b in r["internal"]["statements"]}),
    }

    picked = _pick(here, view)
    by_ticket: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["ticket_number"]:
            by_ticket[r["ticket_number"]].append(r)

    def with_siblings(r: dict) -> dict:
        return {**r, "siblings": [_sibling(o) for o in by_ticket.get(r["ticket_number"] or "", []) if o is not r]}

    out_rows = [with_siblings(r) for r in picked]
    repeats = ([{**p, "original": with_siblings(p["original"]) if p["original"] else None} for p in rep_here]
               if view == ALREADY_UPLOADED else [])

    counts = {c: summary["cases"][c]["open"] for c in CASE_IDS}
    counts.update({MATCHED: summary["matched"]["lines"], UNMATCHED: len(here) - summary["matched"]["lines"],
                   "resolved": summary["resolved"], "all": len(here), ALREADY_UPLOADED: len(rep_here)})
    return {
        "scope": {"vendor": scope.vendor, "statement": scope.statement,
                  "date_from": scope.date_from, "date_to": scope.date_to},
        "view": view,
        "options": options(book),
        "summary": summary,
        "counts": counts,
        "rows": out_rows,
        "repeats": repeats,
    }


def options(book: Book) -> dict:
    """The filter's choices: every vendor of Agency Master (with what is loaded for it) and
    every Third Party GDS statement, newest period first."""
    n_stmts: dict[str, int] = defaultdict(int)
    for s in book.stmts.values():
        if s.vendor_key:
            n_stmts[s.vendor_key] += 1
    n_books: dict[Optional[str], int] = defaultdict(int)
    for ln in book.internal:
        n_books[ln.vendor_key] += 1
    vendors = [{"id": v.key, "name": v.name, "branch": v.branch, "channels": v.channels,
                "statements": n_stmts.get(v.key, 0), "books_tickets": n_books.get(v.key, 0)}
               for v in sorted(book.vendors.values(), key=lambda v: (v.name.upper(), v.branch or ""))]
    stmts = sorted(book.stmts.values(), key=_statement_order, reverse=True)
    return {"vendors": vendors, "statements": [s.public() for s in stmts],
            "unassigned_books": n_books.get(None, 0)}
