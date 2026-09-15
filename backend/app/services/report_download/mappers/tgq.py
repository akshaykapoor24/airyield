"""TGQ HMPR → Combined rows (one per TICKET) and the TGQ detail sheet (one row per LEG).

Ingest expands every HMPR line into one row per flown sector and allocates the money across
the legs (``sector_split.split_row``), so the table no longer holds what the file said about a
ticket. A report has to put the ticket back together, and three facts about that allocation
decide how:

* ``allocate`` divides a value only when it reads as a plain number (commas aside). ``₹1,234``
  or ``1234 INR`` is COPIED onto every leg, so summing the legs would print the amount three
  times on a three-sector ticket. The sum is only taken when every leg passes the allocator's
  own test (``sector_split._NUMERIC_RE``); otherwise the first leg — which then holds the
  whole value — is shown and the row is flagged ``TGQ_MONEY_UNSPLIT``.
* Only the spec's ``divide_fields`` are allocated. Any other field is a verbatim copy on each
  leg and must never be summed.
* ``orig_data`` / ``orig_taxes`` hold the pre-split line verbatim whenever ingest altered it,
  so they win over any reconstruction. A batch imported before splitting existed
  (``sector_count IS NULL``) is still one row per ticket and is read as it stands.

Signs: TGQ is TYPE_SIGNED (``normalize.signed``) — HMPR prints refund amounts as magnitudes.
Membership in BSP is NOT decided here: ``to_common`` defaults Counts In Net to "not in BSP" and
``linking.decide_tgq`` overrides it through the ``LinkResult``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Iterator, Optional

from app.services import sector_split
from app.services import statement_display
from app.services import statement_spec as spec
from app.services.bsp_tgq_enrichment import distinct_classes, journey_chain, resolve_travel_date
from app.services.report_download import columns as C
from app.services.report_download import normalize as N
from app.services.report_download import pii
from app.services.report_download.mappers.base import DetailCol, provenance_cols, row_ref
from app.services.report_download.types import DocKey, LinkResult, MapCtx

__all__ = [
    "SOURCE_KEYS", "TgqFold", "TgqLegGrouper",
    "fold_tgq_ticket", "fold_money", "fold_taxes", "tgq_canon", "tgq_issue_date",
    "tgq_group_key", "iter_folds", "tgq_row_ref", "tgq_natural_key",
    "to_common", "detail_columns",
]

SOURCE_KEYS: tuple[str, ...] = ("tgq-hmpr",)
_SLUG = "tgq-hmpr"
_TABLE = "tgq_hmpr"
_SOURCE_TYPE = "TGQ HMPR"
SETTLED_WITH = "Not settled – GDS record"
NOT_IN_BSP_UNKNOWN = "Unknown – no ticket no."

_TOTAL_ROW_CFG = spec.total_row_config(_SLUG)
_DIVIDE_FIELDS: frozenset[str] = frozenset((spec.split_config(_SLUG) or {}).get("divide_fields") or ())
_MONEY_FIELDS: frozenset[str] = frozenset(spec.money_fields(_SLUG))


def _check_key(source_key: str) -> None:
    if source_key not in SOURCE_KEYS:
        raise ValueError(f"tgq mapper does not handle source {source_key!r}")


def _data(obj: Any) -> dict:
    d = getattr(obj, "data", None)
    return d if isinstance(d, dict) else {}


def _text(data: dict, key: str) -> Optional[str]:
    return N.clean_text(data.get(key))


# ── folding ──────────────────────────────────────────────────────────────────

@dataclass
class TgqFold:
    """One HMPR ticket re-assembled from its legs.

    ``data`` is the FIRST leg's data (identity and text fields are copied onto every leg);
    money must go through ``fold_money`` / ``fold_taxes``, never ``data``. ``flags`` collects
    what folding noticed (``TGQ_PRE_SPLIT``, and ``TGQ_MONEY_UNSPLIT`` / ``AMOUNT_UNPARSEABLE``
    as money is read); ``to_common`` copies them onto the row.
    """
    batch_id: Optional[str]
    row_seq: Optional[int]
    legs: list
    first: Any
    data: dict
    code: Optional[str]
    serial: Optional[str]
    canon: str
    issue_date: Optional[date]
    flags: list[str] = field(default_factory=list)
    pre_split: bool = False

    @property
    def doc_key(self) -> Optional[DocKey]:
        return N.doc_key(self.code, self.serial)

    def flag(self, code: str) -> None:
        if code not in C.FLAG_LEGEND:
            raise KeyError(f"Unknown data flag {code!r}; add it to columns.FLAG_LEGEND")
        if code not in self.flags:
            self.flags.append(code)


def _leg_order(leg: Any) -> tuple:
    idx = getattr(leg, "sector_index", None)
    return (idx if idx is not None else 1, getattr(leg, "id", 0) or 0)


def _fold_code(first: Any, data: dict) -> Optional[str]:
    """``data.airline_code`` (lifted out of Ticket_No at ingest), else the code still inside
    the raw ticket number — a pre-split batch, or a cell the ingest split did not recognise."""
    code = N.zfill3(data.get("airline_code"))
    if code:
        return code
    orig = getattr(first, "orig_data", None)
    for raw in ((orig or {}).get("ticket_no") if isinstance(orig, dict) else None, data.get("ticket_no")):
        c, _serial = sector_split.split_ticket_no(N.clean_text(raw))
        if c:
            return c
    return None


def tgq_canon(data: dict) -> str:
    """Canonical type of one HMPR line (§B.2). An empty line has no type at all → UNKNOWN."""
    if not data or not any(N.clean_text(v) for v in data.values()):
        return C.UNKNOWN
    txn = (N.clean_text(data.get("transaction_type")) or "").upper()
    refund_amount = N.parse_money(data.get("total_refund_amount"))
    if "REF" in txn or (refund_amount is not None and refund_amount != 0):
        return C.REFUND
    if "VOID" in txn:
        return C.VOID
    if "EXCH" in txn or "REISS" in txn:
        return C.EXCHANGE
    if "EMD" in (N.clean_text(data.get("document_type")) or "").upper():
        return C.EMD
    return C.SALE


def tgq_issue_date(data: dict) -> Optional[date]:
    """The row's period-basis date — the Python twin of the §D SQL filter, on purpose.

    ``CASE WHEN upper(transaction_type) LIKE '%REF%' THEN coalesce(refund date, ticket_date)
    ELSE ticket_date END``. A line typed REFUND only by a non-zero refund amount keeps its
    ticket date here, exactly as the upload listing counted it, so a row can never appear on
    the report with a date the period filter did not select it by.
    """
    txn = str(data.get("transaction_type") or "").upper()
    if "REF" in txn:
        refund = N.parse_report_date(data.get("void_exchange_refund_date"))
        if refund is not None:
            return refund
    return N.parse_report_date(data.get("ticket_date"))


def fold_tgq_ticket(legs: list) -> Optional[TgqFold]:
    """The legs of one ``(batch_id, row_seq)`` → a ``TgqFold``, or None for the file's own
    grand-total line (``is_total``, or recognised by content in a batch imported before the
    flag existed — ``tgq_split_01`` did not backfill it)."""
    if not legs:
        return None
    ordered = sorted(legs, key=_leg_order)
    first = ordered[0]
    data = _data(first)
    if any(bool(getattr(leg, "is_total", False)) for leg in ordered):
        return None
    if sector_split.is_total_row(data, _TOTAL_ROW_CFG):
        return None

    pre_split = getattr(first, "sector_count", None) is None
    orig = getattr(first, "orig_data", None)
    ticket_data = orig if isinstance(orig, dict) else data
    canon = tgq_canon(ticket_data)
    fold = TgqFold(
        batch_id=getattr(first, "batch_id", None),
        row_seq=getattr(first, "row_seq", None),
        legs=ordered,
        first=first,
        data=data,
        code=_fold_code(first, data),
        serial=N.clean_text(data.get("ticket_no")),
        canon=canon,
        issue_date=tgq_issue_date(data),
        pre_split=pre_split,
    )
    if pre_split:
        fold.flag("TGQ_PRE_SPLIT")
    return fold


def _read_money(fold: TgqFold, raw: Any) -> Optional[Decimal]:
    value, unparseable = N.parse_money_checked(raw)
    if unparseable:
        fold.flag("AMOUNT_UNPARSEABLE")
    return value


def _allocator_numeric(raw: Any) -> bool:
    """Would ``sector_split.allocate`` have divided this value? Its exact test."""
    return bool(sector_split._NUMERIC_RE.match(str(raw).replace(",", "").strip()))


def fold_money(fold: TgqFold, field_name: str) -> Optional[Decimal]:
    """§B.4 ``m()``: the whole-ticket amount of one money field (as stored, unsigned).

    1. first leg ``orig_data`` when present — the verbatim pre-split line;
    2. a pre-split batch's own ``data``;
    3. one leg, or a field ingest never divides → that leg's value;
    4. the legs' sum when every present leg holds an allocated number;
    5. otherwise the first leg's value (a copied, non-numeric cell) + ``TGQ_MONEY_UNSPLIT``.
    """
    first = fold.first
    orig = getattr(first, "orig_data", None)
    if isinstance(orig, dict):
        return _read_money(fold, orig.get(field_name))
    if fold.pre_split or len(fold.legs) == 1 or field_name not in _DIVIDE_FIELDS:
        return _read_money(fold, fold.data.get(field_name))

    present = [v for v in (_data(leg).get(field_name) for leg in fold.legs) if N.clean_text(v) is not None]
    if not present:
        return None
    if all(_allocator_numeric(v) for v in present):
        return N.dsum(*(N.parse_money(v) for v in present))
    fold.flag("TGQ_MONEY_UNSPLIT")
    return _read_money(fold, fold.data.get(field_name))


def _tax_entries(taxes: Any) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for t in taxes or []:
        if not isinstance(t, dict):
            continue
        code = N.clean_text(t.get("type"))
        if code:
            out.append((code.upper(), t.get("amount")))
    return out


def _sum_entries(fold: TgqFold, entries: Iterable[tuple[str, Any]]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for code, raw in entries:
        value = _read_money(fold, raw)
        if value is not None:
            out[code] = out.get(code, Decimal(0)) + value
    return out


def fold_taxes(fold: TgqFold) -> dict[str, Decimal]:
    """``{TAX CODE: whole-ticket amount}`` from the folded ``Tax_TypeN/TaxN`` pairs.

    ``orig_taxes`` when present; a pre-split or single-leg ticket's own taxes; else the legs'
    sum under the same allocator test as ``fold_money`` (per code).
    """
    first = fold.first
    orig = getattr(first, "orig_taxes", None)
    if isinstance(orig, list):
        return _sum_entries(fold, _tax_entries(orig))
    if fold.pre_split or len(fold.legs) == 1:
        return _sum_entries(fold, _tax_entries(getattr(first, "taxes", None)))

    per_leg = [_tax_entries(getattr(leg, "taxes", None)) for leg in fold.legs]
    codes: list[str] = []
    for entries in per_leg:
        for code, _raw in entries:
            if code not in codes:
                codes.append(code)
    out: dict[str, Decimal] = {}
    for code in codes:
        raws = [raw for entries in per_leg for c, raw in entries if c == code and N.clean_text(raw) is not None]
        if not raws:
            continue
        if all(_allocator_numeric(r) for r in raws):
            total = N.dsum(*(N.parse_money(r) for r in raws))
            if total is not None:
                out[code] = total
            continue
        fold.flag("TGQ_MONEY_UNSPLIT")
        out.update(_sum_entries(fold, ((c, r) for c, r in per_leg[0] if c == code)))
    return out


# ── streaming groups ─────────────────────────────────────────────────────────

def tgq_group_key(leg: Any) -> tuple:
    """``(batch_id, row_seq)``. A row never processed by the split has no ``row_seq`` and is a
    ticket on its own, so it keys on its id instead (as ``statements.reprocess`` does)."""
    seq = getattr(leg, "row_seq", None)
    return (getattr(leg, "batch_id", None), seq if seq is not None else f"id:{getattr(leg, 'id', None)}")


class TgqLegGrouper:
    """Groups a leg stream ordered by ``batch_id, row_seq, sector_index, id`` into tickets.

    ``feed`` takes one fetched chunk and returns the tickets it CLOSED; the last group stays
    open because its next leg may be in the following chunk. ``flush`` closes it at the end.
    Usable from an async fetch loop, which a plain generator is not.
    """

    def __init__(self) -> None:
        self._key: Any = None
        self._open: list = []

    def feed(self, legs: Iterable[Any]) -> list[list]:
        closed: list[list] = []
        for leg in legs:
            key = tgq_group_key(leg)
            if self._open and key != self._key:
                closed.append(self._open)
                self._open = []
            self._key = key
            self._open.append(leg)
        return closed

    def flush(self) -> Optional[list]:
        group, self._open, self._key = self._open, [], None
        return group or None


def iter_folds(legs_iterable: Iterable[Any]) -> Iterator[list]:
    """Yield each ticket's legs from an ordered leg stream (chunks already chained)."""
    grouper = TgqLegGrouper()
    for leg in legs_iterable:
        yield from grouper.feed((leg,))
    last = grouper.flush()
    if last:
        yield last


