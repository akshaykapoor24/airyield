from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, date
from typing import Optional

from dateutil import parser as dateutil_parser
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, status, Query
from fastapi.responses import StreamingResponse
import pandas as pd
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline import Airline
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User
from app.schemas.uploaded_ticket import (
    TicketExtractionPreview,
    TicketRow,
    ConfirmTicketUploadPayload,
    ConfirmTicketUploadResult,
    UploadedTicketRead,
    RunCalculationResult,
    BatchRunCalculationResult,
    UploadedTicketUpdate,
    MatchDiagnosisResponse,
)
from pydantic import BaseModel
from app.services.deal_matching import DealMatchingService
from app.services.ticket_extraction import TicketExtractionService, TEMPLATE_HEADERS

router = APIRouter()


class DealMatchSummary(BaseModel):
    deal_id:              int
    deal_type:            str
    deal_name:            str
    deal_no:              str
    calculated_incentive: Optional[float]
    valid_from:           Optional[date]
    valid_to:             Optional[date]
    deal_maker_name:      Optional[str]
    is_best:              bool

# ── Template download ──────────────────────────────────────────────────────

@router.get("/template/download")
async def download_ticket_template(
    current_user: User = Depends(get_current_user),
):
    """Return a blank XLSX file with the expected column headers as a download."""
    df = pd.DataFrame(columns=TEMPLATE_HEADERS)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ticket_template.xlsx"},
    )


# ── legacy endpoints (kept for backward compatibility) ─────────────────────

