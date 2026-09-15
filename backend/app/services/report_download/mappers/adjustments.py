"""BSPlink ADM / ACM / RA uploads → Combined rows and detail sheets.

WHY MEMOS NEVER COUNT HERE. An ADM, ACM or Refund Application is a BSPlink workflow record;
the money moves when BSP bills the matching ADMA / ACMA / RFND line on a settlement
statement, and that line is already a Combined row. Counting the memo too would double the
charge, so the default Counts In Net is "not yet billed" with the memo's status, and linking
replaces it with where the billed line was found.

Sign rules (design §B.2): the memo AMOUNT is type-signed — an ADM is a charge (+|amount|),
an ACM and an RA a credit (−|amount|) — because BSPlink exports print the magnitude with
inconsistent signs. The component columns are the raw ``airline's − agent's`` deltas and are
NOT re-signed: they explain the memo line by line, and their own sign says which side moved.

Every value in these tables is verbatim export text, so every amount and date goes through
``normalize`` and an unreadable amount is blanked and flagged, never guessed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from app.services import airline_adjustment_spec as spec
from app.services.report_download import columns as C
from app.services.report_download import normalize as N
from app.services.report_download import pii
from app.services.report_download.mappers.base import DetailCol, provenance_cols, row_ref as _ref
from app.services.report_download.types import LinkResult, MapCtx

SOURCE_KEYS: tuple[str, ...] = ("adm", "acm", "ra")

TABLES: dict[str, str] = {"adm": "airline_adm", "acm": "airline_acm", "ra": "airline_ra"}
SOURCE_LABELS: dict[str, str] = {"adm": "ADM", "acm": "ACM", "ra": "RA"}   # registry labels
CANON: dict[str, str] = {"adm": C.ADM, "acm": C.ACM, "ra": C.REFUND}

MEMO_TOLERANCE = Decimal("1.00")
_DPC_TRUE = frozenset({"YES", "Y", "TRUE", "T", "1"})
# Delta components in memo-identity order; (+1) adds to the memo, (−1) reduces it.
_COMPONENTS: tuple[tuple[str, int], ...] = (
    ("fare", 1), ("tax", 1), ("commission", -1), ("supplementary_commission", -1),
    ("tax_on_commission", 1), ("cancellation_penalty", 1), ("miscellaneous_fee", 1),
)


def _kind(source_key: str) -> str:
    k = (source_key or "").strip().lower()
    if k not in TABLES:
        raise ValueError(f"mappers.adjustments does not map {source_key!r}")
    return k


def memo_row_ref(kind: str, row: Any) -> str:
    return _ref(TABLES[_kind(kind)], getattr(row, "id", None))


def sent_to_dpc(row: Any) -> bool:
    """BSPlink prints ``Yes`` / ``No`` (other exports ``Y`` / ``TRUE`` / ``1``)."""
    v = N.clean_text(getattr(row, "sent_to_dpc", None))
    return v is not None and v.upper() in _DPC_TRUE


def status_text(row: Any) -> Optional[str]:
    """Memo status with ``; sent to DPC`` appended when BSPlink already passed it on."""
    s = N.clean_text(getattr(row, "status", None))
    if sent_to_dpc(row):
        return f"{s}; sent to DPC" if s else "Sent to DPC"
    return s


def not_billed_reason(row: Any) -> str:
    """Default Counts In Net for a memo linking did not find billed (design §B.3 rule 3)."""
    s = N.clean_text(getattr(row, "status", None))
    return f"{C.NET_MEMO_NOT_BILLED} (status: {s or 'unknown'}{', sent to DPC' if sent_to_dpc(row) else ''})"


def _airline(row: Any, ctx: MapCtx) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """``(numeric, iata, name)``. BSPlink's Airline Code is the 3-digit accounting code; a
    designator typed there instead ("AI") is resolved through the master the other way."""
    raw = N.zfill3(getattr(row, "airline_code", None))
    if raw is None:
        return None, None, None
    if raw.isdigit():
        info = ctx.airlines.numeric(raw)
        return raw, info.iata_code if info else None, info.name if info else None
    info = ctx.airlines.iata(raw)
    return (info.numeric_code if info else None), raw, (info.name if info else None)


def memo_code(row: Any) -> Optional[str]:
    raw = N.zfill3(getattr(row, "airline_code", None))
    return raw if raw and raw.isdigit() else None


def memo_natural_key(kind: str, row: Any) -> tuple:
    """DuplicateTracker key (design §C.10): ``(packed document key or raw number, amount)``."""
    _kind(kind)
    raw_doc = N.clean_text(getattr(row, "document_number", None))
    key = N.doc_key(memo_code(row), raw_doc)
    return (N.pack(key) if key is not None else raw_doc, N.parse_money(getattr(row, "amount", None)))


def memo_date(kind: str, row: Any) -> Optional[date]:
    """Issue date users recognise (RA: application date), else BSPlink's reporting date."""
    primary = "application_date" if _kind(kind) == "ra" else "issue_date"
    return (N.parse_report_date(getattr(row, primary, None))
            or N.parse_report_date(getattr(row, "reporting_date", None)))


def _money(row: Any, name: str, out: Optional[dict]) -> Optional[Decimal]:
    amount, bad = N.parse_money_checked(getattr(row, name, None))
    if bad and out is not None:
        C.add_flag(out, "AMOUNT_UNPARSEABLE")
    return amount