# ── Combined ─────────────────────────────────────────────────────────────────

def tgq_row_ref(fold: TgqFold) -> str:
    """``tgq_hmpr:<batch_id>#<row_seq>`` — the ticket; the detail sheet's Ticket Ref column
    carries the same text on every leg so the two sheets join."""
    if fold.row_seq is None:
        return row_ref(_TABLE, getattr(fold.first, "id", None))
    return row_ref(_TABLE, f"{fold.batch_id}#{fold.row_seq}")


def _leg_ref(leg: Any) -> str:
    seq = getattr(leg, "row_seq", None)
    if seq is None:
        return row_ref(_TABLE, getattr(leg, "id", None))
    return row_ref(_TABLE, f"{getattr(leg, 'batch_id', None)}#{seq}")


def tgq_natural_key(fold: TgqFold) -> Optional[tuple]:
    """§C.5 step 3 dedupe key ``(packed document key, canon)``; None when unmatchable."""
    key = fold.doc_key
    return None if key is None else (N.pack(key), fold.canon)


def _itinerary(fold: TgqFold) -> dict[str, Optional[str]]:
    """Sector / flight / class / coupon status / first travel token across the legs."""
    first = fold.data
    if fold.pre_split:
        raw_sectors = first.get("sectors")
        pairs, status = sector_split.leg_sectors(raw_sectors)
        n = len(pairs) if status != sector_split.UNPARSED else 0
        if n:
            flights = sector_split.tokens(first.get("flightno"), n) if n > 1 else [first.get("flightno")]
            classes = sector_split.tokens(first.get("class"), n) or [first.get("class")]
            statuses = sector_split.tokens(first.get("coupon_status"), n) or [first.get("coupon_status")]
            travels = sector_split.tokens(first.get("traveldt"), n)
            travel = travels[0] if travels else first.get("traveldt")
            sector = journey_chain(pairs)
        else:
            flights, classes = [first.get("flightno")], [first.get("class")]
            statuses, travel, sector = [first.get("coupon_status")], first.get("traveldt"), None
        return {
            "sector": sector or N.clean_text(raw_sectors),
            "flight_no": "/".join(f for f in (N.clean_text(x) for x in flights) if f) or None,
            "booking_class": distinct_classes(classes),
            "status": N.join_unique(statuses),
            "travel": travel,
        }
    legs = [_data(leg) for leg in fold.legs]
    raw_sectors = [d.get("sectors") for d in legs]
    return {
        # journey_chain fails closed on a leg it cannot read; the report then shows the
        # sectors as printed rather than nothing.
        "sector": journey_chain(raw_sectors) or N.join_unique(raw_sectors, " "),
        "flight_no": "/".join(f for f in (N.clean_text(d.get("flightno")) for d in legs) if f) or None,
        "booking_class": distinct_classes([d.get("class") for d in legs]),
        "status": N.join_unique(d.get("coupon_status") for d in legs),
        "travel": first.get("traveldt"),
    }