@router.get("/legacy", response_model=list)
async def list_tickets_legacy(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return []


# ── Upload flow: Step 1 — extract / preview ────────────────────────────────

@router.post("/upload/extract", response_model=TicketExtractionPreview)
async def extract_ticket_file(
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """Step 1 — Upload an XLS/XLSX file, parse it and return a preview for user review.

    column_mapping (optional form field): JSON string of {canonical: xls_col} pairs
    provided by the user after reviewing the mapping UI.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    max_mb = 50
    chunk = await file.read(max_mb * 1024 * 1024 + 1)
    if len(chunk) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB limit.")

    mapping_dict: Optional[dict[str, str]] = None
    if column_mapping:
        try:
            mapping_dict = json.loads(column_mapping)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=400, detail="column_mapping must be a valid JSON string.")

    try:
        result = await TicketExtractionService.extract(chunk, file.filename, column_mapping=mapping_dict)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return TicketExtractionPreview(
        file_name=result["file_name"],
        total_rows=result["total_rows"],
        rows=[TicketRow(**r) for r in result["rows"]],
        warnings=result.get("warnings", []),
        xls_columns=result.get("xls_columns", []),
        suggested_mapping=result.get("suggested_mapping", {}),
        is_template_match=result.get("is_template_match", True),
        sample_row=result.get("sample_row", {}),
    )


# ── Upload flow: Step 2 — confirm / save ──────────────────────────────────

@router.post(
    "/upload/confirm",
    response_model=ConfirmTicketUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_ticket_upload(
    payload: ConfirmTicketUploadPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Step 2 — User has reviewed the preview and confirms. Save rows to DB."""
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No rows to save.")

    # Batch-lookup airline names by IATA code to populate airline_name
    codes = {r.airlines_code for r in payload.rows if r.airlines_code}
    airline_map: dict[str, str] = {}
    if codes:
        res = await db.execute(select(Airline).where(Airline.iata_code.in_(codes)))
        for airline in res.scalars():
            airline_map[airline.iata_code] = airline.name

    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()

    for row in payload.rows:
        resolved_airline_name = row.airline_name or airline_map.get(row.airlines_code or "", None)
        ticket = UploadedTicket(
            batch_id=batch_id,
            file_name=payload.file_name,
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            created_at=now,
            booking_ref=row.booking_ref,
            segment_type=row.segment_type,
            invoice_type=row.invoice_type,
            invoice_no=row.invoice_no,
            ticket_date=row.ticket_date,
            last_name=row.last_name,
            first_name=row.first_name,
            sector=row.sector,
            booking_class=row.booking_class,
            departure_datetime=row.departure_datetime,
            gds_pnr=row.gds_pnr,
            airlines_code=row.airlines_code,
            ticket_number=row.ticket_number,
            sell_fare=row.sell_fare,
            sell_tax=row.sell_tax,
            sell_tax_yq=row.sell_tax_yq,
            sale_yr=row.sale_yr,
            sale_k3=row.sale_k3,
            rei_sell=row.rei_sell,
            seat_selection=row.seat_selection,
            excess_baggage=row.excess_baggage,
            meals=row.meals,
            rfd_sell=row.rfd_sell,
            can_charge=row.can_charge,
            booking_fee_sell=row.booking_fee_sell,
            cgst_sell=row.cgst_sell,
            sgst_sell=row.sgst_sell,
            igst_sell=row.igst_sell,
            comm_sell=row.comm_sell,
            adm=row.adm,
            incentive_sell=row.incentive_sell,
            dis_sell=row.dis_sell,
            tds_sell=row.tds_sell,
            total_amt=row.total_amt,
            paid_by_credit_card=row.paid_by_credit_card,
            net_amt=row.net_amt,
            cc=row.cc,
            acc_code=row.acc_code,
            sold_to=row.sold_to,
            customer_name=row.customer_name,
            airline_name=resolved_airline_name,
        )
        db.add(ticket)

    await db.commit()
    return ConfirmTicketUploadResult(batch_id=batch_id, created_count=len(payload.rows))


# ── List uploaded tickets ──────────────────────────────────────────────────

@router.get("/uploads", response_model=list[UploadedTicketRead])
async def list_uploaded_tickets(
    skip:     int = 0,
    limit:    int = 500,
    batch_id: Optional[str] = Query(None),
    db:       AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all uploaded ticket rows for the current tenant (full data)."""
    q = select(UploadedTicket).where(
        UploadedTicket.tenant_id == current_user.tenant_id
    ).order_by(UploadedTicket.created_at.desc()).offset(skip).limit(limit)

    if batch_id:
        q = q.where(UploadedTicket.batch_id == batch_id)

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/uploads/{ticket_id}", response_model=UploadedTicketRead)
async def get_uploaded_ticket(
    ticket_id: int,
    db:        AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id == ticket_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# ── Run Calculation helpers ────────────────────────────────────────────────

def _parse_travel_date(departure_datetime: str | None, ticket_date: str | None) -> date | None:
    for raw in (departure_datetime, ticket_date):
        if not raw:
            continue
        try:
            return dateutil_parser.parse(raw, dayfirst=True).date()
        except Exception:
            continue
    return None


async def _run_single(
    ticket: UploadedTicket,
    db: AsyncSession,
    tenant_id: int,
) -> RunCalculationResult:
    """Core matching logic shared by single and batch endpoints."""
    if not ticket.airlines_code:
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message="No airline code on ticket.",
        )

    raw_code = (ticket.airlines_code or "").strip()
    # Normalize numeric codes: "98" → "098", "57" → "057", "217" → "217"
    code_variants = list({raw_code, raw_code.zfill(3)}) if raw_code.isdigit() else [raw_code]

    airline_res = await db.execute(
        select(Airline).where(
            or_(
                Airline.iata_code.in_(code_variants),
                Airline.icao_code.in_(code_variants),
            )
        )
    )
    airline = airline_res.scalar_one_or_none()
    if not airline:
        ticket.matched_deal_id   = None
        ticket.matched_deal_type = None
        ticket.matched_deal_name = None
        ticket.calculated_incentive = None
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message=f"Airline code '{ticket.airlines_code}' not in master.",
        )

    travel_date = _parse_travel_date(ticket.departure_datetime, ticket.ticket_date)
    if not travel_date:
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message="Could not parse travel date.",
        )

    match = await DealMatchingService.find_best_deal(
        db=db,
        airline_name=airline.name,
        travel_date=travel_date,
        tenant_id=tenant_id,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
    )

    if match:
        ticket.matched_deal_id       = match.deal_id
        ticket.matched_deal_type     = match.deal_type
        ticket.matched_deal_name     = match.deal_name
        ticket.calculated_incentive  = match.calculated_incentive
        return RunCalculationResult(
            ticket_id=ticket.id, matched=True,
            matched_deal_id=match.deal_id,
            matched_deal_type=match.deal_type,
            matched_deal_name=match.deal_name,
            calculated_incentive=match.calculated_incentive,
            message=f"Matched {match.deal_type} deal ID {match.deal_id}.",
        )
    else:
        ticket.matched_deal_id       = None
        ticket.matched_deal_type     = None
        ticket.matched_deal_name     = None
        ticket.calculated_incentive  = None
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message="No matching approved deal found.",
        )


# ── Single ticket run-calculation ──────────────────────────────────────────

@router.patch("/uploads/{ticket_id}/run-calculation", response_model=RunCalculationResult)
async def run_calculation(
    ticket_id: int,
    db:        AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Match a single ticket against approved deals and persist the result."""
    res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id == ticket_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
        )
    )
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    result = await _run_single(ticket, db, current_user.tenant_id)
    await db.commit()
    return result


# ── Batch run-calculation ─────────────────────────────────────────────────

@router.patch("/uploads/run-all-calculation", response_model=BatchRunCalculationResult)
async def run_all_calculation(
    batch_id: Optional[str] = Query(None, description="Limit to a specific upload batch; omit for all tickets"),
    db:       AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Match all tickets (or all in a batch) against approved deals."""
    q = select(UploadedTicket).where(UploadedTicket.tenant_id == current_user.tenant_id)
    if batch_id:
        q = q.where(UploadedTicket.batch_id == batch_id)

    res = await db.execute(q)
    tickets = res.scalars().all()

    processed = matched = unmatched = errors = 0
    for ticket in tickets:
        try:
            result = await _run_single(ticket, db, current_user.tenant_id)
            processed += 1
            if result.matched:
                matched += 1
            else:
                unmatched += 1
        except Exception:
            errors += 1

    await db.commit()
    return BatchRunCalculationResult(
        processed=processed,
        matched=matched,
        unmatched=unmatched,
        errors=errors,
    )


# ── Update ticket fields ──────────────────────────────────────────────────

@router.patch("/uploads/{ticket_id}", response_model=UploadedTicketRead)
async def update_uploaded_ticket(
    ticket_id: int,
    payload:   UploadedTicketUpdate,
    db:        AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update editable fields on an uploaded ticket."""
    res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id == ticket_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
        )
    )
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    await db.commit()
    await db.refresh(ticket)
    return ticket


