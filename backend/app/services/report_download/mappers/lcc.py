"""LCC sources → detail sheets and Combined rows: LCC Detailed and the four LCC ledgers.

An LCC (IndiGo, Air India Express …) is settled directly with the airline: there is no BSP, no
ticket stock and no commission line, so the mapping rules differ from every BSP-family source.
Four decisions a reader should know before editing:

1. **Money is written as stored.** LCC Detailed ``total`` is already signed the way billing
   reads it (``bill_kind`` is classified from its sign at ingest), and an Air India Express
   account row carries ``ForeignAmount`` exactly as printed — whose sign the business confirmed
   against the opposite convention in the account Note (see ``services/lcc_merge.py`` rule 3).
   The report never re-signs: it relabels only ``cancellation_credit`` as CREDIT_TRANSFER and
   flags ``LCC_NOTE_SIGN_CONFLICT`` where the Note disagrees with the sign.
2. **"Taxes" is not tax.** ``lcc_detailed.taxes`` holds every named charge — seats, baggage,
   cancellation fees, convenience fees — so the Combined columns come from the
   ``lcc_codes`` classifier, not from ``taxes_total`` (which sums them all). Only lump-sum /
   account exports with no codes fall back to ``taxes_total`` or total − base fare.
3. **An LCC issues no ticket.** Ticket Number stays blank on LCC Detailed, and a ledger's
   ``ticket_number`` is only promoted when it really is a 3-digit code + 10-digit serial — a
   PNR-shaped value dressed up as a ticket would mislead the BSP linking columns.
4. **Ledgers never count.** DI / Divided PNR / Flown / CTA-BTA restate money that LCC Detailed
   already carries, so they are shown for reference (``NET_LEDGER``) and linked by PNR.

``_bill_kind`` and ``_sector`` are local copies of ``api/v1/lcc_detailed._bill_kind`` and
``commission/lcc_detailed._sector``: importing those modules would pull FastAPI routers and the
deal-matching engine into a pure mapper. ``test_report_download_map_lcc`` pins both copies to
the originals so they cannot drift.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Optional

from app.services import lcc_detailed_spec
from app.services.lcc_merge import (
    MOVEMENT_BALANCE, MOVEMENT_BOOKING_PAYMENT, MOVEMENT_CANCELLATION_CREDIT, MOVEMENT_REFUND,
)
from app.services.report_download import columns as C
from app.services.report_download import lcc_codes, pii
from app.services.report_download import normalize as N
from app.services.report_download.mappers.base import DetailCol, attr, data_key, provenance_cols
from app.services.report_download.registry import get_source
from app.services.report_download.types import LinkResult, MapCtx
from app.services.statement_display import display_columns

__all__ = [
    "SOURCE_KEYS", "LEDGER_KEYS",
    "detail_columns", "to_common", "lcc_canon",
    "lcc_natural_key", "ledger_natural_key", "ledger_pnrs", "ledger_pnr",
]

LCC_DETAILED = "lcc-detailed"
LCC_DI = "lcc-di"
LCC_DIVIDED = "lcc-divided-pnr"
LCC_FLOWN = "lcc-flown-report"
LCC_CTA_BTA = "lcc-cta-bta"

LEDGER_KEYS: tuple[str, ...] = (LCC_DI, LCC_DIVIDED, LCC_FLOWN, LCC_CTA_BTA)
SOURCE_KEYS: tuple[str, ...] = (LCC_DETAILED, *LEDGER_KEYS)

ROW_KIND_ACCOUNT = "account"
_SETTLED_WITH = "Airline direct"
_BILL_KIND_CANON = {"sale": C.SALE, "refund": C.REFUND, "payment": C.PAYMENT}

# Ledger fields that hold an amount, for the detail sheet's number conversion. The statement
# specs declare no money fields for these types (their UI never totals them).
_LEDGER_MONEY: dict[str, frozenset[str]] = {
    LCC_DI: frozenset({"amount"}),
    LCC_DIVIDED: frozenset({"payment_amount"}),
    LCC_FLOWN: frozenset({"base_fare", "taxes", "total_fare", "commission_amount",
                          "incentive_amount", "net_fare"}),
    LCC_CTA_BTA: frozenset({"base_fare", "taxes", "fee_amount", "total_amount"}),
}

_CORE_KIND = {"datetime": "datetime", "numeric": "money", "int": "int"}


# ── shared helpers ───────────────────────────────────────────────────────────

def _bill_kind(total: Any) -> str:
    """Copy of ``api/v1/lcc_detailed._bill_kind``: classify on the sign of ``total``.
    ``total`` 0 / None is a payment movement (money moved, no fare)."""
    if total is None or total == 0:
        return "payment"
    return "sale" if total > 0 else "refund"


def _sector(row: Any) -> Optional[str]:
    """Copy of ``commission/lcc_detailed._sector``: 'DEL/BOM/MAA' from the folded legs,
    collapsing an airport shared by consecutive legs. Tolerates non-dict JSON entries."""
    routes = [str(s.get("route")).strip() for s in _dicts(getattr(row, "segments", None))
              if s.get("route")]
    if not routes:
        return None
    parts: list[str] = []
    for r in routes:
        for p in r.replace("-", "/").split("/"):
            p = p.strip().upper()
            if p and (not parts or parts[-1] != p):
                parts.append(p)
    return "/".join(parts) or None


def _dicts(items: Any) -> list[dict]:
    """A JSONB array (possibly JSON null) → its dict entries."""
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _as_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _upper(v: Any) -> Optional[str]:
    s = N.clean_text(v)
    return s.upper() if s is not None else None


def _first(*vals: Any) -> Optional[str]:
    """First non-blank text, as stored (stripped)."""
    for v in vals:
        s = N.clean_text(v)
        if s is not None:
            return s
    return None


def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    d = N.parse_money(v)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


def _money(out: dict, v: Any) -> Optional[Decimal]:
    """Stored amount → Decimal; flags unreadable text (blank stays blank, never 0)."""
    amt, bad = N.parse_money_checked(v)
    if bad:
        C.add_flag(out, "AMOUNT_UNPARSEABLE")
    return amt


def _settled_with(name: Optional[str]) -> str:
    return f"{_SETTLED_WITH} – {name}" if name else _SETTLED_WITH


def _currency(out: dict, code: Any) -> str:
    cur = _upper(code)
    if cur is None:
        C.add_flag(out, "CURRENCY_ASSUMED")
        return "INR"
    return cur


def _row_ref(source_key: str, row: Any) -> str:
    return f"{get_source(source_key).model.__tablename__}:{getattr(row, 'id', None)}"


def _new_row(source_key: str, row: Any, ctx: MapCtx) -> dict[str, Any]:
    src = get_source(source_key)
    return C.new_common_row(ctx, category=src.category, source_type=src.label,
                            row_ref=_row_ref(source_key, row))


def _check_source(source_key: str) -> None:
    if source_key not in SOURCE_KEYS:
        raise KeyError(f"mappers.lcc does not map source {source_key!r}")


# ── LCC Detailed ─────────────────────────────────────────────────────────────

def lcc_canon(row: Any) -> str:
    """Canonical transaction type of an LCC Detailed row (design §B.2).

    Only ``cancellation_credit`` ("Funds Added" back from a cancelled booking) is relabelled;
    every other row keeps the ingest's ``bill_kind`` so the report agrees with billing.
    """
    movement = (getattr(row, "movement_kind", None) or "").strip().lower()
    row_kind = (getattr(row, "row_kind", None) or "").strip().lower()
    if row_kind == ROW_KIND_ACCOUNT and movement == MOVEMENT_CANCELLATION_CREDIT:
        return C.CREDIT_TRANSFER
    if movement == MOVEMENT_BALANCE:
        return C.PAYMENT
    kind = (getattr(row, "bill_kind", None) or "").strip().lower()
    if kind not in _BILL_KIND_CANON:
        kind = _bill_kind(N.D(getattr(row, "total", None)))
    return _BILL_KIND_CANON[kind]


def _taxes_unreadable(taxes: Any) -> bool:
    """A coded charge whose amount the classifier had to leave out of every sum."""
    return bool(lcc_codes.sums(taxes).unreadable_codes)


def _detailed_to_common(row: Any, ctx: MapCtx, link: Optional[LinkResult]) -> dict[str, Any]:
    out = _new_row(LCC_DETAILED, row, ctx)
    header = ctx.upload.header
    snap = ctx.upload.airline
    canon = lcc_canon(row)
    is_account = (row.row_kind or "").strip().lower() == ROW_KIND_ACCOUNT
    movement = (row.movement_kind or "").strip().lower()

    # ── parties / document / booking ─────────────────────────────────────────
    airline_name = _first(row.airline_name, getattr(header, "airline_name", None),
                          getattr(snap, "name", None))
    out.update(
        counts_in_net=C.NET_LCC_PAYMENT if canon == C.PAYMENT else C.NET_YES,
        settled_with=_settled_with(_first(getattr(header, "airline_name", None),
                                          getattr(snap, "name", None), row.airline_name)),
        agent_signon=_first(row.source_agent_code, row.source_organization_code),
        airline_numeric=N.zfill3(getattr(snap, "iata_numeric_code", None)),
        airline_code=_upper(_first(row.airline_code, getattr(snap, "code", None))),
        airline_name=airline_name,
        booking_party_gstin=_upper(row.gst_number),
        product=C.PRODUCT_AIR,
        transaction_type=canon,
        source_txn_type=N.join_unique([row.transaction_type, row.movement_kind]),
        document_number=_first(row.account_transaction_id, row.payment_number),
        ticket_number=None,                 # an LCC issues no ticket; never fabricate one
        related_document=N.clean_text(row.parent_pnr),
        status=N.clean_text(row.payment_status),
        airline_pnr=N.clean_text(row.record_locator),
        gds_ref=N.clean_text(row.gds_record_locator),
        invoice_ref=N.clean_text(row.payment_number),
        passenger_name=N.clean_text(row.name1),   # `name` is the booking contact, not the pax
        pax_count=_int(row.bill_pax_count if row.bill_pax_count is not None else row.pax_count),
        issue_date=_as_date(row.transaction_date),
        booking_date=_as_date(row.booking_date),
        travel_date=_as_date(row.departure_date),
        sector=_sector(row),
        dom_intl=None if row.international is None else (
            "International" if row.international else "Domestic"),
        flight_no=N.join_unique(s.get("flight_no") for s in _dicts(row.segments)),
        booking_class=None,                 # LCC exports print a fare family, never an RBD
        fare_basis=N.clean_text(row.product_class),
        tour_code=N.clean_text(row.booking_promo_code),
        form_of_payment=N.clean_text(row.payment_method_code),
    )
    if is_account:
        C.add_flag(out, "LCC_MERGED_ACCOUNT_ROW")
    if out["issue_date"] is None:
        C.add_flag(out, "DATE_UNREADABLE")
    if out["fare_basis"] is not None:
        C.add_flag(out, "FARE_FAMILY_NOT_RBD")

    # ── currency ─────────────────────────────────────────────────────────────
    booking_cur, payment_cur = _upper(row.currency_code), _upper(row.foreign_currency_code)
    out["currency"] = _currency(out, (payment_cur or booking_cur) if is_account else booking_cur)
    if booking_cur and payment_cur and booking_cur != payment_cur:
        C.add_flag(out, "PAYMENT_CURRENCY_DIFFERS")

    # ── money (as stored) ────────────────────────────────────────────────────
    lc = lcc_codes.sums(row.taxes)
    if lc.unclassified_codes:
        C.add_flag(out, "LCC_CODE_UNCLASSIFIED")
    if _taxes_unreadable(row.taxes):
        C.add_flag(out, "AMOUNT_UNPARSEABLE")
    total, base = N.D(row.total), N.D(row.base_fare)
    yq, yr, k3 = lc.code("YQ"), lc.code("YR"), lc.code("GST")

    if lc.has_codes:
        # Unclassified codes stay inside Total Taxes (flagged) rather than vanish.
        total_taxes = N.dsum(lc.tax_total, lc.unclassified)
    elif row.taxes_total is not None:
        total_taxes = N.D(row.taxes_total)
    elif total is not None and base is not None:
        total_taxes = total - base
        C.add_flag(out, "TAXES_DERIVED")
    else:
        total_taxes = None

    other = None
    if total_taxes is not None:
        other = total_taxes - sum((v for v in (yq, yr, k3) if v is not None), Decimal("0"))
        if other * total_taxes < 0:
            C.add_flag(out, "NEG_TAX_RESIDUAL")

    net = total
    if canon == C.PAYMENT:
        net = N.D(row.payment_amount)
        C.add_flag(out, "LCC_PAYMENT_MOVEMENT")

    out.update(
        base_fare=base, yq=yq, yr=yr, k3=k3, other_taxes=other, total_taxes=total_taxes,
        gross_amount=total,
        penalty=N.magnitude(lc.penalty),
        ancillary=lc.ancillary if lc.ancillary is not None else N.D(row.other_ssr_total),
        service_fee=N.magnitude(lc.fee if lc.fee is not None else row.other_fee_total),
        net_payable=net,
    )
    if total is not None and (
        (movement == MOVEMENT_BOOKING_PAYMENT and total < 0)
        or (movement == MOVEMENT_REFUND and total > 0)
    ):
        C.add_flag(out, "LCC_NOTE_SIGN_CONFLICT")
    return C.apply_link(out, link)


def lcc_natural_key(row: Any) -> tuple:
    """DuplicateTracker key (design §C.10): the same statement line in a newer upload."""
    return (
        _upper(row.airline_code), _upper(row.record_locator),
        _upper(row.account_transaction_id), _upper(row.payment_number),
        row.transaction_date, N.D(row.total), _upper(row.name1),
    )


def _seg_text(segments: Any) -> str:
    return " · ".join(
        f"{s.get('route') or ''} {s.get('flight_no') or ''}".strip() for s in _dicts(segments)
    )


def _code_text(items: Any) -> str:
    return " · ".join(
        f"{s.get('code')} {s.get('amount') or ''}".strip() for s in _dicts(items) if s.get("code")
    )


class _SumsCache:
    """One-row memo so a wide ``Tax <CODE>`` pivot classifies each row's charges once.
    Holding the row itself (not its id) makes a stale hit impossible."""
    __slots__ = ("row", "sums")

    def __init__(self) -> None:
        self.row: Any = None
        self.sums = lcc_codes.LccCodeSums()

    def get(self, row: Any) -> lcc_codes.LccCodeSums:
        if self.row is not row:
            self.sums = lcc_codes.sums(getattr(row, "taxes", None))
            self.row = row
        return self.sums


def _detailed_columns(ctx: MapCtx) -> list[DetailCol]:
    include_pii = ctx.options.include_pii
    cols = provenance_cols(lambda row: _row_ref(LCC_DETAILED, row))
    for c in lcc_detailed_spec.CORE_COLUMNS:
        if pii.allowed(c["field"], include_pii):
            cols.append(DetailCol(c["header"], attr(c["field"]), _CORE_KIND.get(c["dtype"], "text")))

    def airline(row: Any, _ctx: MapCtx) -> Optional[str]:
        parts = (getattr(row, "airline_code", None), getattr(row, "airline_name", None))
        return " ".join(x for x in parts if x) or None

    def fmt(_row: Any, c: MapCtx) -> Optional[str]:
        return getattr(c.upload.header, "source_format", None) or c.upload.source_format

    cols += [
        DetailCol("Airline", airline),
        DetailCol("Departure Date", attr("departure_date"), "date", 12),
        DetailCol("Row Kind", attr("row_kind")),
        DetailCol("Movement", attr("movement_kind")),
        DetailCol("Bill Kind", attr("bill_kind")),
        DetailCol("Segments", lambda row, c: _seg_text(getattr(row, "segments", None)) or None,
                  "text", 24),
        DetailCol("SSR", lambda row, c: _code_text(getattr(row, "ssr", None)) or None, "text", 18),
        DetailCol("Format", fmt),
    ]
    cache = _SumsCache()
    for code in ctx.tax_codes:
        cols.append(DetailCol(f"Tax {code}", _pivot_getter(cache, code), "money", 10))
    # `extra` holds mapped fields with no typed column; the builder passes its keys.
    for key in ctx.extra_keys:
        if pii.allowed(key, include_pii):
            cols.append(DetailCol(f"extra.{key}", _extra_getter(key)))
    return cols


def _pivot_getter(cache: _SumsCache, code: str) -> Callable[[Any, MapCtx], Any]:
    return lambda row, ctx: cache.get(row).code(code)


def _extra_getter(key: str) -> Callable[[Any, MapCtx], Any]:
    def _get(row: Any, ctx: MapCtx) -> Any:
        extra = getattr(row, "extra", None)
        return extra.get(key) if isinstance(extra, dict) else None
    return _get


# ── LCC ledgers ──────────────────────────────────────────────────────────────

def _data(row: Any) -> dict:
    d = getattr(row, "data", None)
    return d if isinstance(d, dict) else {}


def _first_date(*vals: Any) -> Optional[date]:
    """First READABLE date — the same fallback the period filter applies."""
    for v in vals:
        d = N.parse_report_date(v)
        if d is not None:
            return d
    return None


def _ledger_ticket(code: Any, raw: Any) -> Optional[str]:
    """Only a genuine 3-digit code + 10-digit serial; LCC 'ticket' cells are often PNRs."""
    t, nonstandard = N.ticket13(code, raw)
    return t if t is not None and not nonstandard else None


def _ledger_to_common(slug: str, row: Any, ctx: MapCtx, link: Optional[LinkResult]) -> dict[str, Any]:
    out = _new_row(slug, row, ctx)
    src = get_source(slug)
    d = _data(row)
    snap = ctx.upload.airline
    numeric = N.zfill3(getattr(snap, "iata_numeric_code", None))
    flown, cta = slug == LCC_FLOWN, slug == LCC_CTA_BTA

    out.update(
        counts_in_net=C.NET_LEDGER,
        settled_with=_settled_with(N.clean_text(getattr(snap, "name", None))),
        agent_signon=(_first(d.get("source_agent_code"), d.get("source_organization_code"))
                      if slug == LCC_DIVIDED else _first(d.get("agency_code"), d.get("agent_name"))),
        airline_numeric=numeric,
        airline_code=_upper(_first(d.get("airline_code"), getattr(snap, "code", None))),
        airline_name=N.clean_text(getattr(snap, "name", None)),
        product=C.PRODUCT_AIR if (flown or cta) else None,
        passenger_name=N.clean_text(d.get("passenger_name")),
        booking_date=N.parse_report_date(d.get("booking_date")),
        sector=_first(d.get("sector")) or N.join_unique([d.get("origin"), d.get("destination")]),
        flight_no=N.clean_text(d.get("flight_number")),
        tour_code=N.clean_text(d.get("booking_promo_code")),
    )
    out["currency"] = _currency(out, d.get("currency"))

    if slug == LCC_DI:
        out.update(
            transaction_type=C.DEPOSIT,
            source_txn_type=N.clean_text(d.get("type")),
            issue_date=_first_date(d.get("deposit_date")),
        )
        gross = _money(out, d.get("amount"))
        out.update(gross_amount=gross, net_payable=gross)
    elif slug == LCC_DIVIDED:
        out.update(
            transaction_type=C.PNR_DIVIDE,
            related_document=N.clean_text(d.get("parent_pnr")),
            airline_pnr=N.clean_text(d.get("child_pnr")),
            issue_date=_first_date(d.get("divided_date"), d.get("booking_date")),
            form_of_payment=N.clean_text(d.get("payment_method")),
        )
        gross = _money(out, d.get("payment_amount"))
        out.update(gross_amount=gross, net_payable=gross)
    elif flown:
        fare_basis = N.clean_text(d.get("fare_basis"))
        product_class = N.clean_text(d.get("product_class"))
        out.update(
            transaction_type=C.FLOWN,
            document_number=N.clean_text(d.get("ticket_number")),
            ticket_number=_ledger_ticket(numeric, d.get("ticket_number")),
            status=_first(d.get("flown_status"), d.get("coupon_status")),
            airline_pnr=N.clean_text(d.get("pnr")),
            pax_count=_int(d.get("passenger_count")),
            issue_date=_first_date(d.get("flown_date"), d.get("travel_date"), d.get("booking_date")),
            travel_date=_first_date(d.get("travel_date"), d.get("flown_date")),
            booking_class=N.clean_text(d.get("booking_class")),
            fare_basis=fare_basis or product_class,
            form_of_payment=N.clean_text(d.get("payment_method")),
        )
        if fare_basis is None and product_class is not None:
            C.add_flag(out, "FARE_FAMILY_NOT_RBD")
        out.update(
            base_fare=_money(out, d.get("base_fare")),
            total_taxes=_money(out, d.get("taxes")),
            gross_amount=_money(out, d.get("total_fare")),
            commission=_money(out, d.get("commission_amount")),
            incentive_declared=_money(out, d.get("incentive_amount")),
            net_payable=_money(out, d.get("net_fare")),
        )
    else:  # CTA / BTA
        status = N.clean_text(d.get("payment_status"))
        out.update(
            transaction_type=C.REFUND if status and "REFUND" in status.upper() else C.PAYMENT,
            source_txn_type=N.clean_text(d.get("account_type")),
            booking_party_gstin=_upper(d.get("gst_number")),
            document_number=_first(d.get("ticket_number"), d.get("invoice_number")),
            ticket_number=_ledger_ticket(numeric, d.get("ticket_number")),
            status=status,
            airline_pnr=N.clean_text(d.get("pnr")),
            gds_ref=N.clean_text(d.get("reference_number")),
            invoice_ref=N.clean_text(d.get("invoice_number")),
            issue_date=_first_date(d.get("transaction_date"), d.get("booking_date")),
            travel_date=_first_date(d.get("travel_date")),
            booking_class=N.clean_text(d.get("booking_class")),
            form_of_payment=N.clean_text(d.get("card_scheme")),
        )
        gross = _money(out, d.get("total_amount"))
        out.update(
            base_fare=_money(out, d.get("base_fare")),
            total_taxes=_money(out, d.get("taxes")),
            gross_amount=gross,
            service_fee=N.magnitude(_money(out, d.get("fee_amount"))),
            net_payable=gross,
        )

    if out["issue_date"] is None:
        C.add_flag(out, "DATE_UNREADABLE")
    if src.schema_unverified:
        C.add_flag(out, "SCHEMA_UNVERIFIED")
    return C.apply_link(out, link)


def _k_text(v: Any) -> Optional[str]:
    return _upper(v)


def _k_date(v: Any) -> Optional[str]:
    """'01-Jul-2026' and '2026-07-01' are the same key; unreadable text keys as itself."""
    return N.date_key_py(v) or _k_text(v)


def _k_money(v: Any) -> Any:
    amt = N.parse_money(v)
    return amt if amt is not None else _k_text(v)


def ledger_natural_key(slug: str, row: Any, ctx: MapCtx) -> tuple:
    """DuplicateTracker key per design §C.10, scoped to the upload's declared airline."""
    d = _data(row)
    al_id = getattr(ctx.upload.airline, "tenant_airline_id", None)
    if slug == LCC_DI:
        return (al_id, _k_date(d.get("deposit_date")), _k_text(d.get("type")),
                _k_money(d.get("amount")), _k_text(d.get("detail")))
    if slug == LCC_DIVIDED:
        return (al_id, _k_text(d.get("parent_pnr")), _k_text(d.get("child_pnr")),
                _k_date(d.get("divided_date")), _k_money(d.get("payment_amount")))
    if slug == LCC_FLOWN:
        return (al_id, _k_text(_first(d.get("ticket_number"), d.get("pnr"))),
                _k_text(d.get("flight_number")), _k_date(d.get("flown_date")),
                _k_text(d.get("passenger_name")))
    if slug == LCC_CTA_BTA:
        return (al_id, _k_text(d.get("invoice_number")), _k_text(d.get("ticket_number")),
                _k_date(d.get("transaction_date")), _k_money(d.get("total_amount")))
    raise KeyError(f"{slug!r} is not an LCC ledger")


