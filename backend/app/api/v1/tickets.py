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
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline import Airline
from app.models.airline_deal import AirlineDeal
from app.models.b2b_deal import B2BDeal
from app.models.uploaded_ticket import UploadedTicket
from app.models.ticket_statement import TicketStatement
from app.models.ticket_calculation import TicketCalculation
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
    TicketStatementRead,
)
from pydantic import BaseModel
from app.services.deal_matching import DealMatchingService
from app.services.exclusion_evaluator import evaluate_exclusion_for_payout, evaluate_inclusion_for_payout
from app.services.ticket_extraction import (
    TicketExtractionService, TEMPLATE_HEADERS, AIRLINE_TEMPLATE_HEADERS,
)

router = APIRouter()

_CREDIT_TYPES = {"credit note", "refund"}


def _classify_ticket(ticket_number: str | None, invoice_type: str | None) -> tuple[str | None, str | None]:
    """Classify ticket by number prefix. Returns (adm_acm_ra, invoice_type_override).
    invoice_type_override is None when no change is needed (already Credit Note / Refund).
    Rules:
      starts with 400              → RA
      stripped leading-zeros → 6   → ADM
      stripped leading-zeros → 8   → ACM
    """
    if not ticket_number:
        return None, None
    tn_norm = ticket_number.lstrip("0") or "0"
    if ticket_number.startswith("400"):
        category = "RA"
    elif tn_norm.startswith("6"):
        category = "ADM"
    elif tn_norm.startswith("8"):
        category = "ACM"
    else:
        return None, None
    already_credit = (invoice_type or "").strip().lower() in _CREDIT_TYPES
    return category, (None if already_credit else "Credit Note")


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
    type: str = Query("b2b", description="Template type: 'b2b' or 'airline'"),
    current_user: User = Depends(get_current_user),
):
    """Return a blank XLSX file with the expected column headers as a download."""
    if type.lower() == "airline":
        headers = AIRLINE_TEMPLATE_HEADERS
        filename = "airline_ticket_template.xlsx"
    else:
        headers = TEMPLATE_HEADERS
        filename = "ticket_template.xlsx"
    df = pd.DataFrame(columns=headers)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
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
    statement_type: str = Form("B2B"),
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
        result = await TicketExtractionService.extract(
            chunk, file.filename,
            column_mapping=mapping_dict,
            statement_type=statement_type,
        )
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

    # ── Bidirectional airline resolution ─────────────────────────────────────
    # Collect all codes (with numeric zero-padding + uppercase variants) and names
    all_codes: set[str] = set()
    for r in payload.rows:
        if r.airlines_code:
            raw = r.airlines_code.strip()
            all_codes.add(raw)
            all_codes.add(raw.upper())    # handle "ai" → "AI"
            if raw.isdigit():
                all_codes.add(raw.zfill(3))

    all_names = {r.airline_name.strip().lower() for r in payload.rows if r.airline_name}

    # code (IATA or ICAO, uppercased) → Airline
    code_to_airline: dict[str, Airline] = {}
    if all_codes:
        upper_codes = [c.upper() for c in all_codes]
        res = await db.execute(
            select(Airline).where(
                or_(
                    func.upper(Airline.iata_code).in_(upper_codes),
                    func.upper(Airline.icao_code).in_(upper_codes),
                )
            )
        )
        for a in res.scalars():
            if a.iata_code:
                code_to_airline[a.iata_code] = a
                code_to_airline[a.iata_code.upper()] = a
            if a.icao_code:
                code_to_airline[a.icao_code] = a
                code_to_airline[a.icao_code.upper()] = a

    # name (lower) → Airline
    name_to_airline: dict[str, Airline] = {}
    if all_names:
        res = await db.execute(
            select(Airline).where(func.lower(Airline.name).in_(list(all_names)))
        )
        for a in res.scalars():
            name_to_airline[a.name.lower()] = a

    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()
    auto_name = f"{payload.statement_type} - {payload.agency} - {payload.valid_from}"

    statement = TicketStatement(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        statement_type=payload.statement_type,
        statement_name=auto_name,
        agency=payload.agency,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        file_name=payload.file_name,
        created_by_id=current_user.id,
        created_at=now,
    )
    db.add(statement)

    for row in payload.rows:
        # Try code lookup (numeric zero-padding + uppercase for alphabetic)
        raw_code = (row.airlines_code or "").strip()
        code_variants = [raw_code, raw_code.upper()]
        if raw_code.isdigit():
            code_variants.append(raw_code.zfill(3))
        airline_by_code = next((code_to_airline[c] for c in code_variants if c in code_to_airline), None)

        # Try name lookup
        airline_by_name = name_to_airline.get((row.airline_name or "").strip().lower())

        # Prefer code-based match; fall back to name-based match
        matched = airline_by_code or airline_by_name
        resolved_airline_name = row.airline_name or (matched.name if matched else None)
        resolved_airline_code = row.airlines_code or (matched.iata_code if matched else None)

        adm_acm_ra, invoice_override = _classify_ticket(row.ticket_number, row.invoice_type)

        ticket = UploadedTicket(
            batch_id=batch_id,
            file_name=payload.file_name,
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            created_at=now,
            statement_type=payload.statement_type,
            # ── shared / B2B ───────────────────────────────────────────────
            booking_ref=row.booking_ref,
            segment_type=row.segment_type,
            invoice_type=invoice_override if invoice_override is not None else row.invoice_type,
            invoice_no=row.invoice_no,
            ticket_date=row.ticket_date,
            last_name=row.last_name,
            first_name=row.first_name,
            sector=row.sector,
            booking_class=row.booking_class,
            departure_datetime=row.departure_datetime,
            gds_pnr=row.gds_pnr,
            airlines_code=resolved_airline_code,
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
            tour_code=row.tour_code,
            airline_name=resolved_airline_name,
            split_type=row.split_type,
            adm_acm_ra=adm_acm_ra,
            # ── airline-specific ────────────────────────────────────────────
            pax_name=row.pax_name,
            air_pnr=row.air_pnr,
            pcc=row.pcc,
            booking_signon=row.booking_signon,
            booking_pcc=row.booking_pcc,
            booking_agency_name=row.booking_agency_name,
            ticketing_signon=row.ticketing_signon,
            document_type=row.document_type,
            fare_basis=row.fare_basis,
            fare_const_type=row.fare_const_type,
            base_fare_currency=row.base_fare_currency,
            transaction_type=row.transaction_type,
            exchanged_for=row.exchanged_for,
            stock_control_no=row.stock_control_no,
            stp_no=row.stp_no,
            void_date=row.void_date,
            coupon_status=row.coupon_status,
            refund_type=row.refund_type,
            trip_id=row.trip_id,
            ai_code=row.ai_code,
            value_code=row.value_code,
            multiple_receivables=row.multiple_receivables,
            wo_tax=row.wo_tax,
            other_tax=row.other_tax,
            comm_percent=row.comm_percent,
            net_remit=row.net_remit,
            net_fare=row.net_fare,
            invoice_fare=row.invoice_fare,
            total_refund_amount=row.total_refund_amount,
            roe=row.roe,
            nuc=row.nuc,
            fop=row.fop,
            fop_details=row.fop_details,
            cc_auth=row.cc_auth,
            cc_do_expiry=row.cc_do_expiry,
            flight_no=row.flight_no,
            travel_dt=row.travel_dt,
            fare_ladder=row.fare_ladder,
            gstn=row.gstn,
            business_phone=row.business_phone,
            business_email=row.business_email,
            entity_address=row.entity_address,
            tax_breakup=row.tax_breakup,
            segments=row.segments,
        )
        db.add(ticket)

    await db.commit()
    return ConfirmTicketUploadResult(batch_id=batch_id, created_count=len(payload.rows))