# ── Delete a ticket ───────────────────────────────────────────────────────

@router.delete("/uploads/{ticket_id}", status_code=204)
async def delete_uploaded_ticket(
    ticket_id: int,
    db:        AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete an uploaded ticket."""
    res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id == ticket_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
        )
    )
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    await db.delete(ticket)
    await db.commit()


# ── All matching deals for a ticket (on-demand, for popup) ────────────────

@router.get("/uploads/{ticket_id}/matched-deals", response_model=list[DealMatchSummary])
async def get_all_matched_deals(
    ticket_id: int,
    db:        AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all approved deals that match the given ticket (for the multi-deal popup)."""
    res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id == ticket_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
        )
    )
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if not ticket.airlines_code:
        return []

    raw_code = (ticket.airlines_code or "").strip()
    code_variants = list({raw_code, raw_code.zfill(3)}) if raw_code.isdigit() else [raw_code]
    airline_res = await db.execute(
        select(Airline).where(
            or_(
                Airline.iata_code.in_(code_variants),
                Airline.icao_code.in_(code_variants),
            )
        )
    )
    airline = airline_res.scalar_one_or_none()
    if not airline:
        return []

    travel_date = _parse_travel_date(ticket.departure_datetime, ticket.ticket_date)
    if not travel_date:
        return []

    all_matches = await DealMatchingService.find_all_deals(
        db=db,
        airline_name=airline.name,
        travel_date=travel_date,
        tenant_id=current_user.tenant_id,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
    )

    best_id = all_matches[0].deal_id if all_matches else None
    return [
        DealMatchSummary(
            deal_id=m.deal_id,
            deal_type=m.deal_type,
            deal_name=m.deal_name,
            deal_no=m.deal_no,
            calculated_incentive=m.calculated_incentive,
            valid_from=m.valid_from,
            valid_to=m.valid_to,
            deal_maker_name=m.deal_maker_name,
            is_best=(m.deal_id == best_id and m.deal_type == all_matches[0].deal_type if all_matches else False),
        )
        for m in all_matches
    ]


# ── Match Diagnosis — deep step-by-step trace ─────────────────────────────

