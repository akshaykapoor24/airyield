"""Vendors data → Payment Module: Vendor Mapping and Vendor Payments.

VENDOR MAPPING — THE VENDOR'S STATEMENT IS THE BASE. Every ticket a consolidator billed — its
Third Party GDS and LCC statements, the uploads under Statements → Third Party — is looked for
in the MO: Internal Statement's uploads filed as a Booking / MO statement (statement_category
"booking"; never an Accounting statement, never a Create Ticket entry). Each ticket is

    matched       the MO has the ticket, under this vendor, at the same fare
    fare_diff     the MO has it at another fare
    not_in_mo     the MO has no line for it
    other_vendor  the MO has it, filed under another vendor — the one risk of paying twice

ONE ROW PER TICKET (the user's call, 2026-10-30): every line the vendor billed for a ticket and
every line the MO has for it, by the document serial. A side that sold and refunded the ticket is
knocked off — sale less refund — and the two finals are compared (`ticket_row`): a vendor that
billed one line of charges for a ticket the MO sold and refunded, or that has not credited a
refund the MO has, is one comparison, not a sale "paired" with a refund. A refund's figures count
as given back whatever sign its statement printed them with. ONE WAY ONLY (2026-10-29): an MO
ticket no vendor billed is not this screen's question — it is never listed or counted here.

FARE, NOT NET. What is compared is the fare — Basic, Total Tax and SSR, and their total. The
vendor's net also carries its commission, TDS and fees, and the MO's commission is another
figure on purpose: Yatra's report carries the IATA commission and PLB it expects, the vendor
prints what it passed on. Whether that is right is Commission income's question, priced
against the deals; here it is shown beside the fares and is never a reason to hold. A refund's
fare is printed positive by one statement and negative by another, so a refund is compared on
what it gives back, whatever its sign.

WHAT IS PAYABLE — pay what is not in dispute, withhold what is, never refuse a credit:
    matched                     the vendor's net
    fare_diff, vendor higher    the net less the excess; the excess is held
    fare_diff, vendor lower     the net — the difference is in your favour (to review, not held)
    not_in_mo / other_vendor    nothing while open — the net is held — unless the line is a
                                credit (a refund), which is always taken
A decision closes a line: `vendor_wrong` turns what was held into a claim, never paid;
`mo_wrong` and `accepted` pay it as billed. A decision taken on other figures is stale and the
line is open again (models/vendor_mapping.py).

VENDOR PAYMENTS — ONE ACCOUNT PER VENDOR. A consolidator is paid on account, a lump sum by
NEFT / RTGS against its balance, not ticket by ticket:
      opening      its first statement's printed OLD line, when it has one
    + billed       every statement's lines
    − claims       what `vendor_wrong` decisions took off
    − paid         every payment recorded and not voided
    = balance      owed to the vendor; below zero, an advance with it
A payment is applied to the statements oldest first — one made against a statement goes to
that statement first — and a credit statement settles the ones after it the same way. That
gives every statement its paid and balance, and the account its ageing.
"""
from __future__ import annotations

import time
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import String, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_ledger import PAYMENT_COMPLETED, PAYMENT_MODES, PAYMENT_VOIDED, VendorPayment
from app.models.vendor_mapping import (
    MAPPING_DECISIONS, MAPPING_VENDOR_WRONG, VendorMappingDecision,
)
from app.services import vendor_internal_recon as recon

MO_CATEGORY = "booking"
VENDOR_SLUGS = ("tp-gds", "tp-lcc")

MATCHED = "matched"
FARE_DIFF = "fare_diff"
NOT_IN_MO = "not_in_mo"
OTHER_VENDOR = "other_vendor"
STATUSES = (MATCHED, FARE_DIFF, NOT_IN_MO, OTHER_VENDOR)

VIEWS = ("all", *STATUSES, "open", "on_hold", "claims", "resolved")

FARE_TOLERANCE = 1.0     # rupees — an MO rounds its figures to the rupee
PART_TOLERANCE = 0.5     # rupees — below this a part of the fare is "the same"

# What a line does to the payment.
PAY_CLEAR = "clear"      # paid as billed
PAY_HOLD = "hold"        # nothing paid until decided
PAY_PART = "part_hold"   # paid less the excess; the excess held
PAY_REVIEW = "review"    # paid as billed, but differs in your favour — look at it
PAY_CREDIT = "credit"    # a credit the MO does not have — taken
PAY_CLAIM = "claim"      # decided: the vendor is wrong — what was held is claimed back

# The ageing of what is owed, by days since the statement's period ended.
AGING_BUCKETS: tuple[tuple[int, Optional[int], str], ...] = (
    (0, 15, "0–15 days"), (16, 30, "16–30 days"), (31, 60, "31–60 days"),
    (61, 90, "61–90 days"), (91, None, "Over 90 days"),
)
# The modes a bank reference (UTR / cheque number) is required for.
BANK_MODES = ("NEFT", "RTGS", "IMPS", "UPI", "Cheque")


class MappingError(ValueError):
    """A request refused; the message is written for the user."""


def _r(x: float) -> float:
    # + 0.0 turns the −0.0 a settled figure rounds to into 0.0.
    return round(x, 2) + 0.0


def _inr(v: float) -> str:
    return f"{v:,.2f}"


