"""BSP Detailed / BSP Summary → Combined rows and detail sheets.

WHY BSP IS WRITTEN AS STORED. A BSP statement is the settlement document itself: the
parser keeps every printed sign (``(x)``, ``DR``, a trailing ``-``), a card-paid issue
legitimately prints a NEGATIVE balance, a refund with a retained penalty prints a negative
fare and tax next to a positive penalty, and a negative SPDR is spread as negative CANX
units. Forcing ``abs × type sign`` (as the GDS/aggregator sources need) would silently
rewrite money the agency actually remitted, so no BSP amount is ever re-signed here — the
checks below only FLAG rows whose printed components disagree.

Two readings a maintainer must keep:

* ``penalty_amount`` already IS the sum of the row's PENALTY breakups (``bsp_pdf_parser``
  accumulates it while emitting them), so the breakups are never added again, and the
  tax pivot excludes PENALTY. ``K3`` is GST on fare; ``IN`` is India's UDF and never K3.
* A CANX covered by a distributed SPDR has ``document_number`` rewritten to the SPDR's
  (``workers/bsp_tasks._distribute_spdr_canx``); the printed cancelled ticket survives only
  in ``ticket_number``, which is therefore the document the row is about.

The BSP Summary PDF restates the detailed totals, so it never feeds Combined (that would
double count) — only its detail sheet lives here, with the frontend's line-kind reading so a
user totalling the sheet knows which lines to add.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from app.services.report_download import columns as C
from app.services.report_download import normalize as N
from app.services.report_download.mappers.base import DetailCol, attr, provenance_cols, row_ref as _ref
from app.services.report_download.types import LinkResult, MapCtx

SOURCE_KEYS: tuple[str, ...] = ("bsp", "bsp-summary")

BSP_TABLE = "bsp_statement_rows"
SUMMARY_TABLE = "bsp_summary_rows"
SOURCE_LABEL = "BSP"          # registry.SOURCES["bsp"].label

#: Detail sheet: at most this many ``Tax <CODE>`` columns; the rest share ``Tax (other codes)``.
TAX_PIVOT_CAP = 80
#: ``ctx.extra_keys`` sentinel the builder passes when a legacy Excel statement is included.
LEGACY_KEY = "__legacy__"

GROSS_TOLERANCE = Decimal("1.00")

# Summary line kinds (frontend BspGroupDetail.tsx::groupSummaryRows).
LINE_FOP = "FOP line"
LINE_TOTAL = "Airline TOTAL"
LINE_SINGLE = "Single line"

_CANX_TYPES = frozenset({"CANX", "CANN"})
_TIE_OUT_KEYWORDS = ("ISSUE", "REFUND", "DEBIT", "CREDIT")      # workers/bsp_tasks._SECTION_BUCKETS order
_LEGACY_MONEY = ("gross", "commission", "adm", "acm", "refund", "net_due")
_GROSS_CHECKED = frozenset({C.SALE, C.REFUND, C.EXCHANGE})
_PAX_ONE = frozenset({C.SALE, C.EXCHANGE, C.REFUND})
_PAX_ZERO = frozenset({C.EMD, C.ADM, C.ACM, C.AGENT_FEE})
_ISSUE_ANCHORED_TRAVEL = frozenset({C.SALE, C.EXCHANGE, C.EMD})


# ── small readers ────────────────────────────────────────────────────────────

def _json(v: Any) -> Any:
    """JSONB read through a raw ``text()`` query arrives as text; decode it once."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def _as_dict(v: Any) -> dict:
    v = _json(v)
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list:
    v = _json(v)
    if isinstance(v, (list, tuple)):
        return list(v)
    return [] if v is None else [v]


def _doc_of(entry: Any) -> Optional[str]:
    """``{"doc": …}`` (parser shape) or a bare document string."""
    return N.clean_text(entry.get("doc") if isinstance(entry, dict) else entry)


def _assoc_rtdn(row: Any) -> Optional[str]:
    return _doc_of(_as_dict(getattr(row, "associated_docs", None)).get("rtdn"))


def _exchange_docs(row: Any) -> list[str]:
    docs = (_doc_of(e) for e in _as_list(_as_dict(getattr(row, "associated_docs", None)).get("exchanges")))
    return [d for d in docs if d]


def _raw(row: Any) -> dict:
    return _as_dict(getattr(row, "raw_data", None))


