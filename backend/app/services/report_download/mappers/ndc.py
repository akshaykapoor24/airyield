"""NDC → Combined rows (one per NDC line, grouped per ticket) and the NDC detail sheet.

An NDC export writes a ticket's add-ons — paid seats, bags, coupon-level repeats — as lines
of their own, and ``ndc_billing_projection.build_groups`` is the one place that decides which
lines make up a ticket. The report reuses it unchanged, so a report and an invoice can never
disagree about what a ticket is, and follows the projection's money rules:

* fare components (base, taxes, gross, penalty, service fee, discount) exist ONLY on the
  anchor row. A carrier that ships tax on a seat line already has it inside that line's
  settled figure; repeating the anchor's components on its latched lines would double them
  ("THE TAXES STAY ANCHOR-ONLY" in ``ticket_fields``);
* every row's Net Payable is ``signed_total(row)``, so Σ Net over a group is the group total
  the ticket bills at;
* components are signed by ``_sig`` — the export writes refund components as magnitudes and
  only ``Payment Amount`` carries the sign.

The transaction type is the GROUP's (a latched line is part of its ticket's transaction). A
row mapped without a group (a batch too large to group in memory) falls back to the stored
``bill_*`` grouping and is flagged ``NDC_GROUPING_STORED``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from app.services import ndc_billing_projection as P
from app.services import ndc_spec
from app.services import statement_display
from app.services import statement_spec as spec
from app.services.report_download import columns as C
from app.services.report_download import normalize as N
from app.services.report_download import pii
from app.services.report_download.mappers.base import DetailCol, provenance_cols, row_ref
from app.services.report_download.types import DocKey, LinkResult, MapCtx

__all__ = [
    "SOURCE_KEYS", "ROLE_ANCHOR", "ROLE_LATCHED", "ROLE_ANCILLARY", "NdcGroup",
    "ndc_groups", "groups_by_row", "row_role", "group_canon", "group_doc_key",
    "ndc_natural_key", "to_common", "detail_columns",
]

SOURCE_KEYS: tuple[str, ...] = ("ndc",)
_SLUG = "ndc"
_TABLE = "ndc"
_SOURCE_TYPE = "NDC"

ROLE_ANCHOR = "anchor"          # the ticket line: carries the fare components, Pax 1
ROLE_LATCHED = "latched"        # coupon-level repeat of the ticket's document: Net only
ROLE_ANCILLARY = "ancillary"    # seat / bag / meal / other add-on line: Ancillary + Net only

_MONEY_FIELDS: frozenset[str] = frozenset(spec.money_fields(_SLUG))


def _check_key(source_key: str) -> None:
    if source_key not in SOURCE_KEYS:
        raise ValueError(f"ndc mapper does not handle source {source_key!r}")


def _data(obj: Any) -> dict:
    d = getattr(obj, "data", None)
    return d if isinstance(d, dict) else {}


def _text(data: dict, key: str) -> Optional[str]:
    return N.clean_text(data.get(key))


# ── grouping ─────────────────────────────────────────────────────────────────

@dataclass
class NdcGroup:
    """One ticket-to-be: its anchor row view, every row (anchor first, then latched lines in
    file order), the billed total, the canonical type, and each row's report role and
    ``build_groups`` latch status keyed by row id."""
    key: str
    anchor: Any
    rows: list
    total: Optional[Decimal]
    canon: str = C.UNKNOWN
    roles: dict[Any, str] = field(default_factory=dict)
    latch_status: dict[Any, str] = field(default_factory=dict)


def _role_for(data: dict, is_anchor: bool) -> str:
    if P._looks_ancillary(data):
        return ROLE_ANCILLARY
    return ROLE_ANCHOR if is_anchor else ROLE_LATCHED


def _canon_of(data: dict) -> str:
    if not data:
        return C.UNKNOWN
    if P.is_refund(data):
        return C.REFUND
    if P._looks_ancillary(data):
        return C.EMD
    total = P.signed_total(data)
    if total is None or total == 0:
        return C.VOID
    return C.SALE


def group_canon(group: NdcGroup) -> str:
    """§B.2 NDC, from the anchor: refund → REFUND; add-on → EMD; no money → VOID; else SALE."""
    anchor = group.anchor if group.anchor is not None else (group.rows[0] if group.rows else None)
    return C.UNKNOWN if anchor is None else _canon_of(_data(anchor))


def group_doc_key(group: NdcGroup) -> Optional[DocKey]:
    """The anchor's ``(airline_iata_code, document_no)`` — what BSP membership is probed with."""
    if group.anchor is None:
        return None
    d = _data(group.anchor)
    return N.doc_key(d.get("airline_iata_code"), d.get("document_no"))


