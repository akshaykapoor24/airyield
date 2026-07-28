"""Ticket Details — look up a ticket across all vendor-statement stores.

Enter a document/ticket number (or several, `|`-separated) and an airline type
(BSP / LCC / Third Party / All); we exact-match it against every store that could
hold it and return the full stored row(s), grouped by source. BSP + LCC-Detailed
match on typed indexed columns; the spec-repo LCC and Third-Party tables match on
their JSONB `data` keys. Read-only; scoped by tenant_id + created_by_id.
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
from sqlalchemy import select, or_, func
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
     "match": ["document_number", "ticket_number", "spdr_no", "rtdn"], "columns": BSP_COLUMNS},
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


def _predicate(src: dict, tokens_lower: list[str]):
    m = src["model"]
    if src["kind"] == "jsonb":
        conds = [func.lower(m.data[key].astext).in_(tokens_lower) for key in src["match"]]
    else:
        conds = [func.lower(getattr(m, col)).in_(tokens_lower) for col in src["match"]]
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
    groups: list[dict] = []
    for src in SOURCES:
        if at != "all" and src["group"] != at:
            continue
        rows = (await db.execute(
            select(src["model"]).where(
                src["model"].tenant_id == user.tenant_id,
                src["model"].created_by_id == user.id,
                _predicate(src, tokens_lower),
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