def _d(row: Any, name: str) -> Optional[Decimal]:
    return N.D(getattr(row, name, None))


def _coalesce(*vals: Any) -> Any:
    return next((v for v in vals if v is not None), None)


def _upper(v: Any) -> Optional[str]:
    s = N.clean_text(v)
    return s.upper() if s else None


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().upper() in ("TRUE", "YES", "Y", "1", "*")
    return bool(v)


def _join(values: Iterable[Any], sep: str = ", ") -> Optional[str]:
    return N.join_unique(values, sep)


def _period_text(pf: Any, pt: Any) -> Optional[str]:
    fmt = lambda d: d.strftime("%d-%b-%Y") if isinstance(d, date) else N.clean_text(d)  # noqa: E731
    a, b = fmt(pf) if pf else None, fmt(pt) if pt else None
    if a and b:
        return a if a == b else f"{a} – {b}"
    return a or b


def statement_period(header: Any) -> Optional[str]:
    """``01-Jul-2026 – 15-Jul-2026`` for a BspStatement / BspSummaryStatement header."""
    return _period_text(getattr(header, "period_from", None), getattr(header, "period_to", None))


def _component(t: Any, name: str) -> Any:
    return t.get(name) if isinstance(t, dict) else getattr(t, name, None)


# ── tax breakups ─────────────────────────────────────────────────────────────

def tax_pivot(taxes: Optional[Iterable[Any]]) -> dict[str, Decimal]:
    """TAX + FEE amount per upper-cased component code. PENALTY (already in
    ``penalty_amount``), BASE_FARE and COMMISSION components are excluded; a code with no
    readable amount is absent, so a blank pivot cell stays blank instead of 0."""
    out: dict[str, Decimal] = {}
    for t in taxes or ():
        if _upper(_component(t, "component_type")) not in ("TAX", "FEE"):
            continue
        code, amt = _upper(_component(t, "component_code")), N.D(_component(t, "amount"))
        if code is None or amt is None:
            continue
        out[code] = out[code] + amt if code in out else amt
    return out


def tax_type_sums(taxes: Optional[Iterable[Any]]) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """``(TAX total, FEE total)`` — each None when the row has no such component."""
    tax: Optional[Decimal] = None
    fee: Optional[Decimal] = None
    for t in taxes or ():
        ctype = _upper(_component(t, "component_type"))
        if ctype not in ("TAX", "FEE"):
            continue
        amt = N.D(_component(t, "amount"))
        if amt is None:
            continue
        if ctype == "TAX":
            tax = amt if tax is None else tax + amt
        else:
            fee = amt if fee is None else fee + amt
    return tax, fee


# ── identity helpers (also used by the builder / linking) ────────────────────

def bsp_row_ref(row: Any) -> str:
    return _ref(BSP_TABLE, getattr(row, "id", None))


def summary_row_ref(row: Any) -> str:
    return _ref(SUMMARY_TABLE, getattr(row, "id", None))


def bsp_code(row: Any) -> Optional[str]:
    """The row's 3-digit accounting code. Legacy Excel rows may carry it only in
    ``airline_code``; an alphabetic designator there is not an accounting code."""
    code = N.zfill3(getattr(row, "airline_accounting_code", None))
    if code is None:
        alt = N.zfill3(getattr(row, "airline_code", None))
        if alt is not None and alt.isdigit():
            code = alt
    return code


def bsp_canon(row: Any) -> tuple[str, bool]:
    """``(canonical type, legacy)``. Legacy is also a row with no parsed financials but
    legacy Excel money columns — a legacy file may carry upper-case type text."""
    canon, legacy = N.canon_bsp_txn(getattr(row, "transaction_type", None),
                                     getattr(row, "associated_docs", None))
    if (not legacy and getattr(row, "transaction_amount", None) is None
            and getattr(row, "fare_amount", None) is None
            and any(getattr(row, f, None) is not None for f in _LEGACY_MONEY)):
        legacy = True
    return canon, legacy


def _related_raw(row: Any) -> Optional[str]:
    return (N.clean_text(getattr(row, "rtdn", None)) or _assoc_rtdn(row)
            or next(iter(_exchange_docs(row)), None))


def bsp_natural_key(row: Any) -> tuple:
    """DuplicateTracker key (design §C.10): the same settlement line in two uploads."""
    raw_doc = N.clean_text(getattr(row, "document_number", None))
    key = N.doc_key(bsp_code(row), raw_doc)
    return (
        N.pack(key) if key is not None else raw_doc,
        bsp_canon(row)[0],
        N.D(getattr(row, "transaction_amount", None)),
        N.parse_report_date(getattr(row, "issue_date", None)),
    )


def tie_out_section(row: Any) -> Optional[str]:
    """ISSUE / REFUND / DEBIT / CREDIT grand-total line of a row, else None.

    Same rule as ``api/v1/bsp.py::bsp_detailed_summary``: ``coalesce(settlement_section,
    section)`` (so a CANX carrying a distributed SPDR charge totals under the SPDR's DEBIT
    MEMOS), keyword matched case-insensitively, first keyword in worker order wins.
    """
    raw = _raw(row)
    sec = raw.get("settlement_section")
    if sec is None:
        sec = raw.get("section")
    sec = str(sec).upper() if sec is not None else ""
    return next((kw for kw in _TIE_OUT_KEYWORDS if kw in sec), None)


# ── Combined row ─────────────────────────────────────────────────────────────

def _pax_count(canon: str, ticket: Optional[str]) -> int:
    """1 per passenger ticket the document concerns, 0 for documents that are not a
    passenger's ticket (EMD, memos, TASF). CANCELLATION / VOID / UNKNOWN concern the
    ticket they name: 1 when one is printed, else 0. Transaction Type is the filter — a
    count column never goes negative (design review, "minor: Pax Count")."""
    if canon in _PAX_ONE:
        return 1
    if canon in _PAX_ZERO:
        return 0
    return 1 if ticket else 0


def to_common(
    source_key: str,
    row: Any,
    ctx: MapCtx,
    link: Optional[LinkResult] = None,
    *,
    tgq: tuple[Any, Optional[str]] = (None, None),
    **extra: Any,
) -> dict[str, Any]:
    """One BSP Detailed row → Combined dict (design §B.4, BSP column).

    ``tgq`` is ``(TgqTicket | None, match method | None)`` from ``TgqIndex.match``.
    """
    if source_key != "bsp":
        raise ValueError(f"mappers.bsp.to_common does not map {source_key!r} "
                         "(the BSP Summary never feeds Combined)")
    header = ctx.upload.header
    sm = ctx.upload.summary_header
    out = C.new_common_row(ctx, category=C.CAT_BSP, source_type=SOURCE_LABEL, row_ref=bsp_row_ref(row))
    raw = _raw(row)
    ttype = _upper(getattr(row, "transaction_type", None))
    canon, legacy = bsp_canon(row)
    code = bsp_code(row)

    # ── parties ──
    agent_name = N.clean_text(getattr(sm, "agent_name", None))
    info = ctx.airlines.numeric(code) if code else None
    alpha = N.zfill3(getattr(row, "airline_code", None))
    if info is None and alpha and not alpha.isdigit():
        info = ctx.airlines.iata(alpha)
    out.update(
        settled_with=f"BSP – {agent_name}" if agent_name else "BSP",
        agent_signon=N.clean_text(getattr(sm, "agent_code", None)),
        airline_numeric=code or (info.numeric_code if info else None),
        airline_code=(info.iata_code if info else None) or (alpha if alpha and not alpha.isdigit() else None),
        airline_name=N.clean_text(getattr(row, "airline_name", None)) or (info.name if info else None),
        product=C.PRODUCT_AIR,
    )

    # ── document ──
    spdr_no = N.clean_text(getattr(row, "spdr_no", None))
    ticket_raw = N.clean_text(getattr(row, "ticket_number", None))
    doc_raw = N.clean_text(getattr(row, "document_number", None))
    ticket_src = ticket_raw
    if ticket_src is None and canon == C.REFUND:
        # RFND/RFDA refund notices numbered 00…/40… carry no ticket; the RTDN is the ticket.
        ticket_src = N.clean_text(getattr(row, "rtdn", None)) or _assoc_rtdn(row)
    ticket, nonstandard = N.ticket13(code, ticket_src)
    if ttype in _CANX_TYPES and spdr_no:
        document, related = ticket_raw or doc_raw, spdr_no
    else:
        document, related = doc_raw, N.ticket13(code, _related_raw(row))[0]
    out.update(
        transaction_type=canon,
        source_txn_type=N.clean_text(getattr(row, "transaction_type", None)),
        document_number=document,
        ticket_number=ticket,
        related_document=related,
        pax_count=_pax_count(canon, ticket),
    )
    if nonstandard:
        C.add_flag(out, "TICKET_NO_NONSTANDARD")
    if legacy:
        C.add_flag(out, "LEGACY_BSP_EXCEL")
    if canon == C.UNKNOWN:
        C.add_flag(out, "TXN_UNMAPPED")

    # ── dates / itinerary ──
    row_issue = N.parse_report_date(getattr(row, "issue_date", None))
    issue = row_issue
    if issue is None:
        issue = N.parse_report_date(getattr(header, "period_from", None))
        C.add_flag(out, "ISSUE_DATE_FALLBACK" if issue is not None else "DATE_UNREADABLE")
    period = statement_period(header)
    bpc = N.clean_text(getattr(sm, "billing_period_code", None))
    tours = [t for t in (N.clean_text(x) for x in _as_list(getattr(row, "tour", None))) if t]
    out.update(
        issue_date=issue,
        settlement_period=(f"{period} ({bpc})" if period and bpc else period or bpc),
        dom_intl=N.stat_segment(getattr(row, "stat", None)),
        tour_code=tours[0] if tours else None,
        form_of_payment=N.clean_text(getattr(row, "form_of_payment", None)),
    )
    _enrich(out, row, ctx, canon, row_issue, tgq)

    # ── money: as stored ──
    currency = _upper(getattr(sm, "currency", None))
    if currency is None:
        currency = "INR"
        C.add_flag(out, "CURRENCY_ASSUMED")
    taxes = getattr(row, "taxes", None) or ()
    px = tax_pivot(taxes)
    tax, fee = tax_type_sums(taxes)
    total_taxes = N.dsum(tax, fee)
    yq, yr, k3 = px.get("YQ"), px.get("YR"), px.get("K3")
    other = None
    if total_taxes is not None:
        other = total_taxes - (yq or 0) - (yr or 0) - (k3 or 0)
        if other * total_taxes < 0:
            C.add_flag(out, "NEG_TAX_RESIDUAL")
    fare = _d(row, "fare_amount")
    txn = _d(row, "transaction_amount")
    penalty = _d(row, "penalty_amount")
    out.update(
        currency=currency,
        base_fare=_coalesce(fare, _d(row, "gross")),
        yq=yq, yr=yr, k3=k3, other_taxes=other, total_taxes=total_taxes,
        gross_amount=_coalesce(txn, _d(row, "gross")),
        penalty=penalty,
        ancillary=txn if canon == C.EMD else None,
        service_fee=N.magnitude(txn) if canon == C.AGENT_FEE else None,
        commission=_coalesce(_d(row, "standard_commission_amount"), _d(row, "commission")),
        supp_commission=_d(row, "supplier_discount_amount"),
        tax_on_commission=_d(row, "tax_on_commission"),
        net_payable=_coalesce(_d(row, "balance_payable"), _d(row, "net_due")),
    )
    # Printed signs, printed sums: a refund's −fare −tax +penalty must equal its −txn.
    if canon in _GROSS_CHECKED and fare is not None and txn is not None:
        if abs(fare + (tax or 0) + (fee or 0) + (penalty or 0) - txn) > GROSS_TOLERANCE:
            C.add_flag(out, "GROSS_COMPONENTS_MISMATCH")

    # ── SPDR / STAT breadcrumbs ──
    if ttype in _CANX_TYPES and (spdr_no or "spdr_split" in raw
                                 or "settlement_section" in raw or "settlement_category" in raw):
        C.add_flag(out, "SPDR_DISTRIBUTED")
    if ttype == "SPDR" and raw.get("spdr_split"):
        C.add_flag(out, "SPDR_ZEROED")
    if _truthy(raw.get("stat_amended")):
        C.add_flag(out, "STAT_AMENDED")

    out["counts_in_net"] = C.NET_YES
    return C.apply_link(out, link)


