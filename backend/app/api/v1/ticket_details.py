"""Ticket Details — look up a ticket across all vendor-statement stores.

Enter a document/ticket number or PNR (or several, `|`-separated) and an airline
type (BSP / LCC / Third Party / All); we match it against every store that could
hold it and return the full stored row(s), grouped by source. BSP + LCC-Detailed
match on typed indexed columns; the spec-repo LCC and Third-Party tables match on
their JSONB `data` keys. Read-only; scoped by tenant_id + created_by_id.

Matching is not a bare equality test. A ticket is printed with punctuation and its
airline stock prefix (098-4846834428) but stored bare (4846834428), so each token
is also compared through the same two normalisations BSP Reconciliation joins on
(`norm_tn` and `_alt_key` in services/bsp_reconciliation.py). Without that the two
screens disagree about whether a ticket exists.

Note what each source can be found BY, which is not the same everywhere:
  * BSP           — document/ticket number, SPDR, RTDN, and conjunction documents
  * LCC Detailed  — PNR only. The 27-column standard spec has no ticket-number
                    column, so a ticket number can never match it.
  * everything else — ticket number and/or PNR, per its `match` list below.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, or_, func, cast
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import TEXT
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.bsp_statement import BspStatementRow, BspTaxBreakup
from app.models.lcc_detailed import LccDetailed
from app.models.statement_row import (
    LccFlownReport, LccCtaBta, LccDividedPnr, ThirdPartyGds, ThirdPartyLcc,
)
from app.services import statement_spec
from app.services import lcc_detailed_spec
from app.services.bsp_reconciliation import norm_tn, _alt_key
from app.services.bsp_export import _tax_buckets, _join, _f, _s

router = APIRouter()


# ── BSP display columns (mirror the detailed rows table / bsp_export) ────────
BSP_COLUMNS: list[dict] = [
    {"header": "Document #", "field": "document_number"},
    {"header": "Ticket No", "field": "ticket_number"},
    {"header": "Txn", "field": "transaction_type"},
    {"header": "Air", "field": "airline_accounting_code"},
    {"header": "Airline", "field": "airline_name"},
    {"header": "Date", "field": "issue_date"},
    {"header": "CPUI", "field": "cpui"},
    {"header": "NR", "field": "nr_code"},
    {"header": "STAT", "field": "stat"},
    {"header": "FOP", "field": "form_of_payment"},
    {"header": "Txn Amt", "field": "transaction_amount"},
    {"header": "Fare", "field": "fare_amount"},
    {"header": "Tax", "field": "tax"},
    {"header": "F&C", "field": "fc"},
    {"header": "Pen", "field": "pen"},
    {"header": "Net Sales", "field": "net_sales"},
    {"header": "Std %", "field": "standard_commission_rate"},
    {"header": "Std Comm", "field": "standard_commission_amount"},
    {"header": "Supp %", "field": "supplier_discount_rate"},
    {"header": "Supp Disc", "field": "supplier_discount_amount"},
    {"header": "Tax/Comm", "field": "tax_on_commission"},
    {"header": "Balance", "field": "balance_payable"},
    {"header": "Tour", "field": "tour"},
    {"header": "Alt Docs", "field": "alt_document_numbers"},
    {"header": "SPDR No", "field": "spdr_no"},
    {"header": "RTDN", "field": "rtdn"},
    {"header": "ESAC", "field": "esac"},
    {"header": "WAVR", "field": "wavr"},
]

LCC_DETAILED_COLUMNS: list[dict] = [
    {"header": c["header"], "field": c["field"]} for c in lcc_detailed_spec.CORE_COLUMNS
]

# Each store that can hold a ticket, and the fields to exact-match a doc/ticket/PNR on.
# kind: "bsp" (typed cols + tax breakup) | "lcc-detailed" (typed cols) | "jsonb" (data JSONB)
SOURCES: list[dict] = [
    {"key": "bsp", "label": "BSP", "group": "bsp", "kind": "bsp", "model": BspStatementRow,
     "match": ["document_number", "ticket_number", "spdr_no", "rtdn"],
     # JSONB string arrays searched by element. `alt_document_numbers` holds the
     # +TKTT conjunction documents and is already displayed as "Alt Docs".
     "match_json_array": ["alt_document_numbers"],
     "columns": BSP_COLUMNS},
    {"key": "lcc-detailed", "label": "LCC · Detailed Statement", "group": "lcc", "kind": "lcc-detailed",
     "model": LccDetailed, "match": ["record_locator", "gds_record_locator"], "columns": LCC_DETAILED_COLUMNS},
    {"key": "lcc-flown-report", "label": "LCC · Flown Report", "group": "lcc", "kind": "jsonb",
     "model": LccFlownReport, "match": ["ticket_number", "pnr"], "columns": statement_spec.columns("lcc-flown-report")},
    {"key": "lcc-cta-bta", "label": "LCC · CTA/BTA Report", "group": "lcc", "kind": "jsonb",
     "model": LccCtaBta, "match": ["ticket_number", "pnr", "invoice_number"], "columns": statement_spec.columns("lcc-cta-bta")},
    {"key": "lcc-divided-pnr", "label": "LCC · Divided PNR", "group": "lcc", "kind": "jsonb",
     "model": LccDividedPnr, "match": ["parent_pnr", "child_pnr"], "columns": statement_spec.columns("lcc-divided-pnr")},
    {"key": "tp-gds", "label": "Third Party · GDS", "group": "third-party", "kind": "jsonb",
     "model": ThirdPartyGds, "match": ["ticket_number", "pnr", "gds_pnr"], "columns": statement_spec.columns("tp-gds")},
    {"key": "tp-lcc", "label": "Third Party · LCC", "group": "third-party", "kind": "jsonb",
     "model": ThirdPartyLcc, "match": ["pnr", "airline_pnr", "booking_reference", "invoice_number"],
     "columns": statement_spec.columns("tp-lcc")},
]

_GROUPS = {"bsp", "lcc", "third-party"}
_PER_SOURCE_LIMIT = 500


class TicketGroup(BaseModel):
    source: str
    label: str
    columns: list[dict]
    rows: list[dict]
    count: int


class TicketLookupResponse(BaseModel):
    query: list[str]
    airline_type: str
    total: int
    groups: list[TicketGroup]


def _parse_tokens(document: Optional[str]) -> list[str]:
    """Split the document input on | and newlines into unique, trimmed tokens."""
    if not document:
        return []
    out: list[str] = []
    for part in re.split(r"[|\n\r]+", document):
        t = part.strip()
        if t and t not in out:
            out.append(t)
    return out


def _val(v) -> Any:
    """Make a typed-column value JSON-safe (Decimal→float, date→iso, list→joined)."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return _join(v)
    if isinstance(v, dict):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _norm_sql(col):
    """SQL mirror of services.bsp_reconciliation.norm_tn.

    Strip non-alphanumerics, drop leading zeros, uppercase — so a document typed
    as printed ("098-4846834428", "0984846834428") lands on the same key as the
    bare "4846834428" the statement stores.
    """
    return func.upper(func.ltrim(func.regexp_replace(col, r"[^0-9A-Za-z]", "", "g"), "0"))