# ── Statement listing ──────────────────────────────────────────────────────

@router.get("/statements", response_model=list[TicketStatementRead])
async def list_ticket_statements(
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all ticket statements for the current tenant with ticket counts."""
    count_subq = (
        select(UploadedTicket.batch_id, func.count(UploadedTicket.id).label("ticket_count"))
        .where(
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
        )
        .group_by(UploadedTicket.batch_id)
        .subquery()
    )
    q = (
        select(
            TicketStatement,
            func.coalesce(count_subq.c.ticket_count, 0).label("ticket_count"),
            User.full_name.label("created_by_name"),
        )
        .outerjoin(count_subq, TicketStatement.batch_id == count_subq.c.batch_id)
        .outerjoin(User, User.id == TicketStatement.created_by_id)
        .where(
            TicketStatement.tenant_id == current_user.tenant_id,
            TicketStatement.created_by_id == current_user.id,
        )
        .order_by(TicketStatement.created_at.desc())
    )
    result = await db.execute(q)
    rows = result.all()
    return [
        TicketStatementRead(
            batch_id=stmt.batch_id,
            statement_type=getattr(stmt, "statement_type", "B2B"),
            statement_name=stmt.statement_name,
            agency=stmt.agency,
            valid_from=stmt.valid_from,
            valid_to=stmt.valid_to,
            file_name=stmt.file_name,
            file_url=stmt.file_url,
            ticket_count=int(count),
            created_by_name=created_by_name,
            created_at=stmt.created_at,
        )
        for stmt, count, created_by_name in rows
    ]


@router.get("/statements/{batch_id}", response_model=TicketStatementRead)
async def get_ticket_statement(
    batch_id:     str,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a single ticket statement with its ticket count."""
    stmt_res = await db.execute(
        select(TicketStatement).where(
            TicketStatement.batch_id == batch_id,
            TicketStatement.tenant_id == current_user.tenant_id,
            TicketStatement.created_by_id == current_user.id,
        )
    )
    stmt = stmt_res.scalar_one_or_none()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    count_res = await db.execute(
        select(func.count(UploadedTicket.id)).where(
            UploadedTicket.batch_id == batch_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
        )
    )
    ticket_count = count_res.scalar() or 0

    return TicketStatementRead(
        batch_id=stmt.batch_id,
        statement_type=getattr(stmt, "statement_type", "B2B"),
        statement_name=stmt.statement_name,
        agency=stmt.agency,
        valid_from=stmt.valid_from,
        valid_to=stmt.valid_to,
        file_name=stmt.file_name,
        file_url=stmt.file_url,
        ticket_count=int(ticket_count),
        created_at=stmt.created_at,
    )


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
        UploadedTicket.tenant_id == current_user.tenant_id,
        UploadedTicket.created_by_id == current_user.id,
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
            UploadedTicket.created_by_id == current_user.id,
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


_CANCELLED_INVOICE_TYPES = {"credit note", "refund"}


async def _find_original_ticket(
    ticket_number: str,
    tenant_id: int,
    created_by_id: int,
    current_batch_id: str,
    db: AsyncSession,
) -> UploadedTicket | None:
    """Find the most recent prior ticket with the same ticket_number that had commission calculated."""
    res = await db.execute(
        select(UploadedTicket)
        .where(
            UploadedTicket.tenant_id == tenant_id,
            UploadedTicket.created_by_id == created_by_id,
            UploadedTicket.ticket_number == ticket_number,
            UploadedTicket.batch_id != current_batch_id,
            UploadedTicket.calculated_incentive.isnot(None),
            UploadedTicket.ticket_status.in_(["calculated", "included"]),
        )
        .order_by(UploadedTicket.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _run_single(
    ticket: UploadedTicket,
    db: AsyncSession,
    tenant_id: int,
    calculated_by_id: int | None = None,
) -> RunCalculationResult:
    """Core matching logic shared by single and batch endpoints."""
    # Set status upfront so every early-exit path persists "calculated" to the DB.
    # The excluded branch below overrides this to "excluded".
    ticket.ticket_status = "calculated"

    if ticket.invoice_type and ticket.invoice_type.strip().lower() in _CANCELLED_INVOICE_TYPES:
        ticket.comm_sell = 0

        original = None
        if ticket.ticket_number:
            original = await _find_original_ticket(ticket.ticket_number, tenant_id, ticket.created_by_id, ticket.batch_id, db)

        if original and original.calculated_incentive:
            reversal = -(float(original.calculated_incentive))
            ticket.ticket_status        = "reversed"
            ticket.matched_deal_id      = original.matched_deal_id
            ticket.matched_deal_type    = original.matched_deal_type
            ticket.matched_deal_name    = original.matched_deal_name
            ticket.calculated_incentive = reversal
            ticket.exclusion_reason     = (
                f"Reversal of ticket {ticket.ticket_number} — "
                f"original incentive {original.calculated_incentive} from statement {original.batch_id}"
            )
            return RunCalculationResult(
                ticket_id=ticket.id, matched=True, reversed=True, cancelled=False,
                matched_deal_id=original.matched_deal_id,
                matched_deal_type=original.matched_deal_type,
                matched_deal_name=original.matched_deal_name,
                calculated_incentive=reversal,
                message=(
                    f"Commission reversed: original incentive ₹{original.calculated_incentive} "
                    f"reversed from statement {original.batch_id}."
                ),
            )
        else:
            ticket.ticket_status        = "cancelled"
            ticket.matched_deal_id      = None
            ticket.matched_deal_type    = None
            ticket.matched_deal_name    = None
            ticket.calculated_incentive = 0
            ticket.exclusion_reason     = None
            return RunCalculationResult(
                ticket_id=ticket.id, matched=False, cancelled=True,
                matched_deal_id=None, matched_deal_type=None,
                matched_deal_name=None, calculated_incentive=0,
                message=(
                    f"Refund/credit note: no prior commission found for ticket "
                    f"{ticket.ticket_number or 'unknown'}."
                ),
            )

    if not ticket.airlines_code:
        ticket.matched_deal_id      = None
        ticket.matched_deal_type    = None
        ticket.matched_deal_name    = None
        ticket.calculated_incentive = None
        ticket.exclusion_reason     = None
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message="No airline code on ticket.",
        )

    raw_code = (ticket.airlines_code or "").strip()
    # Numeric codes: "98" → also try "098"; alphabetic: also try uppercase ("ai" → "AI")
    if raw_code.isdigit():
        code_variants = list({raw_code, raw_code.zfill(3)})
    else:
        code_variants = list({raw_code, raw_code.upper()})
    upper_variants = [c.upper() for c in code_variants]

    airline_res = await db.execute(
        select(Airline).where(
            or_(
                func.upper(Airline.iata_code).in_(upper_variants),
                func.upper(Airline.icao_code).in_(upper_variants),
            )
        )
    )
    airline = airline_res.scalar_one_or_none()
    if not airline:
        ticket.matched_deal_id      = None
        ticket.matched_deal_type    = None
        ticket.matched_deal_name    = None
        ticket.calculated_incentive = None
        ticket.exclusion_reason     = None
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message=f"Airline code '{ticket.airlines_code}' not in master.",
        )

    travel_date = _parse_travel_date(ticket.departure_datetime, ticket.ticket_date)
    if not travel_date:
        ticket.matched_deal_id      = None
        ticket.matched_deal_type    = None
        ticket.matched_deal_name    = None
        ticket.calculated_incentive = None
        ticket.exclusion_reason     = None
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message="Could not parse travel date.",
        )

    stmt_res = await db.execute(
        select(TicketStatement).where(TicketStatement.batch_id == ticket.batch_id)
    )
    statement = stmt_res.scalar_one_or_none()
    supplier_agency = (statement.agency or None) if statement else None

    match = await DealMatchingService.find_best_deal(
        db=db,
        airline_name=airline.name,
        travel_date=travel_date,
        tenant_id=tenant_id,
        created_by_id=ticket.created_by_id,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
        supplier_agency=supplier_agency,
        statement_type=ticket.statement_type,
    )

    if match:
        ticket.matched_deal_id      = match.deal_id
        ticket.matched_deal_type    = match.deal_type
        ticket.matched_deal_name    = match.deal_name
        ticket.incentive_breakdown  = match.incentive_breakdown or {}
        # Sum of all computed incentive types (PLB + Super PLB + Trans Fee + ...)
        ticket.calculated_incentive = (
            round(sum(match.incentive_breakdown.values()), 2)
            if match.incentive_breakdown
            else match.calculated_incentive
        )

        had_inclusion_rule = False

        if match.is_unified:
            # ── New schema: per-incentive DealRule/DealRuleCondition ──────
            from app.models.deal import (
                Deal as UnifiedDeal,
                DealIncentiveConfig,
                DealRule,
                build_rule_dict,
            )
            u_res = await db.execute(
                select(UnifiedDeal)
                .options(
                    selectinload(UnifiedDeal.incentives)
                    .selectinload(DealIncentiveConfig.rules)
                    .selectinload(DealRule.conditions)
                )
                .where(UnifiedDeal.id == match.deal_id)
            )
            unified_deal = u_res.scalar_one_or_none()
            if unified_deal:
                for config in unified_deal.incentives:
                    if config.incentive_type not in (match.incentive_breakdown or {}):
                        continue
                    for rule in config.rules:
                        rule_dict = build_rule_dict(rule.conditions)
                        if not rule_dict:
                            continue
                        if rule.rule_category == "payout_inclusion":
                            had_inclusion_rule = True
                            is_ok, reason = await evaluate_inclusion_for_payout(ticket, rule_dict, db)
                            if not is_ok:
                                ticket.calculated_incentive = 0
                                ticket.ticket_status        = "excluded"
                                ticket.exclusion_reason     = reason
                                ticket.incentive_breakdown  = {}
                                return RunCalculationResult(
                                    ticket_id=ticket.id, matched=True, excluded=True,
                                    matched_deal_id=match.deal_id,
                                    matched_deal_type=match.deal_type,
                                    matched_deal_name=match.deal_name,
                                    calculated_incentive=0,
                                    incentive_breakdown={},
                                    message=reason,
                                )
                        elif rule.rule_category == "payout_exclusion":
                            is_ex, reason = await evaluate_exclusion_for_payout(ticket, rule_dict, db)
                            if is_ex:
                                ticket.calculated_incentive = 0
                                ticket.ticket_status        = "excluded"
                                ticket.exclusion_reason     = reason
                                ticket.incentive_breakdown  = {}
                                return RunCalculationResult(
                                    ticket_id=ticket.id, matched=True, excluded=True,
                                    matched_deal_id=match.deal_id,
                                    matched_deal_type=match.deal_type,
                                    matched_deal_name=match.deal_name,
                                    calculated_incentive=0,
                                    incentive_breakdown={},
                                    message=reason,
                                )
        else:
            # ── Old schema: deal-level incl_excl_types / incl_excl_data ──
            if match.deal_type == "airline":
                deal_res = await db.execute(select(AirlineDeal).where(AirlineDeal.id == match.deal_id))
                matched_deal = deal_res.scalar_one_or_none()
            else:
                deal_res = await db.execute(select(B2BDeal).where(B2BDeal.id == match.deal_id))
                matched_deal = deal_res.scalar_one_or_none()

            incl_excl_types = matched_deal.incl_excl_types or [] if matched_deal else []
            incl_excl_data  = matched_deal.incl_excl_data  or {} if matched_deal else {}

            # Step 1: Inclusion For Payout
            if "Inclusion For Payout" in incl_excl_types:
                had_inclusion_rule = True
                incl_rule = incl_excl_data.get("Inclusion For Payout", {})
                is_included, incl_reason = await evaluate_inclusion_for_payout(ticket, incl_rule, db)
                if not is_included:
                    ticket.calculated_incentive = 0
                    ticket.ticket_status        = "excluded"
                    ticket.exclusion_reason     = incl_reason
                    ticket.incentive_breakdown  = {}
                    return RunCalculationResult(
                        ticket_id=ticket.id, matched=True, excluded=True,
                        matched_deal_id=match.deal_id,
                        matched_deal_type=match.deal_type,
                        matched_deal_name=match.deal_name,
                        calculated_incentive=0,
                        incentive_breakdown={},
                        message=incl_reason,
                    )

            # Step 2: Exclusion For Payout
            if "Exclusion For Payout" in incl_excl_types:
                excl_rule = incl_excl_data.get("Exclusion For Payout", {})
                if excl_rule:
                    excl_is_excluded, excl_reason = await evaluate_exclusion_for_payout(ticket, excl_rule, db)
                    if excl_is_excluded:
                        ticket.calculated_incentive = 0
                        ticket.ticket_status        = "excluded"
                        ticket.exclusion_reason     = excl_reason
                        ticket.incentive_breakdown  = {}
                        return RunCalculationResult(
                            ticket_id=ticket.id, matched=True, excluded=True,
                            matched_deal_id=match.deal_id,
                            matched_deal_type=match.deal_type,
                            matched_deal_name=match.deal_name,
                            calculated_incentive=0,
                            incentive_breakdown={},
                            message=excl_reason,
                        )

        # ── Success: all incl/excl checks passed ──────────────────────────
        ticket.ticket_status  = "included" if had_inclusion_rule else "calculated"
        ticket.exclusion_reason = None
        return RunCalculationResult(
            ticket_id=ticket.id, matched=True,
            included=had_inclusion_rule,
            matched_deal_id=match.deal_id,
            matched_deal_type=match.deal_type,
            matched_deal_name=match.deal_name,
            calculated_incentive=ticket.calculated_incentive,
            incentive_breakdown=ticket.incentive_breakdown or {},
            message=f"Matched {match.deal_type} deal ID {match.deal_id}.",
        )
    else:
        ticket.matched_deal_id      = None
        ticket.matched_deal_type    = None
        ticket.matched_deal_name    = None
        ticket.calculated_incentive = None
        ticket.incentive_breakdown  = None
        ticket.ticket_status        = "calculated"
        return RunCalculationResult(
            ticket_id=ticket.id, matched=False,
            matched_deal_id=None, matched_deal_type=None,
            matched_deal_name=None, calculated_incentive=None,
            message="No matching approved deal found.",
        )