def _z(v: Optional[Decimal]) -> Decimal:
    return v if v is not None else Decimal(0)


def to_common(source_key: str, fold: TgqFold, ctx: MapCtx, link: Optional[LinkResult] = None,
              **extra: Any) -> dict[str, Any]:
    """One emitted TGQ ticket → a Combined row (§B.4 TGQ column). ``link`` is applied last."""
    _check_key(source_key)
    d, canon = fold.data, fold.canon
    row = C.new_common_row(ctx, category=C.CAT_BSP, source_type=_SOURCE_TYPE, row_ref=tgq_row_ref(fold))
    row["counts_in_net"] = C.NET_TGQ_NOT_IN_BSP
    row["not_in_bsp"] = "Yes"

    # ── parties / document ───────────────────────────────────────────────────
    master = ctx.airlines.numeric(fold.code) if fold.code else None
    row["settled_with"] = SETTLED_WITH
    row["agent_signon"] = _text(d, "ticketing_signon") or _text(d, "booking_signon")
    row["airline_numeric"] = fold.code
    row["airline_code"] = _text(d, "airline") or (master.iata_code if master else None)
    row["airline_name"] = _text(d, "air_name") or (master.name if master else None)
    row["booking_party_gstin"] = _text(d, "gstn")
    row["product"] = C.PRODUCT_AIR
    row["transaction_type"] = canon
    row["source_txn_type"] = _text(d, "transaction_type")
    row["document_number"] = fold.serial

    keys = N.doc_keys(fold.code, fold.serial)
    if keys:
        ticket, nonstandard = N.ticket13(keys[0].code or fold.code, keys[0].serial)
    else:
        ticket, nonstandard = N.ticket13(fold.code, fold.serial)
    row["ticket_number"] = ticket
    if nonstandard:
        C.add_flag(row, "TICKET_NO_NONSTANDARD")
    row["related_document"] = _text(d, "exchanged_for")

    # ── booking ──────────────────────────────────────────────────────────────
    row["airline_pnr"] = _text(d, "air_pnr")
    row["gds_ref"] = _text(d, "gal_pnr")
    row["invoice_ref"] = _text(d, "invoice_no")
    row["passenger_name"] = _text(d, "pax_name")
    row["pax_count"] = 0 if canon == C.EMD else 1

    # ── dates / itinerary ────────────────────────────────────────────────────
    row["issue_date"] = fold.issue_date
    if fold.issue_date is None:
        C.add_flag(row, "DATE_UNREADABLE")
    if canon == C.REFUND:
        row["booking_date"] = N.parse_report_date(d.get("ticket_date"))
    it = _itinerary(fold)
    travel, source = resolve_travel_date(N.clean_text(it["travel"]), N.clean_text(d.get("ticket_date")), None)
    row["travel_date"] = travel
    if source == "inferred":
        C.add_flag(row, "TRAVEL_YEAR_INFERRED")
    row["sector"] = it["sector"]
    row["flight_no"] = it["flight_no"]
    row["booking_class"] = it["booking_class"]
    row["status"] = it["status"]
    row["fare_basis"] = _text(d, "fare_basis")
    row["tour_code"] = _text(d, "tour_code") or _text(d, "value_code")
    row["currency"] = "INR"
    fare_currency = (_text(d, "basefarecurrency") or "").upper()
    if fare_currency and fare_currency != "INR":
        C.add_flag(row, "FARE_CURRENCY_DIFFERS")
    row["form_of_payment"] = _text(d, "fop")      # never fop_details: card data

    # ── money (TYPE_SIGNED) ──────────────────────────────────────────────────
    def s(v: Optional[Decimal]) -> Optional[Decimal]:
        return N.signed(v, canon)

    taxes = fold_taxes(fold)
    yq_raw = fold_money(fold, "yqtax")
    base = s(fold_money(fold, "base_fare"))
    yq = s(yq_raw if yq_raw is not None else taxes.get("YQ"))
    yr = s(taxes.get("YR"))
    k3 = s(taxes.get("K3"))
    total_tax = s(fold_money(fold, "total_tax"))
    airline_fee = s(fold_money(fold, "airlinefee"))
    if total_tax is None:
        other = airline_fee
    else:
        other = total_tax - _z(yq) - _z(yr) - _z(k3) + _z(airline_fee)
        if other != 0 and total_tax != 0 and (other < 0) != (total_tax < 0):
            C.add_flag(row, "NEG_TAX_RESIDUAL")
    if canon == C.REFUND:
        gross = net = s(fold_money(fold, "total_refund_amount"))
    else:
        gross = s(fold_money(fold, "total_fare"))
        net = s(fold_money(fold, "net_remit"))
    row.update(
        base_fare=base, yq=yq, yr=yr, k3=k3, other_taxes=other, total_taxes=total_tax,
        gross_amount=gross, commission=s(fold_money(fold, "comm_amount")), net_payable=net,
    )

    if canon == C.UNKNOWN:
        C.add_flag(row, "TXN_UNMAPPED")
    C.add_flag(row, *fold.flags)
    if fold.doc_key is None:
        C.add_flag(row, "TGQ_UNMATCHABLE")
        row["not_in_bsp"] = NOT_IN_BSP_UNKNOWN
        row["counts_in_net"] = C.NET_TGQ_UNMATCHABLE
    return C.apply_link(row, link)