def ndc_groups(rows: list) -> list[NdcGroup]:
    """Rows of ONE NDC upload → its tickets, via ``ndc_billing_projection.build_groups``.

    Grouping is per upload by construction (PNR + passenger latching must not reach across
    files), so call it once per batch.
    """
    out: list[NdcGroup] = []
    for g in P.build_groups(rows):
        group = NdcGroup(key=g.key, anchor=g.anchor.source, rows=[ln.source for ln in g.lines], total=g.total)
        for line in g.lines:
            group.roles[line.id] = _role_for(line.data, line is g.anchor)
            group.latch_status[line.id] = line.latch_status
        group.canon = group_canon(group)
        out.append(group)
    return out


def groups_by_row(groups: list[NdcGroup]) -> dict[Any, NdcGroup]:
    """``{row id: its group}`` for mapping rows streamed in file order."""
    return {rid: g for g in groups for rid in g.roles}


def row_role(row: Any, group: Optional[NdcGroup]) -> str:
    """The row's report role; without a group, from the stored ``bill_latch_status``."""
    data = _data(row)
    rid = getattr(row, "id", None)
    if group is not None and rid in group.roles:
        return group.roles[rid]
    return _role_for(data, getattr(row, "bill_latch_status", None) != P.LATCHED)


def ndc_natural_key(row: Any) -> tuple:
    """§C.10 duplicate key: the same line re-uploaded in a newer file."""
    d = _data(row)
    return tuple(N.clean_text(d.get(k)) for k in
                 ("document_no", "txn_type", "coupon_number", "payment_amount", "date_of_issue"))


# ── Combined ─────────────────────────────────────────────────────────────────

def _is_blank(raw: Any) -> bool:
    """Blank, or a placeholder ("-", "N/A") that means no amount rather than a bad one."""
    value, unparseable = N.parse_money_checked(raw)
    return value is None and not unparseable


def _checked(row: dict, data: dict, keys: tuple[str, ...], value: Optional[Decimal]) -> Optional[Decimal]:
    """The projection's own parse (``ndc_spec.to_decimal``), kept so the report and the
    invoice read a cell identically — but a present cell it could not read (or read as NaN)
    is blanked AND flagged instead of passing silently."""
    if value is not None:
        if value.is_finite():
            return value
        C.add_flag(row, "AMOUNT_UNPARSEABLE")
        return None
    if any(not _is_blank(data.get(k)) for k in keys):
        C.add_flag(row, "AMOUNT_UNPARSEABLE")
    return None