async def _record_calc_history(
    ticket: UploadedTicket,
    result: RunCalculationResult,
    db: AsyncSession,
    tenant_id: int,
    calculated_by_id: int | None,
) -> None:
    """Insert one row into ticket_calculations after each run."""
    calc = TicketCalculation(
        ticket_id=ticket.id,
        batch_id=ticket.batch_id,
        tenant_id=tenant_id,
        deal_id=result.matched_deal_id,
        deal_type=result.matched_deal_type,
        deal_name=result.matched_deal_name,
        incentive_breakdown=result.incentive_breakdown,
        total_incentive=result.calculated_incentive,
        ticket_status=ticket.ticket_status,
        exclusion_reason=ticket.exclusion_reason,
        calculated_at=datetime.utcnow(),
        calculated_by_id=calculated_by_id,
    )
    db.add(calc)


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
            UploadedTicket.created_by_id == current_user.id,
        )
    )
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    result = await _run_single(ticket, db, current_user.tenant_id)
    await _record_calc_history(ticket, result, db, current_user.tenant_id, current_user.id)
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
    q = select(UploadedTicket).where(
        UploadedTicket.tenant_id == current_user.tenant_id,
        UploadedTicket.created_by_id == current_user.id,
    )
    if batch_id:
        q = q.where(UploadedTicket.batch_id == batch_id)

    res = await db.execute(q)
    tickets = res.scalars().all()

    processed = matched = unmatched = errors = excluded = cancelled = reversed_count = 0
    for ticket in tickets:
        try:
            result = await _run_single(ticket, db, current_user.tenant_id)
            await _record_calc_history(ticket, result, db, current_user.tenant_id, current_user.id)
            processed += 1
            if result.reversed:
                reversed_count += 1
            elif result.cancelled:
                cancelled += 1
            elif result.matched:
                if ticket.ticket_status == "excluded":
                    excluded += 1
                else:
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
        excluded=excluded,
        cancelled=cancelled,
        reversed=reversed_count,
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
            UploadedTicket.created_by_id == current_user.id,
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
            UploadedTicket.created_by_id == current_user.id,
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
            UploadedTicket.created_by_id == current_user.id,
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
        created_by_id=current_user.id,
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
            UploadedTicket.created_by_id == current_user.id,
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

    if raw_code.isdigit():
        code_variants = list({raw_code, raw_code.zfill(3)})
    else:
        code_variants = list({raw_code, raw_code.upper()})
    upper_variants = [c.upper() for c in code_variants]
    airline_res = await db.execute(
        select(Airline).where(
            or_(
                func.upper(Airline.iata_code).in_(upper_variants),
                func.upper(Airline.icao_code).in_(upper_variants),
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

    # ── Supplier agency from ticket statement ─────────────────────────────
    stmt_res = await db.execute(
        select(TicketStatement).where(TicketStatement.batch_id == ticket.batch_id)
    )
    stmt_row = stmt_res.scalar_one_or_none()
    supplier_agency = (stmt_row.agency or None) if stmt_row else None

    # ── Run diagnosis ─────────────────────────────────────────────────────
    deals = await DealMatchingService.diagnose_match(
        db=db,
        airline_name=airline_name,
        travel_date=travel_date,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
        ticket_sector=ticket.sector,
        ticket_date_raw=ticket.ticket_date,
        ticket_departure_raw=ticket.departure_datetime,
        ticket_airline_name=ticket.airline_name,
        supplier_agency=supplier_agency,
        tour_code=ticket.tour_code,
        statement_type=ticket.statement_type,
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


# ── GCS file upload & preview ─────────────────────────────────────────────────

@router.post("/statements/{batch_id}/file")
async def upload_statement_file(
    batch_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload the source XLS for a ticket statement to GCS. Called right after confirm."""
    import logging, mimetypes
    from app.services import gcs as gcs_service
    from app.config import settings
    log = logging.getLogger(__name__)

    log.info("[TICKET FILE UPLOAD] batch_id=%s | filename=%s | tenant=%s",
             batch_id, file.filename, current_user.tenant_id)

    stmt = await db.scalar(
        select(TicketStatement).where(
            TicketStatement.batch_id == batch_id,
            TicketStatement.tenant_id == current_user.tenant_id,
            TicketStatement.created_by_id == current_user.id,
        )
    )
    if not stmt:
        log.error("[TICKET FILE UPLOAD] Statement not found: %s", batch_id)
        raise HTTPException(status_code=404, detail="Statement not found")

    log.info("[TICKET FILE UPLOAD] Statement found. Reading file content...")
    bucket_name = settings.GCS_TICKETS_BUCKET_NAME
    log.info("[TICKET FILE UPLOAD] GCS_TICKETS_BUCKET_NAME=%r", bucket_name)

    content = await file.read()
    log.info("[TICKET FILE UPLOAD] File read complete | size=%d bytes", len(content))

    ct = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    blob_name = f"tickets/{current_user.tenant_id}/{batch_id}/{file.filename}"
    log.info("[TICKET FILE UPLOAD] Uploading to GCS | blob=%s | content_type=%s", blob_name, ct)

    try:
        await gcs_service.upload_bytes(content, blob_name, ct, bucket_name)
        log.info("[TICKET FILE UPLOAD] GCS upload SUCCESS | blob=%s", blob_name)
    except Exception as e:
        log.error("[TICKET FILE UPLOAD] GCS upload FAILED: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"GCS upload failed: {e}")

    stmt.file_url = blob_name
    await db.commit()
    log.info("[TICKET FILE UPLOAD] DB updated with file_url | batch_id=%s", batch_id)
    return {"file_url": blob_name}


@router.get("/statements/{batch_id}/file-url")
async def get_statement_file_url(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a short-lived signed URL for previewing the statement source file."""
    from app.services import gcs as gcs_service
    from app.config import settings

    stmt = await db.scalar(
        select(TicketStatement).where(
            TicketStatement.batch_id == batch_id,
            TicketStatement.tenant_id == current_user.tenant_id,
            TicketStatement.created_by_id == current_user.id,
        )
    )
    if not stmt or not stmt.file_url:
        raise HTTPException(status_code=404, detail="No file attached to this statement")
    bucket_name = settings.GCS_TICKETS_BUCKET_NAME
    # Tickets are always XLS — no inline flag needed
    url = await gcs_service.generate_signed_url(stmt.file_url, bucket_name, expiry_minutes=60, inline=False)
    return {"url": url, "file_type": "excel"}