def _enrich(out: dict, row: Any, ctx: MapCtx, canon: str, row_issue: Optional[date],
            tgq: tuple[Any, Optional[str]]) -> None:
    """Passenger / PNR / itinerary from the live TGQ match, else the values the last
    commission run stored on the row (flagged, because that TGQ upload may be gone)."""
    ticket, method = (tuple(tgq) + (None, None))[:2] if tgq else (None, None)
    stored_sector = N.clean_text(getattr(row, "enriched_sector", None))
    stored_class = N.clean_text(getattr(row, "enriched_booking_class", None))
    stored_travel = N.parse_report_date(getattr(row, "enriched_travel_date", None))
    stored_src = N.clean_text(getattr(row, "enriched_travel_date_source", None))
    used_stored = False

    if ticket is not None:
        travel, src = ticket.resolve_travel(row_issue if canon in _ISSUE_ANCHORED_TRAVEL else None)
        sector = N.clean_text(ticket.sector)
        klass = N.clean_text(ticket.booking_class)
        if sector is None and stored_sector:
            sector, used_stored = stored_sector, True
        if klass is None and stored_class:
            klass, used_stored = stored_class, True
        if travel is None and stored_travel is not None:
            travel, src, used_stored = stored_travel, stored_src, True
        m = N.clean_text(method) or "match"
        file_name = ctx.tgq_files.get(ticket.batch_id) if ticket.batch_id else None
        out.update(
            passenger_name=N.clean_text(ticket.pax_name),
            airline_pnr=N.clean_text(ticket.air_pnr),
            gds_ref=N.clean_text(ticket.gal_pnr),
            flight_no=N.clean_text(ticket.flight_numbers),
            fare_basis=N.clean_text(ticket.fare_basis),
            sector=sector, booking_class=klass, travel_date=travel,
            tgq_enriched=f"Yes ({m})",
            linked_via=f"TGQ HMPR {m} ({file_name})" if file_name else f"TGQ HMPR {m}",
        )
    else:
        travel, src = stored_travel, stored_src
        used_stored = bool(stored_sector or stored_class or stored_travel is not None)
        out.update(sector=stored_sector, booking_class=stored_class, travel_date=stored_travel,
                   tgq_enriched="No")
    if used_stored:
        C.add_flag(out, "TGQ_ENRICH_STORED")
    if travel is not None and (src or "").lower() == "inferred":
        C.add_flag(out, "TRAVEL_YEAR_INFERRED")


# ── BSP Summary line kinds ───────────────────────────────────────────────────

def summary_line_kinds(rows: Iterable[Any]) -> dict[Any, tuple[str, bool]]:
    """``{row.id: (line kind, use for totals)}`` — port of the frontend's
    ``BspGroupDetail.tsx::groupSummaryRows``.

    Lines group by (category, airline_code ?? airline_name). An airline printed with several
    FOP lines has a TOTAL line that restates them: the TOTAL (else the first line carrying a
    balance, else the last line) is the ``Airline TOTAL`` used for totals and the others are
    ``FOP line`` s not to be added again. A lone line already is the airline's total.
    """
    groups: dict[tuple[str, Any], list[Any]] = {}
    for r in rows:
        cat = getattr(r, "category", None)
        code = getattr(r, "airline_code", None)
        ident = code if code is not None else getattr(r, "airline_name", None)
        key = ("" if cat is None else str(cat), "" if ident is None else str(ident))
        groups.setdefault(key, []).append(r)

    out: dict[Any, tuple[str, bool]] = {}
    for members in groups.values():
        if len(members) == 1:
            out[members[0].id] = (LINE_SINGLE, True)
            continue
        total = (next((r for r in members if (getattr(r, "fop", None) or "").upper() == "TOTAL"), None)
                 or next((r for r in members if getattr(r, "balance_payable", None) is not None), None)
                 or members[-1])
        for r in members:
            out[r.id] = (LINE_TOTAL, True) if r is total else (LINE_FOP, False)
    return out


# ── detail sheets ────────────────────────────────────────────────────────────

def _money(name: str) -> Any:
    return lambda row, ctx: _d(row, name)


def _raw_key(name: str) -> Any:
    def _get(row: Any, ctx: MapCtx) -> Any:
        v = _raw(row).get(name)
        return v if v is None or isinstance(v, (str, int, float, Decimal)) else json.dumps(v, default=str)
    return _get


def _spdr_split_text(row: Any, ctx: MapCtx) -> Optional[str]:
    split = _raw(row).get("spdr_split")
    if not split:
        return None
    if isinstance(split, dict) and {"amount", "count", "unit"} <= split.keys():
        return f"{split['amount']} split into {split['count']} × {split['unit']}"
    return json.dumps(split, default=str, sort_keys=True)