def _same(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < 0.005


# ── one ticket, both sides ───────────────────────────────────────────────────
# A ticket is a row: every line the vendor billed for it, and every line the MO has for it. A
# side that sold and refunded the ticket is KNOCKED OFF — sale less refund — and the two finals
# are compared, so whatever each side did with the ticket, it is one comparison:
#   vendor sale            · MO sale              the sale against the sale
#   vendor sale            · MO sale + refund     the vendor has not credited the refund yet
#   vendor charges line    · MO sale + refund     its one line of charges against what the MO kept
#   vendor sale + refund   · MO sale + refund     final against final
#   vendor sale + refund   · MO sale              the vendor credited a refund the MO lacks
#   vendor refund          · MO refund            what each gave back
_PARTS = ("base", "tax", "ssr")
SALE_REFUND = recon.NETTED          # "sale+refund"
_MONEY = ("base", "tax", "ssr", "charge", "fare", "net", "commission", "tds")


def _is_refund(ln: recon.Line) -> bool:
    """A refund line: as its side reads it, or — the user's rule (2026-10-30) — one with a negative
    Basic or Tax, which is what a refund printed with a positive amount still shows."""
    a = ln.amounts
    return ln.kind == recon.REFUND or a.get("base", 0.0) < 0 or a.get("tax", 0.0) < 0


def _signed(x: float, refund: bool) -> float:
    """A figure as it moves the ticket: a sale's as printed; a refund's given back, whatever sign
    its statement printed it with — Yatra's refund report prints the Basic negative on one line and
    positive on the next, Brightsun and TripJack print some refunds positive throughout."""
    return -abs(x) if refund else x


def mo_given_back(a: dict, sale_base: float = 0.0) -> float:
    """What an MO refund line gave back, as a positive figure.

    THE AIRLINE'S CANCELLATION CHARGE (the user's rule, 2026-10-30). What the airline kept is not
    given back. Yatra's refund report prints it in airline_cancellation_charge, and prints the line
    one of two ways — so the charge is taken off only where the Basic still holds it:
      * the Basic as sold, the charge apart (5809142213: Basic 1,18,022, charge 1,18,022 — only
        the 169 tax came back);
      * the Basic already less the charge (5882961640: sold at 23,790, refund Basic 23,436, charge
        354) — taking it off again would count it twice.
    The file's Net Cancellation Amount says which, where it is one of the two (448 of 448 lines
    whose sale is in the MO): Basic + Tax − charge, or Basic + Tax. Else the MO's own sale: a
    refund Basic equal to the sale's still holds the charge; one equal to the sale's less the
    charge does not. Else, the charge is taken off."""
    b, t, ssr = abs(a.get("base", 0.0)), abs(a.get("tax", 0.0)), abs(a.get("ssr", 0.0))
    charge, nett = abs(a.get("airline_charge", 0.0)), abs(a.get("net_cancel", 0.0))
    whole = b + t + ssr
    if not charge:
        return whole
    if nett and (abs(nett - (b + t - charge)) < FARE_TOLERANCE or abs(nett - (b + t)) < FARE_TOLERANCE):
        return nett + ssr
    if sale_base and abs(b + charge - sale_base) < FARE_TOLERANCE:
        return whole
    return max(whole - charge, 0.0)


def charge_of(ln: recon.Line, side: str) -> float:
    """The airline's cancellation charge a line prints: the MO's airline_cancellation_charge; the
    vendor's Cancellation Charges (Brightsun) or Agent Penalty (TripJack)."""
    return abs(ln.amounts.get("airline_charge" if side == "internal" else "canc_charge", 0.0))


def _figures(ln: recon.Line, side: str, sale_base: float = 0.0, charge: Optional[float] = None) -> dict:
    """One line's fare, net and commission as they move the ticket.

    THE CANCELLATION CHARGE, BOTH SIDES (the user's rule, 2026-10-30): what the airline kept is not
    given back — a refund line gives back its Basic + Tax + SSR less the charge (TripJack
    4849253318: 47,510 less an Agent Penalty of 8,022 is the MO's 39,488; Brightsun 5808961921:
    32,566 less Cancellation Charges of 10,815 is the MO's 21,751). `charge`: the ticket's charge
    to take off this refund line — `ticket_row` reads it off the sale or the refund, whichever
    prints it, and takes it once (Yatra prints the same charge on the sale and on the refund).
    `out["charge"]` is the charge the line prints, `out["charge_applied"]` whether it came off the
    line's fare: so a line adds up, Basic + Tax + SSR + charge = Fare, where it did.
    `sale_base`: the Basic the MO sold the ticket at (`mo_given_back`)."""
    a, refund = ln.amounts, _is_refund(ln)
    out = {k: _signed(a.get(k, 0.0), refund) for k in _PARTS}
    whole = abs(a.get("base", 0.0)) + abs(a.get("tax", 0.0)) + abs(a.get("ssr", 0.0))
    take = charge_of(ln, side) if charge is None else charge
    out["charge"], out["charge_applied"] = (take if refund else charge_of(ln, side)), False
    if side == "internal" and refund:
        given = mo_given_back({**a, "airline_charge": take}, sale_base)
        out["fare"] = -given
        out["charge_applied"] = take >= PART_TOLERANCE and given < whole - PART_TOLERANCE
    elif side == "vendor" and refund and take >= PART_TOLERANCE:
        out["fare"] = -max(whole - take, 0.0)
        out["charge_applied"] = True
    elif side == "vendor" and refund:
        # What a vendor's refund GAVE BACK is in its net, not its fare: a vendor prints the
        # original ticket's fare on the refund line (TripJack 4849253318: fare 47,510, net
        # −39,200, commission 288.44 taken back — the MO's refund is 39,488) and credits what
        # the airline returned, less the commission it takes back, plus the TDS on it. A line
        # that prints its figures negative means its net's sign; one printed positive
        # throughout is a credit whatever the sign of its net.
        comm, tds, net = abs(a.get("commission", 0.0)), abs(a.get("tds", 0.0)), a.get("net", 0.0)
        negative = a.get("base", 0.0) < 0 or a.get("tax", 0.0) < 0
        out["fare"] = net - comm + tds if negative else -(abs(net) + comm - tds)
    elif side == "vendor" and not (a.get("base") or a.get("tax")):
        # A line of charges only (no Basic, no tax): its Total Fare column is what it bills.
        out["fare"] = _signed(a.get("fare", 0.0), refund)
    else:
        out["fare"] = out["base"] + out["tax"] + out["ssr"]
    if side == "vendor":
        out["net"] = a.get("net", 0.0)                  # what the vendor bills, as it billed it
        out["commission"] = _signed(a.get("commission", 0.0), refund) if refund else abs(a.get("commission", 0.0))
    else:
        # A refund line's Amount is the original ticket's (Yatra prints the sale's BSP Amount on
        # its refund); what it gave back is `mo_given_back` — the airline's charge kept — else its
        # Net Cancellation Amount, where the file has one.
        if not refund:
            out["net"] = a.get("net", 0.0)
        elif take >= PART_TOLERANCE:
            out["net"] = out["fare"]
        else:
            out["net"] = -abs(a.get("net_cancel") or a.get("net", 0.0))
        out["commission"] = _signed(a.get("comm_expected", 0.0), refund)
    out["tds"] = a.get("tds", 0.0)
    out["kind"] = recon.REFUND if refund else recon.SALE
    return out


def _line_out(ln: recon.Line, f: dict) -> dict:
    return {"id": ln.id, "kind": f["kind"], "date": ln.date, "booked": ln.booked, "ref": ln.ref,
            "source": ln.source, "statements": list(ln.batches), "pax": ln.pax, "pnr": ln.pnr,
            "charges_only": not (ln.amounts.get("base") or ln.amounts.get("tax")),
            "charge_applied": f["charge_applied"],
            **{k: _r(f[k]) for k in _MONEY}}


def _side_figures(lines: list[recon.Line], side: str, sale_base: float = 0.0) -> list[dict]:
    """A side's lines, the ticket's cancellation charge taken off its refund once. The MO prints
    the charge on the sale and on the refund alike: a refund that prints none takes the sale's
    (the first refund only). A vendor's charge is taken off only where its refund prints it — on
    its sale, the charge is what the line bills (Brightsun's 359 "Sales" line: 300 of it)."""
    charges = [None] * len(lines)
    if side == "internal":
        refunds = [i for i, x in enumerate(lines) if _is_refund(x)]
        printed = max((charge_of(x, side) for x in lines), default=0.0)
        if refunds and printed and not any(charge_of(lines[i], side) for i in refunds):
            charges[refunds[0]] = printed
    return [_figures(x, side, sale_base, c) for x, c in zip(lines, charges)]


def _final(lines: list[recon.Line], figs: list[dict]) -> dict:
    """A side's lines knocked off into one — what the screen compares and shows as the side."""
    first = lines[0]
    out = {
        "id": first.id, "ticket_prefix": next((x.code for x in lines if x.code), None),
        "pax": next((x.pax for x in lines if x.pax), None), "pnr": next((x.pnr for x in lines if x.pnr), None),
        "sector": next((x.sector for x in lines if x.sector), ""), "date": first.date,
        "booked": min((x.booked for x in lines if x.booked), default=None),
        "ref": " + ".join(dict.fromkeys(x.ref for x in lines if x.ref)) or None,
        "source": " + ".join(dict.fromkeys(x.source for x in lines if x.source)) or None,
        "statements": list(dict.fromkeys(b for x in lines for b in x.batches)),
        "lines": len(lines), "line_ids": [i for x in lines for i in x.line_ids],
    }
    for k in _MONEY:
        out[k] = _r(sum(f[k] for f in figs))
    # A ticket's cancellation charge counts once, however many of its lines print it.
    out["charge"] = _r(max((f["charge"] for f in figs), default=0.0))
    return out


def _kinds(figs: list[dict]) -> Optional[str]:
    kinds = {f["kind"] for f in figs}
    return None if not kinds else SALE_REFUND if len(kinds) > 1 else next(iter(kinds))


def _knocked(side: str, figs: list[dict], final: float) -> Optional[str]:
    """"MO: sale 38,504.00 − refund 38,150.00 = 354.00" — for a side with both."""
    sold = sum(f["fare"] for f in figs if f["kind"] == recon.SALE)
    back = sum(f["fare"] for f in figs if f["kind"] == recon.REFUND)
    if not sold or not back:
        return None
    return f"{side}: sale {_inr(sold)} − refund {_inr(-back)} = {_inr(final)} — sold and refunded, knocked off"


def _order(ln: recon.Line) -> tuple:
    return (ln.date or "", ln.id)


_PENDING_SAID = {recon.NEXT_STATEMENT: "The MO loaded does not reach this date yet — it may be on the next MO statement",
                 recon.IN_PERIOD: "The MO loaded covers this date and has no such ticket"}


def _mo_cover(book: recon.Book) -> dict[Optional[str], str]:
    """How far the MO reaches, per vendor it files tickets under (None: every vendor) — each MO
    statement's declared end, else a ticket's own date."""
    out: dict[Optional[str], str] = {}
    for ln in book.internal:
        ends = [e for e in (book.internal_ends.get(b) for b in ln.batches) if e]
        end = max(ends) if ends else recon._day(ln.date)
        if end:
            for k in (ln.vendor_key, None):
                if end > out.get(k, ""):
                    out[k] = end
    return out


def ticket_row(serial: Optional[str], vendor_id: Optional[str], vlines: list[recon.Line],
               mlines: list[recon.Line], names: dict[str, str], *,
               mo_by_pnr: Optional[dict[str, list[recon.Line]]] = None,
               mo_cover: Optional[dict] = None, billed_by: Optional[set] = None) -> dict:
    """One ticket the vendor billed, against everything the MO has for it."""
    vf = _side_figures(vlines, "vendor")
    sale_base = sum(x.amounts.get("base", 0.0) for x in mlines if not _is_refund(x))
    mf = _side_figures(mlines, "internal", sale_base)
    vend = _final(vlines, vf)
    row: dict[str, Any] = {
        "key": f"{serial or ''}|{vendor_id or ''}"[:480], "ticket_number": serial,
        "kind": _kinds(vf), "mo_kind": _kinds(mf),
        "vendor_id": vendor_id, "vendor_name": names.get(vendor_id),
        "mo_vendor_id": None, "mo_vendor_name": None,
        "statements": vend["statements"], "booked": vend["booked"], "pending": None,
        "vendor": vend, "mo": None, "gap": None, "parts": None, "commission_gap": None, "hints": [],
        "vendor_lines": [_line_out(x, f) for x, f in zip(vlines, vf)],
        "mo_lines": [_line_out(x, f) for x, f in zip(mlines, mf)],
    }
    hints: list[str] = row["hints"]
    # No Basic fare on any of the vendor's lines: charges — a cancellation, a reissue, an SSR, a fee.
    no_basic = all(not x.amounts.get("base") for x in vlines)
    sales = [f for f in vf if f["kind"] == recon.SALE and abs(f["fare"]) >= FARE_TOLERANCE]
    if len(sales) > 1 and max(f["fare"] for f in sales) - min(f["fare"] for f in sales) < FARE_TOLERANCE:
        hints.append(f"Billed more than once — {len(sales)} sale lines of {_inr(sales[0]['fare'])}")
    others = sorted(names.get(k) or "another vendor" for k in (billed_by or set()) if k != vendor_id)
    if others:
        hints.append(f"Also billed by {', '.join(others)}")
    said = _knocked("Vendor", vf, vend["fare"])
    if said:
        hints.append(said)
    kept = max((f["charge"] for f in vf if f["charge_applied"]), default=0.0)
    if kept >= FARE_TOLERANCE:
        hints.append(f"The vendor's refund keeps {_inr(kept)} as the airline's cancellation charge — "
                     "not given back")

    if not mlines:
        row["status"] = NOT_IN_MO
        cover = mo_cover or {}
        if vendor_id is not None and vendor_id not in cover:
            row["pending"] = recon.NEXT_STATEMENT if recon._day(vend["date"]) else None
        else:
            row["pending"] = recon._pending(vend["date"], cover.get(vendor_id))
        for x in vlines:
            near = [m for m in (mo_by_pnr or {}).get((x.pnr or "").upper(), []) if m.serial != serial]
            if x.pnr and near:
                m = near[0]
                hints.append(f"Possible match: MO ticket {m.code + ' ' if m.code else ''}{m.serial}"
                             f"{f' (Doc {m.ref})' if m.ref else ''} — same PNR {x.pnr}. Check the ticket number")
                break
        if row["pending"] in _PENDING_SAID:
            hints.append(_PENDING_SAID[row["pending"]])
        elif not hints:
            hints.append("Not in the MO statements loaded — load the MO covering it, or check it was booked")
        return row

    mo = _final(mlines, mf)
    mo["comm_expected"] = mo["commission"]
    row["mo"] = mo
    row["booked"] = row["booked"] or mo["booked"]
    keys = [x.vendor_key for x in mlines if x.vendor_key]
    if vendor_id in keys:
        row["mo_vendor_id"] = vendor_id
    elif keys:
        row["mo_vendor_id"] = Counter(keys).most_common(1)[0][0]
    row["mo_vendor_name"] = names.get(row["mo_vendor_id"])

    gap = vend["fare"] - mo["fare"]
    row["gap"] = _r(gap)
    parts = {k: _r(vend[k] - mo[k]) for k in _PARTS}
    row["parts"] = parts
    if abs(vend["commission"]) >= 0.005 or abs(mo["commission"]) >= 0.005:
        # What the vendor passed on against what the MO expects (IATA commission + PLB).
        row["commission_gap"] = _r(vend["commission"] - mo["commission"])
    mo_said = _knocked("MO", mf, mo["fare"])
    kept = max((f["charge"] for f in mf if f["charge_applied"]), default=0.0)
    printed = mo["charge"]
    if kept >= FARE_TOLERANCE:
        mo_said = (f"{mo_said}. " if mo_said else "") + (
            f"The airline kept {_inr(kept)} as its cancellation charge — taken off the MO's refund")
    elif printed >= FARE_TOLERANCE and any(f["kind"] == recon.REFUND for f in mf):
        mo_said = (f"{mo_said}. " if mo_said else "") + (
            f"The MO's refund Basic is already less the airline's {_inr(printed)} cancellation charge — "
            "not taken off again")

    if vendor_id and row["mo_vendor_id"] and row["mo_vendor_id"] != vendor_id:
        row["status"] = OTHER_VENDOR
        hints.append(f"Billed by {row['vendor_name'] or 'this vendor'}, but the MO has it under "
                     f"{row['mo_vendor_name'] or 'another vendor'}")
    elif abs(gap) < FARE_TOLERANCE:
        row["status"] = MATCHED
        if abs(gap) >= 0.005:
            hints.append(f"Round-off only ({_inr(gap)}) — the MO rounds to the rupee")
    else:
        row["status"] = FARE_DIFF
        why: list[str] = []
        v_refund = any(f["kind"] == recon.REFUND for f in vf)
        m_refund = any(f["kind"] == recon.REFUND for f in mf)
        if no_basic and row["kind"] == recon.SALE and mo["base"]:
            why.append("The vendor billed this ticket as one line of charges (no Basic, no tax) — against the "
                       f"MO's sale less its refund, {_inr(mo['fare'])}" if m_refund else
                       "The vendor billed no basic fare on this line — a charges-only line (a reissue, an SSR or "
                       "a fee); the ticket's own sale may be on another statement")
        if m_refund and not v_refund and gap > 0:
            back = -sum(f["fare"] for f in mf if f["kind"] == recon.REFUND)
            why.append(f"The MO has this ticket refunded ({_inr(back)} back) — the vendor has not credited the "
                       "refund; the excess is held until it does")
        if v_refund and not m_refund and gap < 0:
            back = -sum(f["fare"] for f in vf if f["kind"] == recon.REFUND)
            why.append(f"The vendor credited a refund of {_inr(back)} the MO does not have — check the MO's "
                       "refund report is loaded")
        if not no_basic and not v_refund and not m_refund:
            # Part by part only sale against sale: a refund's parts are not what it gave back.
            why += [f"{label} differs by {_inr(parts[k])} (vendor {_inr(vend[k])} · MO {_inr(mo[k])})"
                    for k, label in (("base", "Basic fare"), ("tax", "Tax"), ("ssr", "SSR"))
                    if abs(parts[k]) >= PART_TOLERANCE]
        if vend["charge"] >= FARE_TOLERANCE and mo["charge"] >= FARE_TOLERANCE                 and abs(vend["charge"] - mo["charge"]) >= PART_TOLERANCE:
            why.append(f"Cancellation charge differs by {_inr(mo['charge'] - vend['charge'])} "
                       f"(vendor {_inr(vend['charge'])} · MO {_inr(mo['charge'])})")
        if not why:
            why.append(f"Total fare differs by {_inr(gap)} (vendor {_inr(vend['fare'])} · MO {_inr(mo['fare'])})")
        hints[:0] = why
    if mo_said:
        hints.append(mo_said)
    return row


def build_rows(book: recon.Book) -> list[dict]:
    """Every ticket the vendors billed, each against the MO — one row per ticket and vendor."""
    names = {k: v.name for k, v in book.vendors.items()}
    mo_by_serial: dict[str, list[recon.Line]] = defaultdict(list)
    mo_by_pnr: dict[str, list[recon.Line]] = defaultdict(list)
    for ln in book.internal:
        if ln.serial:
            mo_by_serial[ln.serial].append(ln)
        if ln.pnr:
            mo_by_pnr[ln.pnr.upper()].append(ln)
    groups: dict[tuple, list[recon.Line]] = defaultdict(list)
    for ln in book.vendor:
        groups[(ln.serial, ln.vendor_key)].append(ln)
    billed_by: dict[Optional[str], set] = defaultdict(set)
    for serial, key in groups:
        billed_by[serial].add(key)
    cover = _mo_cover(book)
    return [ticket_row(serial, key, sorted(vlines, key=_order), sorted(mo_by_serial.get(serial, []), key=_order),
                       names, mo_by_pnr=mo_by_pnr, mo_cover=cover, billed_by=billed_by[serial])
            for (serial, key), vlines in groups.items()]


def settle(row: dict) -> None:
    """What the ticket pays, holds and claims — the module docstring's rules, on its final."""
    net = row["vendor"]["net"]
    d = row.get("decision")
    decided = d is not None and not d["stale"]
    claimed = decided and d["decision"] == MAPPING_VENDOR_WRONG
    hold = claim = 0.0
    state = PAY_CLEAR
    if row["status"] == FARE_DIFF:
        excess = row["gap"] if row["gap"] and row["gap"] > 0 else 0.0
        if excess < FARE_TOLERANCE:
            state = PAY_CLEAR if decided else PAY_REVIEW
        elif claimed:
            claim, state = excess, PAY_CLAIM
        elif not decided:
            # Never more than the ticket bills: a credit short of the MO's refund holds nothing.
            hold = min(excess, max(net, 0.0))
            state = PAY_PART if hold >= FARE_TOLERANCE else PAY_REVIEW
    elif row["status"] in (NOT_IN_MO, OTHER_VENDOR):
        if net <= 0:
            state = PAY_CREDIT
        elif claimed:
            claim, state = net, PAY_CLAIM
        elif not decided:
            hold, state = net, PAY_HOLD
    row["pay"] = {"state": state, "hold": _r(hold), "claim": _r(claim), "payable": _r(net - hold - claim)}


def apply_decisions(rows: list[dict], decisions: dict[str, dict]) -> None:
    """Mark each row open or closed, and settle it. A matched ticket closes itself; any other is
    closed by a decision taken on the figures it still shows."""
    for row in rows:
        d = decisions.get(row["key"]) if row["status"] != MATCHED else None
        if d:
            stale = (d["status"] != row["status"]
                     or not _same(d["vendor_fare"], row["vendor"]["fare"])
                     or not _same(d["mo_fare"], row["mo"]["fare"] if row["mo"] else None)
                     or not _same(d["vendor_net"], row["vendor"]["net"]))
            row["decision"] = {**d, "stale": stale}
        else:
            row["decision"] = None
        row["open"] = row["status"] != MATCHED and (row["decision"] is None or row["decision"]["stale"])
        settle(row)


# ── everything loaded ────────────────────────────────────────────────────────
@dataclass
class Mapping:
    book: recon.Book
    rows: list[dict]        # every ticket the vendors billed, mapped and settled


async def _decisions(db: AsyncSession, tenant_id: int, user_id: int) -> dict[str, dict]:
    q = select(VendorMappingDecision).where(
        VendorMappingDecision.tenant_id == tenant_id, VendorMappingDecision.created_by_id == user_id)
    num = lambda v: None if v is None else float(v)  # noqa: E731
    return {
        d.item_key: {
            "decision": d.decision, "note": d.note, "status": d.status,
            "vendor_fare": num(d.vendor_fare), "mo_fare": num(d.mo_fare), "vendor_net": num(d.vendor_net),
            "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        }
        for d in (await db.execute(q)).scalars()
    }


# THE MAPPING IS KEPT, per user, while what it was built from is unchanged. Building it reads
# every vendor line and every MO ticket — a lakh-line MO is seconds — and a filter, a search or a
# page only narrows what was built. `_fingerprint` is a few aggregate queries over the same inputs
# (their counts, ids and a hash of the figures a row is built from): anything uploaded, edited,
# deleted or re-filed under another vendor changes it, and the next request builds afresh.
# Decisions are not part of it — they are read and applied on every request.
_CACHE: "OrderedDict[tuple[int, int], tuple[tuple, Mapping, float]]" = OrderedDict()
_CACHE_USERS = 8
_CACHE_SECONDS = 15 * 60


def _hash(*cols):
    return func.coalesce(func.sum(func.hashtext(func.concat_ws("|", *cols))), 0)


async def _fingerprint(db: AsyncSession, tenant_id: int, user_id: int) -> tuple:
    from app.models.agency import Agency
    from app.models.internal_ticket import InternalTicketStatement as S, InternalUploadedTicket as T
    from app.models.statement_batch_control import StatementBatchControl as C
    from app.models.statement_batch_supplier import StatementBatchSupplier as B
    from app.models.statement_row import ThirdPartyGds as G, ThirdPartyGdsLeftOut as L, ThirdPartyLcc as LC
    from app.models.third_party_statement import ThirdPartyStatement as TP

    mine = lambda m: (m.tenant_id == tenant_id, m.created_by_id == user_id)  # noqa: E731
    queries = [
        select(func.count(), func.max(T.id), _hash(
            T.id, T.batch_id, T.ticket_number, T.ticket_prefix, T.doc_no, T.invoice_type, T.ticket_date,
            T.doc_date, T.pax_name, T.gds_pnr, T.sell_fare, T.sell_tax, T.sell_tax_yq, T.sale_yr, T.sale_k3,
            T.oc_tax, T.other_tax, T.total_amt, T.meals, T.excess_baggage, T.seat_selection, T.iata_comm_amt,
            T.plb_amount, T.cancellation_date, T.net_cancellation_amount, T.supplier_can_charge,
            T.payable_type, T.payable_agency_id,
            T.customer_type, T.customer_agency_id)).where(*mine(T)),
        select(func.count(), _hash(S.batch_id, S.statement_category, S.customer_type, S.customer_agency_id,
                                   S.valid_to, S.file_name)).where(S.tenant_id == tenant_id),
        select(func.count(), _hash(TP.batch_id, TP.slug, TP.source_file, TP.period_from, TP.period_to,
                                   TP.uploaded_at)).where(*mine(TP)),
        select(func.count(), func.max(G.id), _hash(G.id, G.batch_id, func.cast(G.data, String))).where(*mine(G)),
        select(func.count(), func.max(LC.id), _hash(LC.id, LC.batch_id, func.cast(LC.data, String))).where(*mine(LC)),
        select(func.count(), func.max(L.id)).where(*mine(L)),
        select(func.count(), _hash(B.batch_id, B.slug, B.agency_id, B.supplier_name, B.supplier_branch)),
        select(func.count(), func.max(C.updated_at)),
        select(func.count(), _hash(Agency.id, Agency.name, Agency.branch_name, Agency.channels))
        .where(Agency.user_id == user_id),
    ]
    out = []
    for q in queries:
        out.extend((await db.execute(q)).one())
    return tuple(str(x) for x in out)


async def load(db: AsyncSession, tenant_id: int, user_id: int, *, fresh: bool = False) -> Mapping:
    """The mapping — built, or kept from the last request while nothing it reads has changed
    (`fresh`: build it whatever). Decisions are applied every time."""
    key = (tenant_id, user_id)
    fp = await _fingerprint(db, tenant_id, user_id)
    hit = _CACHE.get(key)
    if hit and not fresh and hit[0] == fp and time.monotonic() - hit[2] < _CACHE_SECONDS:
        _CACHE.move_to_end(key)
        m = hit[1]
    else:
        book = await recon.load_book(db, tenant_id, user_id, vendor_slugs=VENDOR_SLUGS, internal_category=MO_CATEGORY)
        m = Mapping(book=book, rows=build_rows(book))
        _CACHE[key] = (fp, m, time.monotonic())
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_USERS:
            _CACHE.popitem(last=False)
    apply_decisions(m.rows, await _decisions(db, tenant_id, user_id))
    return m


# ── the Vendor Mapping screen ────────────────────────────────────────────────
def summarize(rows: list[dict]) -> dict:
    """What the lines in scope come to. Per status: the lines, their net, how many are open,
    what the sales among them bill (`sales`) and how many are refunds. `fare_excess` /
    `fare_short`: the fare differences the vendor billed above / below the MO."""
    s: dict[str, Any] = {
        "lines": len(rows), "tickets": len({r["ticket_number"] for r in rows if r["ticket_number"]}),
        "billed": 0.0, "payable": 0.0, "hold": 0.0, "claim": 0.0, "credit": 0.0,
        "fare_excess": 0.0, "fare_short": 0.0,
        "open": 0, "open_amount": 0.0, "resolved": 0, "review": 0,
        "status": {k: {"lines": 0, "amount": 0.0, "open": 0, "sales": 0.0, "refunds": 0} for k in STATUSES},
    }
    for r in rows:
        net, p = r["vendor"]["net"], r["pay"]
        s["billed"] += net
        s["payable"] += p["payable"]
        s["hold"] += p["hold"]
        s["claim"] += p["claim"]
        if p["state"] == PAY_CREDIT:
            s["credit"] += net
        if p["state"] == PAY_REVIEW:
            s["review"] += 1
        b = s["status"][r["status"]]
        b["lines"] += 1
        b["amount"] += net
        if net > 0:
            b["sales"] += net
        elif net < 0:
            b["refunds"] += 1
        if r["open"]:
            b["open"] += 1
            s["open"] += 1
            s["open_amount"] += net
        elif r["status"] != MATCHED:
            s["resolved"] += 1
        if r["status"] == FARE_DIFF and r["gap"]:
            s["fare_excess" if r["gap"] > 0 else "fare_short"] += r["gap"]
    for k in ("billed", "payable", "hold", "claim", "credit", "fare_excess", "fare_short", "open_amount"):
        s[k] = _r(s[k])
    for b in s["status"].values():
        b["amount"], b["sales"] = _r(b["amount"]), _r(b["sales"])
    return s


_ORDER = {NOT_IN_MO: 0, OTHER_VENDOR: 1, FARE_DIFF: 2, MATCHED: 3}


def _sort_key(r: dict) -> tuple:
    weight = r["pay"]["hold"] or abs(r["gap"] or 0.0)
    return (not r["open"], _ORDER[r["status"]], -weight, r["ticket_number"] or "", r["kind"])


def _pick(rows: list[dict], view: str) -> list[dict]:
    if view in STATUSES:
        return [r for r in rows if r["status"] == view]
    if view == "open":
        return [r for r in rows if r["open"]]
    if view == "on_hold":
        return [r for r in rows if r["pay"]["hold"] > 0]
    if view == "claims":
        return [r for r in rows if r["pay"]["claim"] > 0]
    if view == "resolved":
        return [r for r in rows if r["status"] != MATCHED and not r["open"]]
    return rows


def _matches(r: dict, q: str) -> bool:
    sides = [x for x in (r.get("vendor"), r.get("mo")) if x]
    hay = [r.get("ticket_number") or ""] + [str(x.get(k) or "") for x in sides for k in ("pax", "pnr", "ref", "sector")]
    hay += [str(ln.get("ref") or "") for ln in r.get("vendor_lines", []) + r.get("mo_lines", [])]
    return any(q in h.upper() for h in hay)


def _stmt_order(s: recon.Stmt) -> tuple:
    return (s.period_to or date.min, s.uploaded_at or datetime.min)


def options(m: Mapping) -> dict:
    """The vendors that have a statement loaded, and their statements, newest period first."""
    per: dict[str, dict] = defaultdict(lambda: {"open": 0, "hold": 0.0})
    for r in m.rows:
        for b in r["statements"]:
            per[b]["open"] += 1 if r["open"] else 0
            per[b]["hold"] += r["pay"]["hold"]
    stmts = sorted(m.book.stmts.values(), key=_stmt_order, reverse=True)
    n: dict[str, int] = defaultdict(int)
    for s in stmts:
        if s.vendor_key:
            n[s.vendor_key] += 1
    vendors = [{"id": k, "name": v.name, "branch": v.branch, "channels": v.channels, "statements": n[k]}
               for k, v in m.book.vendors.items() if n.get(k)]
    vendors.sort(key=lambda x: (x["name"].upper(), x["branch"] or ""))
    return {
        "vendors": vendors,
        "statements": [{**s.public(), "open": per[s.batch_id]["open"], "hold": _r(per[s.batch_id]["hold"])}
                       for s in stmts],
        "unassigned": sum(1 for s in stmts if not s.vendor_key),
    }


def mo_coverage(book: recon.Book) -> dict:
    days = sorted(d for d in (ln.booked for ln in book.internal) if d)
    return {"tickets": len(book.internal), "statements": len({b for ln in book.internal for b in ln.batches}),
            "from": days[0] if days else None, "to": days[-1] if days else None}


def mapping_view(m: Mapping, *, vendor: Optional[str] = None, statement: Optional[str] = None,
                 view: str = "all", q: Optional[str] = None, offset: int = 0, limit: int = 500) -> dict:
    """What the screen shows: the options, the summary of the lines in scope, the counts of each
    view, and one page of one view. Raises LookupError for a statement that is not loaded."""
    st = m.book.stmts.get(statement) if statement else None
    if statement and st is None:
        raise LookupError(statement)
    vkey = vendor or (st.vendor_key if st else None)
    here = [r for r in m.rows
            if (not vkey or r["vendor_id"] == vkey) and (not statement or statement in r["statements"])]
    summary = summarize(here)
    counts = {v: len(_pick(here, v)) for v in VIEWS}

    picked = sorted(_pick(here, view), key=_sort_key)
    if q and q.strip():
        needle = q.strip().upper()
        picked = [r for r in picked if _matches(r, needle)]
    return {
        "scope": {"vendor": vkey, "statement": statement, "view": view, "q": q or None},
        "options": options(m),
        "mo": mo_coverage(m.book),
        "statement": st.public() if st else None,
        "summary": summary,
        "counts": counts,
        "total": len(picked), "offset": offset, "limit": limit,
        "rows": picked[offset:offset + limit],
    }


async def decide(db: AsyncSession, *, tenant_id: int, user_id: int, keys: list[str], decision: str,
                 note: Optional[str]) -> Mapping:
    """Record one decision on every line in `keys`, with the figures each shows now — looked up
    afresh, never taken from the caller. LookupError: a key is not an open line any more."""
    if decision not in MAPPING_DECISIONS:
        raise MappingError(f"Unknown decision “{decision}”.")
    note = (note or "").strip() or None
    if decision == MAPPING_VENDOR_WRONG and not note:
        raise MappingError("Say what the vendor got wrong — it is what the claim rests on.")
    m = await load(db, tenant_id, user_id)
    by_key = {r["key"]: r for r in m.rows}
    keys = list(dict.fromkeys(keys))      # one upsert cannot touch the same row twice
    gone = [k for k in keys if k not in by_key or by_key[k]["status"] == MATCHED]
    if gone:
        raise LookupError(gone)
    now = datetime.utcnow()
    values = [{
        "tenant_id": tenant_id, "created_by_id": user_id, "item_key": k,
        "ticket_number": by_key[k]["ticket_number"], "kind": by_key[k]["kind"], "status": by_key[k]["status"],
        "decision": decision, "note": note,
        "vendor_fare": by_key[k]["vendor"]["fare"],
        "mo_fare": by_key[k]["mo"]["fare"] if by_key[k]["mo"] else None,
        "vendor_net": by_key[k]["vendor"]["net"],
        "decided_at": now,
    } for k in keys]
    stmt = pg_insert(VendorMappingDecision).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_vendor_mapping_decision_key",
        set_={c: stmt.excluded[c] for c in ("ticket_number", "kind", "status", "decision", "note",
                                            "vendor_fare", "mo_fare", "vendor_net", "decided_at")},
    )
    await db.execute(stmt)
    await db.commit()
    apply_decisions(m.rows, await _decisions(db, tenant_id, user_id))
    return m


async def reopen(db: AsyncSession, *, tenant_id: int, user_id: int, keys: list[str]) -> Mapping:
    """Withdraw the decision on these lines; they are open again."""
    await db.execute(delete(VendorMappingDecision).where(
        VendorMappingDecision.tenant_id == tenant_id, VendorMappingDecision.created_by_id == user_id,
        VendorMappingDecision.item_key.in_(list(dict.fromkeys(keys)))))
    await db.commit()
    return await load(db, tenant_id, user_id)


# ── Vendor Payments: one account per vendor ──────────────────────────────────
def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def stmt_day(s: recon.Stmt) -> Optional[date]:
    """The day a statement bills on — its period's end, else the day it was uploaded."""
    return _day(s.period_to) or _day(s.uploaded_at)


def _bucket(age: int) -> str:
    for lo, hi, label in AGING_BUCKETS:
        if age >= lo and (hi is None or age <= hi):
            return label
    return AGING_BUCKETS[0][2]


def allocate(items: list[dict], payments: list[dict]) -> float:
    """Apply payments, and the credit of any statement that is one, to what is owed — oldest
    first; a payment made against a statement goes to that statement first. Sets each item's
    `paid` and each payment's `applied`; returns what is left over — an advance with the vendor.

    `items` are in date order, each {"ref", "due", "day"} (`ref` a statement's batch id);
    `payments` each {"amount", "day", "statement"}."""
    for it in items:
        it["paid"] = 0.0
    owed = [it for it in items if it["due"] > 0]
    pool: list[list] = []                          # [day, amount left, source]
    for it in items:
        if it["due"] < 0:
            it["credit_used"] = 0.0
            pool.append([it["day"] or date.min, -it["due"], it])
    for p in payments:
        p["applied"] = 0.0
        amount = p["amount"]
        target = next((it for it in owed if p.get("statement") and it["ref"] == p["statement"]), None)
        if target is not None:
            take = min(amount, max(target["due"] - target["paid"], 0.0))
            target["paid"] += take
            p["applied"] += take
            amount -= take
        if amount > 0.005:
            pool.append([p["day"] or date.min, amount, p])
    pool.sort(key=lambda e: e[0])
    for it in owed:
        need = it["due"] - it["paid"]
        for e in pool:
            if need <= 0.005:
                break
            if e[1] <= 0.005:
                continue
            take = min(e[1], need)
            e[1] -= take
            need -= take
            it["paid"] += take
            src = e[2]
            if "applied" in src:
                src["applied"] += take
            else:
                src["credit_used"] = src.get("credit_used", 0.0) + take
    return _r(sum(e[1] for e in pool if "applied" in e[2]))


def _payment_dict(p: VendorPayment) -> dict:
    return {
        "id": p.id, "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        "amount": _r(float(p.amount or 0)), "mode": p.mode, "reference": p.reference, "remarks": p.remarks,
        "statement": p.vendor_batch_id, "status": p.status, "void_reason": p.void_reason,
        "voided_at": p.voided_at.isoformat() if p.voided_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def account(m: Mapping, vendor_key: str, payments: list[VendorPayment], today: date) -> dict:
    """One vendor's account: its statements with what each pays, holds, claims and still owes,
    its payments, the ledger with a running balance, the ageing and the check against the
    balance the vendor printed."""
    book = m.book
    v = book.vendors.get(vendor_key)
    stmts = sorted((s for s in book.stmts.values() if s.vendor_key == vendor_key), key=_stmt_order)
    by_batch = {s.batch_id: s for s in stmts}

    per: dict[str, dict] = {s.batch_id: {"hold": 0.0, "claim": 0.0, "open": 0, "lines": 0, "matched": 0,
                                         "fare_diff": 0, "not_in_mo": 0, "other_vendor": 0} for s in stmts}
    for r in m.rows:
        if r["vendor_id"] != vendor_key:
            continue
        # A ticket's lines on two statements (sold in one week, refunded in the next, compared
        # whole) count on the later one.
        home = max((by_batch[b] for b in r["statements"] if b in by_batch), key=_stmt_order, default=None)
        if home is None:
            continue
        x = per[home.batch_id]
        x["hold"] += r["pay"]["hold"]
        x["claim"] += r["pay"]["claim"]
        x["open"] += 1 if r["open"] else 0
        x["lines"] += 1
        x[r["status"]] += 1

    # The opening balance: the first statement's printed OLD line — what was owed before it.
    first = stmts[0] if stmts else None
    opening = first.opening if first is not None and first.opening is not None else None
    items: list[dict] = []
    if opening:
        items.append({"ref": "opening", "due": opening, "day": _day(first.period_from) or stmt_day(first)})
    for s in stmts:
        x = per[s.batch_id]
        items.append({"ref": s.batch_id, "due": s.billed - x["claim"], "day": stmt_day(s)})
    live = [p for p in payments if p.status == PAYMENT_COMPLETED]
    pays = [{"amount": float(p.amount or 0), "day": p.payment_date, "statement": p.vendor_batch_id, "id": p.id}
            for p in sorted(live, key=lambda p: (p.payment_date, p.id))]
    unapplied = allocate(items, pays)
    by_ref = {it["ref"]: it for it in items}

    statements = []
    aging = {label: 0.0 for _, _, label in AGING_BUCKETS}
    hold_left = 0.0
    oldest: Optional[dict] = None
    for s in stmts:
        x, it = per[s.batch_id], by_ref[s.batch_id]
        due, paid = it["due"], it["paid"]
        balance = due - paid
        approved = s.billed - x["hold"] - x["claim"]
        day = stmt_day(s)
        age = (today - day).days if day else None
        if due < 0:
            state = "credit"
        elif balance <= 0.5:
            state = "paid"
        elif paid > 0.005:
            state = "part_paid"
        else:
            state = "unpaid"
        if balance > 0.005:
            hold_left += min(x["hold"], balance)
            aging[_bucket(max(age or 0, 0))] += balance
            if oldest is None:
                oldest = {"batch_id": s.batch_id, "day": day.isoformat() if day else None, "age": age}
        statements.append({
            **s.public(),
            "day": day.isoformat() if day else None, "age_days": age,
            "billed": _r(s.billed), "hold": _r(x["hold"]), "claim": _r(x["claim"]),
            "approved": _r(approved), "due": _r(due), "paid": _r(paid), "balance": _r(balance),
            "payable_now": _r(max(min(approved - paid, balance), 0.0)) if due > 0 else 0.0,
            "credit_used": _r(it.get("credit_used", 0.0)) if due < 0 else None,
            "state": state, "open": x["open"], "lines_mapped": x["lines"],
            "counts": {k: x[k] for k in STATUSES},
        })
    opening_left = 0.0
    if opening and "opening" in by_ref:
        opening_left = by_ref["opening"]["due"] - by_ref["opening"]["paid"] if opening > 0 else 0.0
        if opening_left > 0.005:
            day = by_ref["opening"]["day"]
            aging[_bucket(max((today - day).days if day else 0, 0))] += opening_left

    billed = sum(s.billed for s in stmts)
    claims = sum(x["claim"] for x in per.values())
    hold = sum(x["hold"] for x in per.values())
    paid = sum(p["amount"] for p in pays)
    balance = (opening or 0.0) + billed - claims - paid

    # The ledger, oldest first: what was billed, claimed and paid, with the balance after each.
    entries: list[dict] = []
    if opening:
        entries.append({"day": by_ref["opening"]["day"], "order": 0, "type": "opening",
                        "label": f"Opening balance — as printed on {first.file_name or 'its first statement'}",
                        "amount": opening})
    for s in stmts:
        day = stmt_day(s)
        entries.append({"day": day, "order": 1, "type": "statement", "batch_id": s.batch_id,
                        "label": f"Billed — {s.file_name or 'statement'}", "period_from": s.public()["period_from"],
                        "period_to": s.public()["period_to"], "amount": s.billed})
        if per[s.batch_id]["claim"]:
            entries.append({"day": day, "order": 2, "type": "claim", "batch_id": s.batch_id,
                            "label": f"Claimed back — vendor wrong on {s.file_name or 'statement'}",
                            "amount": -per[s.batch_id]["claim"]})
    for p in live:
        entries.append({"day": p.payment_date, "order": 3, "type": "payment", "payment_id": p.id,
                        "label": " · ".join(x for x in (f"Paid — {p.mode or 'payment'}", p.reference) if x),
                        "statement": p.vendor_batch_id, "amount": -float(p.amount or 0)})
    entries.sort(key=lambda e: (e["day"] or date.min, e["order"]))
    run = 0.0
    ledger = []
    for e in entries:
        run += e["amount"]
        ledger.append({**{k: e[k] for k in e if k not in ("order", "day", "amount")},
                       "day": e["day"].isoformat() if e["day"] else None,
                       "amount": _r(e["amount"]), "balance": _r(run)})

    # The balance the vendor printed — its latest statement that prints one — against this
    # ledger as at the same day, claims left out (the vendor does not know of them).
    check = None
    printed = [s for s in stmts if s.closing is not None and stmt_day(s)]
    if printed:
        last = printed[-1]
        as_at = stmt_day(last)
        ours = ((opening or 0.0) + sum(s.billed for s in stmts if stmt_day(s) and stmt_day(s) <= as_at)
                - sum(p["amount"] for p in pays if p["day"] and p["day"] <= as_at))
        check = {"as_at": as_at.isoformat(), "statement": last.batch_id, "file_name": last.file_name,
                 "vendor": _r(last.closing), "ours": _r(ours), "difference": _r(last.closing - ours)}

    last_payment = max(live, key=lambda p: (p.payment_date, p.id), default=None)
    return {
        "vendor": {"id": vendor_key, "name": v.name if v else (payments[0].vendor_name if payments else vendor_key),
                   "branch": v.branch if v else None, "channels": v.channels if v else [],
                   "agency_ids": v.agency_ids if v else []},
        "totals": {
            "opening": None if opening is None else _r(opening),
            "billed": _r(billed), "claims": _r(claims), "hold": _r(hold), "paid": _r(paid),
            "balance": _r(balance), "advance": _r(max(-balance, 0.0)),
            "payable_now": _r(max(balance - hold_left, 0.0)),
            "hold_unpaid": _r(hold_left), "unapplied": unapplied,
            "statements": len(stmts), "open": sum(x["open"] for x in per.values()),
        },
        "aging": [{"bucket": label, "amount": _r(aging[label])} for _, _, label in AGING_BUCKETS],
        "oldest_due": oldest,
        "last_payment": _payment_dict(last_payment) if last_payment else None,
        "statements": statements,
        "payments": [_payment_dict(p) for p in sorted(payments, key=lambda p: (p.payment_date, p.id), reverse=True)],
        "ledger": ledger,
        "check": check,
    }


async def payments_of(db: AsyncSession, tenant_id: int, user_id: int,
                      vendor_key: Optional[str] = None) -> list[VendorPayment]:
    q = select(VendorPayment).where(VendorPayment.tenant_id == tenant_id, VendorPayment.created_by_id == user_id,
                                    VendorPayment.vendor_key.is_not(None))
    if vendor_key is not None:
        q = q.where(VendorPayment.vendor_key == vendor_key)
    return list((await db.execute(q.order_by(VendorPayment.payment_date, VendorPayment.id))).scalars().all())


def accounts(m: Mapping, payments: list[VendorPayment], today: date) -> dict:
    """Every vendor with a statement loaded or a payment recorded — its account in one line."""
    by_vendor: dict[str, list[VendorPayment]] = defaultdict(list)
    for p in payments:
        by_vendor[p.vendor_key].append(p)
    keys = {s.vendor_key for s in m.book.stmts.values() if s.vendor_key} | set(by_vendor)
    out = []
    for k in keys:
        a = account(m, k, by_vendor.get(k, []), today)
        out.append({**a["vendor"], **a["totals"], "aging": a["aging"], "oldest_due": a["oldest_due"],
                    "last_payment": a["last_payment"], "check": a["check"]})
    out.sort(key=lambda x: (-(x["balance"] if x["balance"] > 0 else 0), (x["name"] or "").upper()))
    totals = {k: _r(sum(x[k] for x in out)) for k in ("billed", "claims", "hold", "paid", "balance",
                                                       "payable_now", "advance")}
    aging = {label: 0.0 for _, _, label in AGING_BUCKETS}
    for x in out:
        for b in x["aging"]:
            aging[b["bucket"]] += b["amount"]
    return {
        "as_of": today.isoformat(),
        "vendors": out,
        "totals": totals,
        "aging": [{"bucket": label, "amount": _r(aging[label])} for _, _, label in AGING_BUCKETS],
        "unassigned_statements": sum(1 for s in m.book.stmts.values() if not s.vendor_key),
    }


async def record_payment(db: AsyncSession, *, tenant_id: int, user_id: int, book: recon.Book, vendor_key: str,
                         payment_date: date, amount: Decimal, mode: str, reference: Optional[str],
                         remarks: Optional[str], statement: Optional[str], today: date) -> VendorPayment:
    """A payment made to a vendor's account. MappingError on a refused request."""
    v = book.vendors.get(vendor_key)
    own = {s.batch_id for s in book.stmts.values() if s.vendor_key == vendor_key}
    if v is None and not own:
        raise MappingError("This vendor has no statement loaded and is not in Agency Master.")
    if amount is None or amount <= 0:
        raise MappingError("Enter the amount paid.")
    if amount >= Decimal("1e12"):
        raise MappingError("That amount is too large.")
    if payment_date > today:
        raise MappingError("A payment is recorded once it is made — the date cannot be in the future.")
    if mode not in PAYMENT_MODES:
        raise MappingError(f"Payment mode must be one of {', '.join(PAYMENT_MODES)}.")
    reference = (reference or "").strip() or None
    if mode in BANK_MODES and not reference:
        raise MappingError(f"Enter the {'cheque number' if mode == 'Cheque' else 'UTR / bank reference'} — "
                           f"it is how this payment is traced in the bank statement.")
    if statement and statement not in own:
        raise MappingError("That statement is not one of this vendor's.")
    if reference:
        twin = (await db.execute(select(VendorPayment).where(
            VendorPayment.tenant_id == tenant_id, VendorPayment.created_by_id == user_id,
            VendorPayment.vendor_key == vendor_key, VendorPayment.status != PAYMENT_VOIDED,
            func.upper(VendorPayment.reference) == reference.upper(),
        ).limit(1))).scalar_one_or_none()
        if twin is not None:
            raise MappingError(f"A payment with reference {reference} is already recorded for this vendor "
                               f"(₹{float(twin.amount):,.2f} on {twin.payment_date:%d %b %Y}). "
                               f"Void that one first if it was entered wrong.")
    payment = VendorPayment(
        tenant_id=tenant_id, created_by_id=user_id,
        vendor_key=vendor_key, vendor_name=v.name if v else None,
        agency_id=(v.agency_ids[0] if v and v.agency_ids else None),
        supplier_name=v.name if v else None,
        vendor_batch_id=statement, payment_date=payment_date, amount=amount, mode=mode,
        reference=reference, remarks=(remarks or "").strip() or None, items_count=0,
        status=PAYMENT_COMPLETED, created_at=datetime.utcnow(),
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment
