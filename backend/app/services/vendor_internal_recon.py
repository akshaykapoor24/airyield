"""Vendor ↔ Internal reconciliation: a consolidator's statement against our own.

The vendor side is a Third Party GDS statement (third_party_gds — e.g. Globe's
weekly "TRIUMPHH BSP STATEMENT"), the internal side is Internal Statement
(internal_uploaded_tickets — e.g. "GLOBE OUR …", or tickets punched in Create
Ticket). Both describe the same tickets; this lines them up and says where, and
why, they disagree.

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

HINTS. Every row that is not a clean match says why in words — which figure moved
and by how much, a code or name that disagrees, a period the other side does not
cover, a likely partner when the ticket number itself finds nothing, or (for a
ticket sold and refunded on one side and booked once on the other) both tickets'
net side by side.

THE FOUR CASES, and what each asks of the user:
    matched        settled — nothing to look at again when the next statement loads
    difference     on both, figures disagree — the user RESOLVES it: the GDS statement
                   is wrong, the internal statement is wrong, or the difference is accepted
    vendor_only    on the GDS statement only — carried forward, re-checked against every
                   internal statement loaded after it
    internal_only  on the internal statement only — carried forward the same way
Carrying forward needs no state: every load reconciles everything loaded, so a line
waiting for its partner meets it the moment that statement arrives. `pending` says
whether it is still EXPECTED there (dated after everything the other side has loaded)
or already MISSING (the other side's statements cover its date).

RESOLUTIONS are the only thing stored (models/vendor_internal_recon.py), keyed by
ticket text so a re-upload keeps them, and checked against the figures they were taken
on so a corrected statement reopens them.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_ticket import InternalTicketStatement, InternalUploadedTicket
from app.models.statement_row import ThirdPartyGds
from app.models.third_party_statement import ThirdPartyStatement
from app.models.vendor_internal_recon import VendorInternalResolution

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

    def public(self) -> dict:
        return {
            "id": self.id, "ticket_prefix": self.code, "pax": self.pax, "pnr": self.pnr,
            "sector": self.sector, "date": self.date, "ref": self.ref, "source": self.source,
            "loaded_at": self.loaded_at,
            **{k: round(v, 2) for k, v in self.amounts.items()},
        }


def _iso(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v else None


def _vendor_line(row: ThirdPartyGds, source_file: Optional[str] = None,
                 uploaded_at: Optional[datetime] = None) -> Optional[Line]:
    """`source_file` / `uploaded_at` are the statement's own (models/third_party_statement.py);
    the line's copies of them are the fallback."""
    d = row.data or {}
    if (d.get("row_kind") or "").lower() in _NON_TICKET_KINDS or not d.get("ticket_number"):
        return None
    net = _f(d.get("net_amount"))
    refund = (d.get("ticket_status") or "").upper() == "CANCELLED" or net < 0
    return Line(
        side="vendor", id=row.id, serial=_serial(d.get("ticket_number")), code=_code(d.get("ticket_prefix")),
        kind=REFUND if refund else SALE,
        pax=d.get("passenger_name") or d.get("first_name"), pnr=d.get("airline_pnr"),
        sector=_route(d.get("sector")), date=d.get("issue_date"),
        ref=d.get("week"), source=source_file or row.source_file,
        loaded_at=_iso(uploaded_at or row.uploaded_at),
        amounts={
            "fare": _f(d.get("total_fare")),
            "commission": _f(d.get("commission_amount")),
            "charges": _f(d.get("service_fee")) + _f(d.get("cancellation_markup")),
            "gst": _f(d.get("gst_on_sf")),
            "tds": _f(d.get("tds")),
            "net": net,
        },
    )


def _internal_line(t: InternalUploadedTicket, statement_file: Optional[str],
                   loaded_at: Optional[datetime] = None) -> Line:
    fare = sum(_f(getattr(t, c)) for c in
               ("sell_fare", "sell_tax_yq", "sale_yr", "sale_k3", "oc_tax", "other_tax", "wo_tax"))
    gst = _f(t.gst_sell) or (_f(t.cgst_sell) + _f(t.sgst_sell) + _f(t.igst_sell))
    net = _f(t.total_amt)
    refund = (
        (t.invoice_type or "") in ("Credit Note", "Refund")
        or (t.doc_no or "").strip().upper().startswith("IR")
        or net < 0
    )
    return Line(
        side="internal", id=t.id, serial=_serial(t.ticket_number), code=_code(t.ticket_prefix),
        kind=REFUND if refund else SALE,
        pax=t.pax_name or " ".join(x for x in (t.last_name, t.first_name) if x) or None,
        pnr=t.gds_pnr or t.air_pnr, sector=_route(t.sector),
        date=t.doc_date or t.ticket_date,
        ref=re.sub(r"\s+", " ", t.doc_no) if t.doc_no else None,
        source=statement_file, loaded_at=_iso(loaded_at),
        amounts={
            "fare": fare,
            "commission": _f(t.dis_sell),
            "charges": _f(t.serv_charge) + _f(t.serv_charge_2) + _f(t.serv_charge_3) + _f(t.raf),
            "gst": gst,
            "tds": _f(t.tds_sell),
            "net": net,
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


async def reconcile(
    db: AsyncSession, *, tenant_id: int, user_id: int,
    vendor_batches: Optional[list[str]] = None,
    internal_batches: Optional[list[str]] = None,
) -> dict:
    vendor, internal = await _load(db, tenant_id, user_id, vendor_batches, internal_batches)
    rows = match_lines(vendor, internal)
    apply_resolutions(rows, await _resolutions(db, tenant_id, user_id))
    return {"summary": _summary(rows, vendor, internal), "rows": rows}


async def resolve(
    db: AsyncSession, *, tenant_id: int, user_id: int, keys: list[str], decision: str,
    note: Optional[str], vendor_batches: Optional[list[str]] = None,
    internal_batches: Optional[list[str]] = None,
) -> dict:
    """Record one decision on every line in `keys`, with the figures each shows now.

    The lines are looked up in a fresh reconciliation of the same selection, never taken
    from the caller, so what is stored is what the statements say. Raises LookupError
    when a key is not an open line any more (a statement changed under the screen)."""
    vendor, internal = await _load(db, tenant_id, user_id, vendor_batches, internal_batches)
    rows = match_lines(vendor, internal)
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
    return {"summary": _summary(rows, vendor, internal), "rows": rows}


async def _load(
    db: AsyncSession, tenant_id: int, user_id: int,
    vendor_batches: Optional[list[str]], internal_batches: Optional[list[str]],
) -> tuple[list[Line], list[Line]]:
    # Ordered by id: when one ticket has two lines that tie, the same one must win every
    # time, or its item_key (and the decision stored against it) would flip between loads.
    # The file and upload time come from the statement header, which every line has.
    vq = (select(ThirdPartyGds, ThirdPartyStatement.source_file, ThirdPartyStatement.uploaded_at)
          .join(ThirdPartyStatement, ThirdPartyStatement.batch_id == ThirdPartyGds.batch_id)
          .where(ThirdPartyGds.tenant_id == tenant_id, ThirdPartyGds.created_by_id == user_id)
          .order_by(ThirdPartyGds.id))
    if vendor_batches:
        vq = vq.where(ThirdPartyGds.batch_id.in_(vendor_batches))
    vendor = [ln for ln in (_vendor_line(r, f, at) for r, f, at in (await db.execute(vq)).all()) if ln]

    iq = (
        select(InternalUploadedTicket, InternalTicketStatement.file_name, InternalTicketStatement.created_at)
        .join(InternalTicketStatement, and_(
            InternalTicketStatement.batch_id == InternalUploadedTicket.batch_id,
            InternalTicketStatement.tenant_id == InternalUploadedTicket.tenant_id,
        ), isouter=True)
        .where(InternalUploadedTicket.tenant_id == tenant_id, InternalUploadedTicket.created_by_id == user_id)
        .order_by(InternalUploadedTicket.id)
    )
    if internal_batches:
        iq = iq.where(InternalUploadedTicket.batch_id.in_(internal_batches))
    internal = [_internal_line(t, f, at or t.created_at) for t, f, at in (await db.execute(iq)).all()]
    return vendor, internal


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
        source=full[0].source,
        amounts={k: sum(ln.amounts[k] for ln in full) for k in COMPARED},
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
    # apply_resolutions.
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


def _coverage(lines: list[Line]) -> dict:
    """What one side has loaded — how far a waiting line has been checked."""
    loaded = sorted(ln.loaded_at for ln in lines if ln.loaded_at)
    return {
        "statements": len({ln.source for ln in lines if ln.source}),
        "last_date": _span(lines)[1],
        "last_loaded": loaded[-1] if loaded else None,
    }


def _summary(rows: list[dict], vendor: list[Line], internal: list[Line]) -> dict:
    count = defaultdict(int)
    open_count = defaultdict(int)
    open_amount = defaultdict(float)
    resolved = defaultdict(int)
    matched_net = 0.0
    # internal − vendor, split by case. Every line is in exactly one row, so the four parts
    # always add up to the net difference — the reconciliation statement, line by line.
    bridge = defaultdict(float)
    for r in rows:
        st = r["status"]
        count[st] += 1
        count[f"{st}_{r['kind']}"] += 1
        if st == VENDOR_ONLY:
            amount = r["vendor"]["net"]
            bridge[st] -= amount
        elif st == INTERNAL_ONLY:
            amount = r["internal"]["net"]
            bridge[st] += amount
        else:
            amount = r["diff"]["net"]
            bridge[st] += amount
        if st == MATCHED:
            matched_net += r["vendor"]["net"]
        elif r["open"]:
            open_count[st] += 1
            open_amount[st] += amount
        else:
            resolved[st] += 1
    v_net = round(sum(ln.amounts["net"] for ln in vendor), 2)
    i_net = round(sum(ln.amounts["net"] for ln in internal), 2)
    cases = (DIFFERENCE, VENDOR_ONLY, INTERNAL_ONLY)
    parts = {c: round(bridge[c], 2) for c in cases}
    # The matched lines' round-off, plus the paisa each rounded part loses — taken as the
    # remainder, so the parts on screen add up to the net difference exactly.
    round_off = round(round(i_net - v_net, 2) - sum(parts.values()), 2)
    return {
        "vendor_lines": len(vendor), "internal_lines": len(internal),
        # Distinct tickets — a ticket sold and refunded is two lines but one ticket.
        "vendor_tickets": len({ln.serial for ln in vendor if ln.serial}),
        "internal_tickets": len({ln.serial for ln in internal if ln.serial}),
        "tickets": len({r["ticket_number"] for r in rows if r["ticket_number"]}),
        "matched": count[MATCHED], "difference": count[DIFFERENCE],
        "vendor_only": count[VENDOR_ONLY], "internal_only": count[INTERNAL_ONLY],
        "matched_net": round(matched_net, 2),
        "open": {c: open_count[c] for c in cases},
        "open_amount": {c: round(open_amount[c], 2) for c in cases},
        "resolved": {c: resolved[c] for c in cases},
        "bridge": {"round_off": round_off, **parts},
        "coverage": {"vendor": _coverage(vendor), "internal": _coverage(internal)},
        "by_kind": {k: v for k, v in count.items() if k.rsplit("_", 1)[-1] in (SALE, REFUND, NETTED)},
        "vendor_net": v_net, "internal_net": i_net, "net_difference": round(i_net - v_net, 2),
        "difference_amount": round(sum(abs(r["diff"]["net"]) for r in rows if r["status"] == DIFFERENCE), 2),
    }