@router.get("/uploads/{ticket_id}/match-diagnosis", response_model=MatchDiagnosisResponse)
async def match_diagnosis(
    ticket_id:    int,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a full step-by-step diagnostic showing why each candidate deal did or did not match."""
    from app.services.deal_matching import _resolve_cabin_groups_with_detail

    res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id == ticket_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
        )
    )
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    raw_code = (ticket.airlines_code or "").strip()

    # ── Airline resolution ────────────────────────────────────────────────
    if not raw_code:
        return MatchDiagnosisResponse(
            ticket_id=ticket_id,
            raw_airline_code="",
            normalized_codes=[],
            airline_resolved=None,
            airline_resolution_detail="No airline code on ticket — cannot search for deals",
            raw_departure=ticket.departure_datetime,
            raw_ticket_date=ticket.ticket_date,
            travel_date=None,
            travel_date_detail="Not applicable — airline code missing",
            segment_type=ticket.segment_type,
            booking_class=ticket.booking_class,
            cabin_groups_resolved=[],
            cabin_resolution_detail="Not applicable — airline code missing",
            invoice_type=ticket.invoice_type,
            sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
            sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
            sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
            total_deals_checked=0,
            matched_count=0,
            deals=[],
        )

    code_variants = list({raw_code, raw_code.zfill(3)}) if raw_code.isdigit() else [raw_code]
    airline_res = await db.execute(
        select(Airline).where(
            or_(
                Airline.iata_code.in_(code_variants),
                Airline.icao_code.in_(code_variants),
            )
        )
    )
    airline = airline_res.scalar_one_or_none()
    if airline:
        airline_name = airline.name
        airline_detail = (
            f"raw_code='{raw_code}'; checked IATA and ICAO in {code_variants}; "
            f"found '{airline_name}' (IATA={airline.iata_code}, ICAO={airline.icao_code})"
        )
    else:
        airline_name = None
        airline_detail = (
            f"raw_code='{raw_code}'; checked IATA and ICAO in {code_variants}; "
            f"NOT FOUND in airline master — add this airline code to the master table"
        )

    # ── Travel date ───────────────────────────────────────────────────────
    travel_date = _parse_travel_date(ticket.departure_datetime, ticket.ticket_date)
    if travel_date:
        src = ticket.departure_datetime if ticket.departure_datetime else ticket.ticket_date
        date_detail = f"parsed from '{src}' → {travel_date}"
    else:
        date_detail = (
            f"departure_datetime='{ticket.departure_datetime}', ticket_date='{ticket.ticket_date}'; "
            f"could not parse either — fix the date format"
        )

    if not airline_name or not travel_date:
        _, cabin_detail = await _resolve_cabin_groups_with_detail(db, airline_name or "", ticket.booking_class)
        return MatchDiagnosisResponse(
            ticket_id=ticket_id,
            raw_airline_code=raw_code,
            normalized_codes=code_variants,
            airline_resolved=airline_name,
            airline_resolution_detail=airline_detail,
            raw_departure=ticket.departure_datetime,
            raw_ticket_date=ticket.ticket_date,
            travel_date=str(travel_date) if travel_date else None,
            travel_date_detail=date_detail,
            segment_type=ticket.segment_type,
            booking_class=ticket.booking_class,
            cabin_groups_resolved=[],
            cabin_resolution_detail=cabin_detail,
            invoice_type=ticket.invoice_type,
            sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
            sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
            sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
            total_deals_checked=0,
            matched_count=0,
            deals=[],
        )

    # ── Cabin group resolution ────────────────────────────────────────────
    cabin_groups, cabin_detail = await _resolve_cabin_groups_with_detail(
        db, airline_name, ticket.booking_class
    )

    # ── Run diagnosis ─────────────────────────────────────────────────────
    deals = await DealMatchingService.diagnose_match(
        db=db,
        airline_name=airline_name,
        travel_date=travel_date,
        tenant_id=current_user.tenant_id,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
    )

    return MatchDiagnosisResponse(
        ticket_id=ticket_id,
        raw_airline_code=raw_code,
        normalized_codes=code_variants,
        airline_resolved=airline_name,
        airline_resolution_detail=airline_detail,
        raw_departure=ticket.departure_datetime,
        raw_ticket_date=ticket.ticket_date,
        travel_date=str(travel_date),
        travel_date_detail=date_detail,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        cabin_groups_resolved=sorted(cabin_groups),
        cabin_resolution_detail=cabin_detail,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
        total_deals_checked=len(deals),
        matched_count=sum(1 for d in deals if d.overall_match),
        deals=deals,
    )