def to_common(source_key: str, row: Any, ctx: MapCtx, link: Optional[LinkResult] = None,
              group: Optional[NdcGroup] = None, **extra: Any) -> dict[str, Any]:
    """One NDC line → a Combined row (§B.4 NDC column). ``link`` is applied last."""
    _check_key(source_key)
    d = _data(row)
    out = C.new_common_row(ctx, category=C.CAT_BSP, source_type=_SOURCE_TYPE,
                           row_ref=row_ref(_TABLE, getattr(row, "id", None)))
    out["counts_in_net"] = C.NET_YES

    role = row_role(row, group)
    if group is not None and getattr(row, "id", None) in group.roles:
        canon = group.canon
    else:
        canon = _canon_of(d)
        C.add_flag(out, "NDC_GROUPING_STORED")
    kind = "refund" if canon == C.REFUND else "sale"

    # ── parties / document ───────────────────────────────────────────────────
    numeric = N.zfill3(d.get("airline_iata_code"))
    carrier = _text(d, "airline")
    master = ctx.airlines.numeric(numeric) or ctx.airlines.iata(carrier)
    out["settled_with"] = f"Airline NDC – {carrier}" if carrier else (
        f"Airline NDC – {master.name}" if master and master.name else "Airline NDC")
    out["agent_signon"] = _text(d, "tkt_issue_signin") or _text(d, "booking_signin")
    out["airline_numeric"] = numeric
    out["airline_code"] = carrier or (master.iata_code if master else None)
    out["airline_name"] = master.name if master else None
    out["product"] = C.PRODUCT_AIR
    out["transaction_type"] = canon
    out["source_txn_type"] = N.join_unique([d.get("txn_type"), d.get("product")])
    out["document_number"] = _text(d, "document_no")
    ticket, nonstandard = N.ticket13(d.get("airline_iata_code"), d.get("document_no"))
    out["ticket_number"] = ticket
    if nonstandard:
        C.add_flag(out, "TICKET_NO_NONSTANDARD")
    out["related_document"] = _text(d, "inconnection_doc_number")
    out["status"] = _text(d, "coupon_status") or _text(d, "payment_status")

    # ── booking ──────────────────────────────────────────────────────────────
    out["airline_pnr"] = _text(d, "airline_pnr")
    out["gds_ref"] = _text(d, "child_parent_pnr")
    out["passenger_name"] = _text(d, "passenger_name")
    out["pax_count"] = 1 if role == ROLE_ANCHOR else 0

    # ── dates / itinerary ────────────────────────────────────────────────────
    booking = N.parse_report_date(d.get("date_of_booking"))
    issue = N.parse_report_date(d.get("date_of_issue")) or booking
    out["issue_date"] = issue
    if issue is None:
        C.add_flag(out, "DATE_UNREADABLE")
    out["booking_date"] = booking
    out["travel_date"] = N.parse_report_date(d.get("departure_date"))
    out["sector"] = _text(d, "sectors")
    out["flight_no"] = _text(d, "flight_no")
    out["booking_class"] = _text(d, "class_of_booking")
    out["fare_basis"] = _text(d, "farebasis")
    out["tour_code"] = _text(d, "tour_code") or _text(d, "deal_code") or _text(d, "promo_code")
    currency = _text(d, "currency")
    if currency:
        out["currency"] = currency.upper()
    else:
        out["currency"] = "INR"
        C.add_flag(out, "CURRENCY_ASSUMED")
    out["form_of_payment"] = _text(d, "form_of_payment")

    # ── money ────────────────────────────────────────────────────────────────
    if role == ROLE_ANCHOR:
        for col, key in (("base_fare", "basic_fare"), ("yq", "yq_tax"), ("yr", "yr_tax"),
                         ("k3", "k3_tax"), ("other_taxes", "other_taxes"),
                         ("total_taxes", "total_tax"), ("gross_amount", "total_fare")):
            out[col] = _checked(out, d, (key,), P._sig(d, key, kind))
        for col, key in (("penalty", "penalty_amount"), ("service_fee", "service_fee"),
                         ("discount", "discount")):
            out[col] = _checked(out, d, (key,), P._abs(d, key))
    else:
        rid = getattr(row, "id", None)
        stored = group is None or rid not in group.roles
        latch = getattr(row, "bill_latch_status", None) if stored else group.latch_status.get(rid)
        if role == ROLE_ANCILLARY:
            C.add_flag(out, "NDC_ANCILLARY")
        if latch == P.LATCHED:
            C.add_flag(out, "NDC_LATCHED")
    # signed_total reads Payment Amount, else Total Fare — the figure the group total sums.
    net = _checked(out, d, ("payment_amount", "total_fare"), P.signed_total(d))
    if not _is_blank(d.get("payment_amount")) and ndc_spec.to_decimal(d.get("payment_amount")) is None:
        C.add_flag(out, "AMOUNT_UNPARSEABLE")    # junk settled figure; Total Fare stood in
    out["net_payable"] = net
    if role == ROLE_ANCILLARY:
        out["ancillary"] = net

    if canon == C.UNKNOWN:
        C.add_flag(out, "TXN_UNMAPPED")
    return C.apply_link(out, link)


# ── detail sheet ─────────────────────────────────────────────────────────────

def _money_getter(name: str):
    def _get(row: Any, ctx: MapCtx) -> Any:
        raw = _data(row).get(name)
        value = N.parse_money(raw)
        return value if value is not None else N.clean_text(raw)
    return _get


def _raw_getter(name: str):
    return lambda row, ctx: _data(row).get(name)


def _anchor_text(row: Any, ctx: MapCtx) -> Optional[str]:
    flag = getattr(row, "bill_is_anchor", None)
    return None if flag is None else ("Yes" if flag else "No")


def detail_columns(source_key: str, ctx: MapCtx) -> list[DetailCol]:
    """The NDC sheet: provenance, the repository's display columns, then the STORED billing
    grouping (Group Key / Anchor / Latch Status — detail sheets show what is stored) and any
    extra JSONB keys, PII-filtered."""
    _check_key(source_key)
    include_pii = ctx.options.include_pii
    cols = provenance_cols(lambda row: row_ref(_TABLE, getattr(row, "id", None)))
    seen: set[str] = set()
    for c in statement_display.display_columns(_SLUG):
        name, header = c["field"], c["header"]
        seen.add(name)
        if name.startswith("__"):
            continue       # no derived display fields for NDC today; never guess one
        if not (pii.allowed(name, include_pii) and pii.allowed(header, include_pii)):
            continue
        if name in _MONEY_FIELDS or c.get("kind") == "money":
            cols.append(DetailCol(header, _money_getter(name), "money", 12))
        else:
            cols.append(DetailCol(header, _raw_getter(name), "text", 14))
    cols += [
        DetailCol("Group Key", lambda row, ctx: getattr(row, "bill_group_key", None), "text", 20),
        DetailCol("Anchor", _anchor_text, "text", 7),
        DetailCol("Latch Status", lambda row, ctx: getattr(row, "bill_latch_status", None), "text", 12),
    ]
    for key in ctx.extra_keys:
        if key in seen or not pii.allowed(key, include_pii):
            continue
        cols.append(DetailCol(f"data.{key}", _raw_getter(key), "text", 14))
    return cols