def ledger_pnrs(slug: str, row: Any) -> list[str]:
    """PNRs to probe the LCC Detailed PNR index with, in lookup order (design §C.8)."""
    d = _data(row)
    if slug in (LCC_FLOWN, LCC_CTA_BTA):
        raw = [d.get("pnr")]
    elif slug == LCC_DIVIDED:
        raw = [d.get("parent_pnr"), d.get("child_pnr")]
    elif slug == LCC_DI:
        raw = []
    else:
        raise KeyError(f"{slug!r} is not an LCC ledger")
    out: list[str] = []
    for v in raw:
        p = _upper(v)
        if p is not None and p not in out:
            out.append(p)
    return out


# The report contract names it in the singular.
ledger_pnr = ledger_pnrs


def _ledger_money_getter(field: str) -> Callable[[Any, MapCtx], Any]:
    """Detail value: a number when it parses, else the text exactly as stored."""
    def _get(row: Any, ctx: MapCtx) -> Any:
        raw = _data(row).get(field)
        amt = N.parse_money(raw)
        return amt if amt is not None else raw
    return _get


def _ledger_columns(slug: str, ctx: MapCtx) -> list[DetailCol]:
    include_pii = ctx.options.include_pii
    money = _LEDGER_MONEY[slug]
    cols = provenance_cols(lambda row: _row_ref(slug, row))
    seen: set[str] = set()
    for c in display_columns(slug):
        field = c["field"]
        seen.add(field)
        if field == "__format__":
            cols.append(DetailCol(c["header"], attr("source_format")))
        elif not pii.allowed(field, include_pii):
            continue
        elif field in money or c.get("kind") == "money":
            cols.append(DetailCol(c["header"], _ledger_money_getter(field), "money", 12))
        else:
            cols.append(DetailCol(c["header"], data_key(field)))
    for key in ctx.extra_keys:
        if key not in seen and pii.allowed(key, include_pii):
            cols.append(DetailCol(f"data.{key}", data_key(key)))
    return cols


# ── module API ───────────────────────────────────────────────────────────────

def detail_columns(source_key: str, ctx: MapCtx) -> list[DetailCol]:
    """Detail-sheet columns for one LCC source; personal data only with ``include_pii``."""
    _check_source(source_key)
    if source_key == LCC_DETAILED:
        return _detailed_columns(ctx)
    return _ledger_columns(source_key, ctx)


def to_common(source_key: str, row: Any, ctx: MapCtx, link: Optional[LinkResult] = None,
              **extra: Any) -> dict[str, Any]:
    """One stored row → a Combined row (design §B.4); ``link`` is applied last."""
    _check_source(source_key)
    if source_key == LCC_DETAILED:
        return _detailed_to_common(row, ctx, link)
    return _ledger_to_common(source_key, row, ctx, link)