def _delta(row: Any, part: str, out: Optional[dict]) -> Optional[Decimal]:
    """``airline's − agent's`` for one component; None when neither side printed a number.
    An unreadable side blanks the delta (flagged) rather than treating it as 0."""
    airline, bad_a = N.parse_money_checked(getattr(row, f"airlines_{part}", None))
    agent, bad_b = N.parse_money_checked(getattr(row, f"agents_{part}", None))
    if bad_a or bad_b:
        if out is not None:
            C.add_flag(out, "AMOUNT_UNPARSEABLE")
        return None
    if airline is None and agent is None:
        return None
    return (airline or Decimal(0)) - (agent or Decimal(0))


def to_common(
    source_key: str,
    row: Any,
    ctx: MapCtx,
    link: Optional[LinkResult] = None,
    **extra: Any,
) -> dict[str, Any]:
    """One ADM / ACM / RA row → Combined dict (design §B.4, "ADM/ACM · RA" column)."""
    kind = _kind(source_key)
    canon = CANON[kind]
    is_ra = kind == "ra"
    out = C.new_common_row(ctx, category=C.CAT_BSP, source_type=SOURCE_LABELS[kind],
                           row_ref=memo_row_ref(kind, row))
    numeric, iata, name = _airline(row, ctx)
    code = memo_code(row)

    # ── parties / document ──
    out.update(
        settled_with="BSP (BSPlink)",
        agent_signon=N.clean_text(getattr(row, "agent_code", None)),
        airline_numeric=numeric, airline_code=iata, airline_name=name,
        product=C.PRODUCT_AIR,
        transaction_type=canon,
        source_txn_type="RA" if is_ra else (N.clean_text(getattr(row, "type", None)) or SOURCE_LABELS[kind]),
        document_number=N.clean_text(getattr(row, "document_number", None)),
        status=status_text(row),
        pax_count=0,
    )
    if is_ra:
        ticket, nonstandard = N.ticket13(code, getattr(row, "rtdn_number", None))
        out.update(ticket_number=ticket, related_document=ticket,
                   passenger_name=N.clean_text(getattr(row, "passenger", None)),
                   form_of_payment=N.clean_text(getattr(row, "forms_of_payment", None)))
        if nonstandard:
            C.add_flag(out, "TICKET_NO_NONSTANDARD")
    else:
        out["related_document"] = N.ticket13(code, getattr(row, "related_document", None))[0]
        out["dom_intl"] = N.stat_segment(getattr(row, "statistical_code", None))

    # ── dates / currency ──
    issue = memo_date(kind, row)
    if issue is None:
        C.add_flag(out, "DATE_UNREADABLE")
    currency = N.clean_text(getattr(row, "currency", None))
    if currency is None:
        currency = "INR"
        C.add_flag(out, "CURRENCY_ASSUMED")
    out.update(issue_date=issue, settlement_period=N.clean_text(getattr(row, "period", None)),
               currency=currency.upper())

    # ── money ──
    amount = _money(row, "amount", out)
    memo = N.signed(amount, canon)          # ADM +|a|; ACM and RA −|a|
    out.update(gross_amount=memo, net_payable=memo)
    if not is_ra:
        deltas = {part: _delta(row, part, out) for part, _ in _COMPONENTS}
        out.update(
            base_fare=deltas["fare"],
            total_taxes=deltas["tax"],
            commission=deltas["commission"],
            supp_commission=deltas["supplementary_commission"],
            tax_on_commission=deltas["tax_on_commission"],
            penalty=N.magnitude(deltas["cancellation_penalty"]),
            service_fee=N.magnitude(deltas["miscellaneous_fee"]),
        )
        if amount is not None and any(v is not None for v in deltas.values()):
            explained = sum(((deltas[part] or Decimal(0)) * sign for part, sign in _COMPONENTS), Decimal(0))
            if abs(abs(explained) - abs(amount)) > MEMO_TOLERANCE:
                C.add_flag(out, "MEMO_COMPONENTS_MISMATCH")

    out["counts_in_net"] = not_billed_reason(row)
    return C.apply_link(out, link)


# ── detail sheets ────────────────────────────────────────────────────────────

def _is_money_field(field: str) -> bool:
    return field == "amount" or field.startswith(("airlines_", "agents_"))


def _getter(field: str) -> Any:
    if _is_money_field(field):
        def _money_or_text(row: Any, ctx: MapCtx) -> Any:
            raw = getattr(row, field, None)
            amount, bad = N.parse_money_checked(raw)
            if amount is not None:
                return amount
            return raw if bad else None          # keep unreadable text; blank stays blank
        return _money_or_text
    return lambda row, ctx: getattr(row, field, None)


def detail_columns(source_key: str, ctx: MapCtx) -> list[DetailCol]:
    """``ADM`` / ``ACM`` / ``RA`` sheet: provenance, then the BSPlink export headers in file
    order. Contact name / e-mail / phone only with ``include_pii``; amounts as numbers when
    readable, else the exported text."""
    kind = _kind(source_key)
    cols = provenance_cols(lambda row: memo_row_ref(kind, row))
    for header in spec.HEADERS[kind]:
        field = spec.norm(header)
        if not pii.allowed(field, ctx.options.include_pii):
            continue
        money = _is_money_field(field)
        cols.append(DetailCol(header, _getter(field), "money" if money else "text", 12 if money else 14))
    return cols