# ── detail sheet ─────────────────────────────────────────────────────────────

def _leg_label(row: Any, ctx: MapCtx) -> Optional[str]:
    count = getattr(row, "sector_count", None)
    return f"{getattr(row, 'sector_index', None)}/{count}" if count else None


def _taxes_text(row: Any, ctx: MapCtx) -> Optional[str]:
    text = " · ".join(
        f"{t.get('type')} {t.get('amount') or ''}".strip()
        for t in (getattr(row, "taxes", None) or []) if isinstance(t, dict) and t.get("type")
    )
    return text or None


def _money_getter(name: str):
    def _get(row: Any, ctx: MapCtx) -> Any:
        raw = _data(row).get(name)
        value = N.parse_money(raw)
        return value if value is not None else N.clean_text(raw)
    return _get


def _raw_getter(name: str):
    return lambda row, ctx: _data(row).get(name)


def detail_columns(source_key: str, ctx: MapCtx) -> list[DetailCol]:
    """The TGQ HMPR sheet, one row per LEG: provenance, Ticket Ref (joins Combined), then the
    repository's own display columns (Leg, …, Airline_Code, …, Taxes) and any extra JSONB keys.
    Card fields never appear; contact fields only with ``include_pii``."""
    _check_key(source_key)
    include_pii = ctx.options.include_pii
    cols = provenance_cols(lambda row: row_ref(_TABLE, getattr(row, "id", None)))
    cols.append(DetailCol("Ticket Ref", lambda row, ctx: _leg_ref(row), "text", 24))
    seen: set[str] = set()
    for c in statement_display.display_columns(_SLUG):
        name, header = c["field"], c["header"]
        seen.add(name)
        if name == "__leg__":
            cols.append(DetailCol(header, _leg_label, "text", 7))
        elif name == "__taxes__":
            cols.append(DetailCol(header, _taxes_text, "text", 30))
        elif not (pii.allowed(name, include_pii) and pii.allowed(header, include_pii)):
            continue
        elif name in _MONEY_FIELDS or c.get("kind") == "money":
            cols.append(DetailCol(header, _money_getter(name), "money", 12))
        else:
            cols.append(DetailCol(header, _raw_getter(name), "text", 14))
    for key in ctx.extra_keys:
        if key in seen or not pii.allowed(key, include_pii):
            continue
        cols.append(DetailCol(f"data.{key}", _raw_getter(key), "text", 14))
    return cols