def _alt_sql(col):
    """SQL mirror of services.bsp_reconciliation._alt_key — last 10 alphanumerics.

    A ticket is printed with its 3-digit airline stock prefix (098-4846834428)
    but stored without it, so normalising alone still misses. Reconciliation
    already joins on the trailing 10; searching has to agree with it or the two
    screens disagree about whether the same ticket exists.
    """
    return func.right(func.regexp_replace(col, r"[^0-9A-Za-z]", "", "g"), 10)


def _predicate(
    src: dict,
    tokens: list[str],
    tokens_lower: list[str],
    tokens_norm: list[str],
    tokens_alt: list[str],
):
    """Match a token against every identifier this source can be found by.

    Three passes, OR'd: the exact (indexed) one first, then the two normalised
    forms. Previously only the exact one existed, which meant Ticket Search
    answered "not found" for a ticket that BSP Reconciliation had already
    matched — the same number, written the way the agent reads it off the coupon.
    """
    m = src["model"]
    cols = (
        [m.data[key].astext for key in src["match"]]
        if src["kind"] == "jsonb"
        else [getattr(m, col) for col in src["match"]]
    )

    conds = [func.lower(c).in_(tokens_lower) for c in cols]
    if tokens_norm:
        conds += [_norm_sql(c).in_(tokens_norm) for c in cols]
    if tokens_alt:
        conds += [_alt_sql(c).in_(tokens_alt) for c in cols]

    # Conjunction tickets: a long itinerary is issued across several documents,
    # and the extra ones live in this JSONB array. The list is already shown in
    # the results as "Alt Docs" but was never searchable, so looking up a
    # conjunction number found nothing while the ticket sat right there.
    # Conjunction tickets: a long itinerary is issued across several documents,
    # and the extra ones live in this JSONB array. The list is already shown in
    # the results as "Alt Docs" but was never searchable, so looking up a
    # conjunction number found nothing while the ticket sat right there.
    #
    # `?|` tests array membership and can use a GIN index, so rather than
    # normalising every element we hand it every form the token could have been
    # stored as. Conjunction documents are bare digits, so case never matters.
    if tokens_norm or tokens_alt:
        json_tokens = sorted({*tokens, *tokens_norm, *tokens_alt})
    else:
        json_tokens = sorted(set(tokens))
    for key in src.get("match_json_array", []):
        conds.append(getattr(m, key).op("?|")(cast(json_tokens, ARRAY(TEXT))))

    return or_(*conds)