class _TaxView:
    """Pivot + type sums of the row being written, computed once per row for all of its
    (up to 80+) tax columns. Holds the row itself, so ``is`` can never match a new row that
    reused a freed row's id."""
    __slots__ = ("_row", "_pivot", "_sums")

    def __init__(self) -> None:
        self._row: Any = None
        self._pivot: dict[str, Decimal] = {}
        self._sums: tuple[Optional[Decimal], Optional[Decimal]] = (None, None)

    def _load(self, row: Any) -> None:
        if self._row is not row:
            taxes = getattr(row, "taxes", None) or ()
            self._row, self._pivot, self._sums = row, tax_pivot(taxes), tax_type_sums(taxes)

    def pivot(self, row: Any) -> dict[str, Decimal]:
        self._load(row)
        return self._pivot

    def sums(self, row: Any) -> tuple[Optional[Decimal], Optional[Decimal]]:
        self._load(row)
        return self._sums


def _bsp_detail_columns(ctx: MapCtx) -> list[DetailCol]:
    tv = _TaxView()
    cols = provenance_cols(bsp_row_ref) + [
        DetailCol("Statement Period", lambda row, c: statement_period(c.upload.header), "text", 24),
        DetailCol("Document #", attr("document_number"), "text", 14),
        DetailCol("Ticket No", attr("ticket_number"), "text", 14),
        DetailCol("Txn", attr("transaction_type"), "text", 7),
        DetailCol("Air", attr("airline_accounting_code"), "text", 6),
        DetailCol("Airline", attr("airline_name"), "text", 22),
        DetailCol("Issue Date", attr("issue_date"), "date", 12),
        DetailCol("CPUI", attr("cpui"), "text", 7),
        DetailCol("NR", attr("nr_code"), "text", 7),
        DetailCol("STAT", attr("stat"), "text", 6),
        DetailCol("FOP", attr("form_of_payment"), "text", 6),
        DetailCol("Txn Amt", _money("transaction_amount"), "money", 12),
        DetailCol("Fare", _money("fare_amount"), "money", 12),
        DetailCol("Tax (TAX)", lambda row, c: tv.sums(row)[0], "money", 11),
        DetailCol("F&C (FEE)", lambda row, c: tv.sums(row)[1], "money", 11),
        DetailCol("Pen", _money("penalty_amount"), "money", 10),
        DetailCol("Net Sales", _money("net_sales"), "money", 12),
        DetailCol("Std %", _money("standard_commission_rate"), "text", 7),
        DetailCol("Std Comm", _money("standard_commission_amount"), "money", 11),
        DetailCol("Supp %", _money("supplier_discount_rate"), "text", 7),
        DetailCol("Supp Disc", _money("supplier_discount_amount"), "money", 11),
        DetailCol("Tax/Comm", _money("tax_on_commission"), "money", 10),
        DetailCol("Balance", _money("balance_payable"), "money", 12),
        DetailCol("Tour", lambda row, c: _join(_as_list(getattr(row, "tour", None))), "text", 14),
        DetailCol("Alt Docs", lambda row, c: _join(_as_list(getattr(row, "alt_document_numbers", None))), "text", 14),
        DetailCol("SPDR No", attr("spdr_no"), "text", 12),
        DetailCol("RTDN", attr("rtdn"), "text", 12),
        DetailCol("Assoc RTDN", lambda row, c: _assoc_rtdn(row), "text", 12),
        DetailCol("Exchanges", lambda row, c: _join(_exchange_docs(row)), "text", 14),
        DetailCol("ESAC", attr("esac"), "text", 14),
        DetailCol("WAVR", attr("wavr"), "text", 10),
        DetailCol("Section", _raw_key("section"), "text", 12),
        DetailCol("Category", _raw_key("category"), "text", 12),
        DetailCol("Settlement Section", _raw_key("settlement_section"), "text", 14),
        DetailCol("Settlement Category", _raw_key("settlement_category"), "text", 14),
        DetailCol("SPDR Split", _spdr_split_text, "text", 20),
        DetailCol("Stat Amended", lambda row, c: "Yes" if _truthy(_raw(row).get("stat_amended")) else None, "text", 8),
        DetailCol("Match Status", attr("match_status"), "text", 11),
        DetailCol("Commission Status", attr("commission_status"), "text", 12),
        DetailCol("Calculated Incentive", _money("calculated_incentive"), "money", 12),
        DetailCol("Matched Deal", attr("matched_deal_name"), "text", 20),
        DetailCol("Enriched Sector", attr("enriched_sector"), "text", 16),
        DetailCol("Enriched Class", attr("enriched_booking_class"), "text", 8),
        DetailCol("Enriched Travel Date", attr("enriched_travel_date"), "date", 12),
        DetailCol("Enrichment Ref", attr("enrichment_ref"), "text", 20),
    ]

    codes = [c for c in dict.fromkeys(_upper(x) for x in ctx.tax_codes) if c]
    shown, rest = codes[:TAX_PIVOT_CAP], codes[TAX_PIVOT_CAP:]
    for code in shown:
        cols.append(DetailCol(f"Tax {code}", (lambda k: lambda row, c: tv.pivot(row).get(k))(code), "money", 9))
    if rest:
        shown_set = frozenset(shown)

        def _other(row: Any, c: MapCtx) -> Optional[Decimal]:
            return N.dsum(*(v for k, v in tv.pivot(row).items() if k not in shown_set))
        cols.append(DetailCol("Tax (other codes)", _other, "money", 11))

    if LEGACY_KEY in ctx.extra_keys:
        for header, name in (("Gross", "gross"), ("Commission", "commission"), ("ADM", "adm"),
                             ("ACM", "acm"), ("Refund", "refund"), ("Net Due", "net_due")):
            cols.append(DetailCol(header, _money(name), "money", 12))
    return cols