async def _bsp_row_dicts(db: AsyncSession, rows) -> list[dict]:
    by_row: dict[int, list] = defaultdict(list)
    ids = [r.id for r in rows]
    if ids:
        taxes = (await db.execute(
            select(BspTaxBreakup).where(BspTaxBreakup.bsp_row_id.in_(ids))
        )).scalars().all()
        for t in taxes:
            by_row[t.bsp_row_id].append(t)
    out = []
    for r in rows:
        tx = by_row.get(r.id, [])
        tax, fee, pen = _tax_buckets(tx)
        if pen == 0.0 and not any(getattr(t, "component_type", None) == "PENALTY" for t in tx):
            pen = _f(r.penalty_amount)
        out.append({
            "id": r.id,
            "document_number": _s(r.document_number),
            "ticket_number": _s(r.ticket_number),
            "transaction_type": _s(r.transaction_type),
            "airline_accounting_code": _s(r.airline_accounting_code),
            "airline_name": _s(r.airline_name),
            "issue_date": _s(r.issue_date),
            "cpui": _s(r.cpui),
            "nr_code": _s(r.nr_code),
            "stat": _s(r.stat),
            "form_of_payment": _s(r.form_of_payment),
            "transaction_amount": _f(r.transaction_amount),
            "fare_amount": _f(r.fare_amount),
            "tax": round(tax, 2),
            "fc": round(fee, 2),
            "pen": round(pen, 2),
            "net_sales": _f(r.net_sales),
            "standard_commission_rate": _f(r.standard_commission_rate),
            "standard_commission_amount": _f(r.standard_commission_amount),
            "supplier_discount_rate": _f(r.supplier_discount_rate),
            "supplier_discount_amount": _f(r.supplier_discount_amount),
            "tax_on_commission": _f(r.tax_on_commission),
            "balance_payable": _f(r.balance_payable),
            "tour": _join(r.tour),
            "alt_document_numbers": _join(r.alt_document_numbers),
            "spdr_no": _s(r.spdr_no),
            "rtdn": _s(r.rtdn),
            "esac": _s(r.esac),
            "wavr": _s(r.wavr),
        })
    return out


def _typed_row_dicts(rows, columns: list[dict]) -> list[dict]:
    fields = [c["field"] for c in columns]
    return [{"id": r.id, **{f: _val(getattr(r, f, None)) for f in fields}} for r in rows]


def _jsonb_row_dicts(rows) -> list[dict]:
    return [{"id": r.id, **{k: _val(v) for k, v in (r.data or {}).items()}} for r in rows]


async def _run_lookup(document: Optional[str], airline_type: str, db: AsyncSession, user: User):
    tokens = _parse_tokens(document)
    if not tokens:
        raise HTTPException(status_code=400, detail="Enter at least one document or ticket number.")
    at = (airline_type or "all").lower()
    if at != "all" and at not in _GROUPS:
        raise HTTPException(status_code=400, detail="airline_type must be one of: all, bsp, lcc, third-party.")

    tokens_lower = [t.lower() for t in tokens]
    # Same two keys BSP Reconciliation joins on, so both screens agree about what
    # counts as the same ticket. _alt_key returns None below 10 characters, which
    # keeps a 6-character PNR off the trailing-10 path entirely.
    tokens_norm = sorted({n for n in (norm_tn(t) for t in tokens) if n})
    tokens_alt = sorted({a for a in (_alt_key(t) for t in tokens) if a})

    groups: list[dict] = []
    for src in SOURCES:
        if at != "all" and src["group"] != at:
            continue
        rows = (await db.execute(
            select(src["model"]).where(
                src["model"].tenant_id == user.tenant_id,
                src["model"].created_by_id == user.id,
                _predicate(src, tokens, tokens_lower, tokens_norm, tokens_alt),
            ).limit(_PER_SOURCE_LIMIT)
        )).scalars().all()
        if not rows:
            continue
        if src["kind"] == "bsp":
            row_dicts = await _bsp_row_dicts(db, rows)
        elif src["kind"] == "lcc-detailed":
            row_dicts = _typed_row_dicts(rows, src["columns"])
        else:
            row_dicts = _jsonb_row_dicts(rows)
        groups.append({
            "source": src["key"], "label": src["label"],
            "columns": src["columns"], "rows": row_dicts, "count": len(row_dicts),
        })
    return tokens, at, groups


@router.get("/lookup", response_model=TicketLookupResponse)
async def lookup_ticket_details(
    document: str = Query(..., description="Document/ticket number(s); separate multiple with | (pipe)."),
    airline_type: str = Query("all", description="all | bsp | lcc | third-party"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tokens, at, groups = await _run_lookup(document, airline_type, db, current_user)
    return TicketLookupResponse(
        query=tokens, airline_type=at,
        total=sum(g["count"] for g in groups),
        groups=[TicketGroup(**g) for g in groups],
    )


@router.get("/export")
async def export_ticket_details(
    document: str = Query(...),
    airline_type: str = Query("all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.ticket_details_export import build_ticket_details_xlsx
    _, _, groups = await _run_lookup(document, airline_type, db, current_user)
    buf = build_ticket_details_xlsx(groups)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ticket-details.xlsx"},
    )