def _summary_detail_columns(ctx: MapCtx) -> list[DetailCol]:
    """``bsp_export._SUMMARY_HEADERS`` + header context + line kind.

    Line Kind / Use For Totals are read from ``row.line_kind`` / ``row.use_for_totals``,
    which the BUILDER sets from ``summary_line_kinds(all rows of the statement)`` — a single
    row cannot know its siblings, so the grouping has to be computed over the whole upload
    first (blank when the builder did not set them).
    """
    head = lambda name: (lambda row, c: getattr(c.upload.header, name, None))  # noqa: E731

    def _use(row: Any, c: MapCtx) -> Optional[str]:
        v = getattr(row, "use_for_totals", None)
        return None if v is None else ("Y" if v else "N")

    return provenance_cols(summary_row_ref) + [
        DetailCol("Category", attr("category"), "text", 14),
        DetailCol("Airline Code", attr("airline_code"), "text", 8),
        DetailCol("IATA", attr("airline_iata"), "text", 6),
        DetailCol("Airline", attr("airline_name"), "text", 24),
        DetailCol("FOP", attr("fop"), "text", 8),
        DetailCol("Issues", _money("issues"), "money", 13),
        DetailCol("Refunds", _money("refunds"), "money", 13),
        DetailCol("Debit Memos", _money("debit_memos"), "money", 13),
        DetailCol("Credit Memos", _money("credit_memos"), "money", 13),
        DetailCol("Std Comm", _money("std_comm"), "money", 12),
        DetailCol("Sup Comm", _money("sup_comm"), "money", 12),
        DetailCol("Tax on Comm", _money("tax_on_comm"), "money", 12),
        DetailCol("Balance Payable", _money("balance_payable"), "money", 14),
        DetailCol("Docs", attr("doc_count"), "int", 7),
        DetailCol("Agent Code", head("agent_code"), "text", 10),
        DetailCol("Agent", head("agent_name"), "text", 24),
        DetailCol("Period", lambda row, c: statement_period(c.upload.header), "text", 24),
        DetailCol("Billing Period Code", head("billing_period_code"), "text", 10),
        DetailCol("Currency", head("currency"), "text", 8),
        DetailCol("Match Status", head("match_status"), "text", 10),
        DetailCol("Line Kind", attr("line_kind"), "text", 13),
        DetailCol("Use For Totals", _use, "text", 8),
    ]


def detail_columns(source_key: str, ctx: MapCtx) -> list[DetailCol]:
    """``BSP Detailed`` / ``BSP Summary`` sheet columns (design §A). Values as stored;
    money as Decimal, blank as None. ``raw_data`` itself is never exported."""
    if source_key == "bsp":
        return _bsp_detail_columns(ctx)
    if source_key == "bsp-summary":
        return _summary_detail_columns(ctx)
    raise ValueError(f"mappers.bsp has no detail sheet for {source_key!r}")
