from __future__ import annotations

import io
import json
import logging
import re
import uuid
from datetime import datetime, date
from typing import Optional

from dateutil import parser as dateutil_parser
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, status, Query
from fastapi.responses import StreamingResponse
import pandas as pd
from dataclasses import dataclass

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline import Airline
from app.models.uploaded_ticket import UploadedTicket
from app.models.ticket_statement import TicketStatement
from app.models.income_summary import IncomeSummary
from app.models.ticket_calculation import TicketCalculation
from app.models.user import User
from app.models.agency import Agency
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.schemas.uploaded_ticket import (
    TicketExtractionPreview,
    TicketRow,
    ManualTicketPreviewPayload,
    AppendTicketsPayload,
    ConfirmTicketUploadPayload,
    ConfirmTicketUploadResult,
    UploadedTicketRead,
    UploadedTicketWithStatement,
    UploadedTicketsPage,
    UploadedTicketFacets,
    RunCalculationResult,
    BatchRunCalculationResult,
    UploadedTicketUpdate,
    MatchDiagnosisResponse,
    TicketStatementRead,
    IncomeSummaryCreate,
    IncomeSummaryRead,
)
from pydantic import BaseModel
from app.models.deal import DealDirection
from app.services.deal_matching import CustomerScope, DealMatchingService, SCOPE_SPECIFIC
from app.services.exclusion_evaluator import evaluate_exclusion_for_payout, evaluate_inclusion_for_payout
from app.services.ticket_extraction import (
    TicketExtractionService, TEMPLATE_HEADERS, AIRLINE_TEMPLATE_HEADERS,
    derive_ticket_rows,
)

router = APIRouter()

_CREDIT_TYPES = {"credit note", "refund"}

# Statements punched by hand have no source file, but ticket_statements.file_name
# is NOT NULL and confirm copies it onto every ticket — so this doubles as the
# provenance marker the UI reads to show a "Manually punched" pill.
MANUAL_ENTRY_FILE_NAME = "Manual Entry"


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


# ── Shared row construction (upload confirm + manual append) ───────────────
# One builder, so a ticket saved by either path lands with the same columns, the
# same airline resolution and the same ADM/ACM/RA classification.

async def _resolve_airlines(
    rows: list[TicketRow], db: AsyncSession,
) -> tuple[dict[str, Airline], dict[str, Airline]]:
    """Bidirectional airline lookup: code -> Airline, lowercased name -> Airline."""
    # ── Bidirectional airline resolution ─────────────────────────────────────
    # Collect all codes (with numeric zero-padding + uppercase variants) and names
    all_codes: set[str] = set()
    for r in rows:
        if r.airlines_code:
            raw = r.airlines_code.strip()
            all_codes.add(raw)
            all_codes.add(raw.upper())    # handle "ai" → "AI"
            if raw.isdigit():
                all_codes.add(raw.zfill(3))

    all_names = {r.airline_name.strip().lower() for r in rows if r.airline_name}

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

    return code_to_airline, name_to_airline


@dataclass
class CustomerParty:
    """A resolved, authorised counterparty for a statement or ticket."""
    customer_type: str | None = None          # agency | corporate | direct
    agency_id:     int | None = None
    corporate_id:  int | None = None
    customer_id:   int | None = None
    name:          str | None = None          # display name, written to `agency`
    label:         str | None = None          # "B2B" | "Corporate" | "Direct"


_PARTY_LABEL = {"agency": "B2B", "corporate": "Corporate", "direct": "Direct"}


async def _resolve_customer_party(
    db: AsyncSession,
    current_user: User,
    customer_type: str | None,
    agency_id: int | None,
    corporate_id: int | None,
    customer_id: int | None,
) -> CustomerParty:
    """Authorise the named party and return it.

    Ownership is checked here rather than left to the foreign keys, because an FK
    only proves the row exists — not that it is the caller's. The three masters
    are scoped differently: agencies by `user_id` alone, customers and corporates
    by tenant + creator.

    An untyped payload (an older client, or the legacy Internal Statement form)
    returns an empty party and the caller keeps its previous behaviour.
    """
    ct = (customer_type or "").strip().lower() or None
    if ct is None:
        return CustomerParty()
    if ct not in _PARTY_LABEL:
        raise HTTPException(status_code=422, detail="customer_type must be agency, corporate or direct.")

    if ct == "agency":
        if agency_id is None:
            raise HTTPException(status_code=422, detail="An agency statement needs an agency.")
        row = (await db.execute(
            select(Agency).where(Agency.id == agency_id, Agency.user_id == current_user.id)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=400, detail=f"Agency id {agency_id} not found in your agencies.")
        return CustomerParty("agency", agency_id=row.id, name=row.name, label="B2B")

    if ct == "corporate":
        if corporate_id is None:
            raise HTTPException(status_code=422, detail="A corporate statement needs a corporate.")
        row = (await db.execute(
            select(Corporate).where(
                Corporate.id == corporate_id,
                Corporate.tenant_id == current_user.tenant_id,
                Corporate.created_by_id == current_user.id,
            )
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=400, detail=f"Corporate id {corporate_id} not found in your corporates.")
        name = (row.company or "").strip() or f"{row.first_name} {row.last_name or ''}".strip()
        return CustomerParty("corporate", corporate_id=row.id, name=name, label="Corporate")

    # Direct. A walk-in need not exist in Customer Master, so the id is optional —
    # the type alone is enough to say "this is not an agency and not a corporate".
    if customer_id is None:
        return CustomerParty("direct", label="Direct")
    row = (await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == current_user.tenant_id,
            Customer.created_by_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=400, detail=f"Customer id {customer_id} not found in your customers.")
    name = f"{row.first_name} {row.last_name or ''}".strip() or (row.company or "")
    return CustomerParty("direct", customer_id=row.id, name=name, label="Direct")


async def _build_uploaded_tickets(
    rows:           list[TicketRow],
    db:             AsyncSession,
    *,
    batch_id:       str,
    file_name:      str,
    statement_type: str,
    tenant_id:      int,
    created_by_id:  int,
    now:            datetime,
    party:          "CustomerParty | None" = None,
) -> list[UploadedTicket]:
    """Build UploadedTicket rows from preview rows. Not added to the session.

    Left unset on purpose: ticket_status (server default 'draft'), raw_data,
    is_billed/billing_id, and the whole matched_deal_* / incentive block — those
    belong to run-calculation.
    """
    code_to_airline, name_to_airline = await _resolve_airlines(rows, db)
    built: list[UploadedTicket] = []

    for row in rows:
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

        built.append(UploadedTicket(
            batch_id=batch_id,
            file_name=file_name,
            tenant_id=tenant_id,
            created_by_id=created_by_id,
            created_at=now,
            statement_type=statement_type,
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
            # The statement's tag copied onto every ticket. The commission run
            # reads the TICKET, never the statement — one file can hold rows sold
            # to different customers, and Create Tickets files them one at a time.
            customer_type=(party.customer_type if party else None),
            customer_agency_id=(party.agency_id if party else None),
            corporate_id=(party.corporate_id if party else None),
            customer_id=(party.customer_id if party else None),
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
        ))

    return built


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

    now = datetime.utcnow()
    batch_id = str(uuid.uuid4())

    # WHO it was sold to. Authorised here, not trusted from the payload: an FK
    # alone would let one user tag a statement to another user's agency.
    party = await _resolve_customer_party(
        db, current_user,
        payload.customer_type, payload.customer_agency_id,
        payload.corporate_id, payload.customer_id,
    )

    db.add(TicketStatement(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        statement_type=payload.statement_type,
        # The derived name leads with the CUSTOMER TYPE when there is one, so a
        # corporate statement reads "Corporate - Infosys Ltd - …" rather than
        # "B2B - Infosys Ltd - …", which named the wrong thing entirely.
        statement_name=(payload.statement_name or "").strip()
                       or f"{party.label or payload.statement_type} - {party.name or payload.agency} - {payload.valid_from}",
        agency=party.name or payload.agency,
        # Only an agency-typed statement sets agency_id, so Agency Billing keeps
        # claiming exactly the statements it did before and no others.
        agency_id=party.agency_id if party.customer_type == "agency" else payload.agency_id,
        customer_type=party.customer_type,
        customer_agency_id=party.agency_id,
        corporate_id=party.corporate_id,
        customer_id=party.customer_id,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        file_name=payload.file_name,
        created_by_id=current_user.id,
        created_at=now,
    ))

    for ticket in await _build_uploaded_tickets(
        payload.rows, db,
        batch_id=batch_id,
        file_name=payload.file_name,
        statement_type=payload.statement_type,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        now=now,
        party=party,
    ):
        db.add(ticket)

    await db.commit()
    await _rematch_series_contracts(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id, batch_id=batch_id,
    )
    return ConfirmTicketUploadResult(batch_id=batch_id, created_count=len(payload.rows))


async def _rematch_series_contracts(db: AsyncSession, *, tenant_id: int, created_by_id: int, batch_id: str) -> None:
    """Refresh Series/SIT/MICE contract rollups after tickets land.

    Best-effort by design: a block-booking contract going stale is a reporting
    problem, losing a ticket save is a data problem. Never let the former cause
    the latter. Same posture as the auto-reconcile in workers/bsp_tasks.

    Imported locally to keep the service out of this module's import graph.
    """
    try:
        from app.services.series_contract_matching import SeriesContractMatchingService
        await SeriesContractMatchingService.run(db, tenant_id=tenant_id, created_by_id=created_by_id)
        await db.commit()
    except Exception as ex:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "Series contract matching failed after batch %s: %s", batch_id, ex
        )
        await db.rollback()


# ── Append tickets to an existing statement (manual entry) ─────────────────

@router.post(
    "/statements/{batch_id}/tickets",
    response_model=ConfirmTicketUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def append_tickets_to_statement(
    batch_id:     str,
    payload:      AppendTicketsPayload,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add manually punched rows to a statement that already exists.

    Lets a single hand-punched ticket join its peers instead of spawning a
    one-ticket statement. The rows go through the same builder as upload confirm,
    and inherit the statement's own type so a B2B statement can never end up
    holding an AIRLINE row.
    """
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No rows to save.")

    res = await db.execute(
        select(TicketStatement).where(
            TicketStatement.batch_id == batch_id,
            TicketStatement.tenant_id == current_user.tenant_id,
            TicketStatement.created_by_id == current_user.id,
        )
    )
    statement = res.scalar_one_or_none()
    if not statement:
        raise HTTPException(status_code=404, detail="Statement not found.")

    for ticket in await _build_uploaded_tickets(
        payload.rows, db,
        batch_id=batch_id,
        # Keep the statement's own file_name so provenance stays consistent; a
        # manual top-up of an uploaded statement still belongs to that file.
        file_name=statement.file_name,
        statement_type=statement.statement_type,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        now=datetime.utcnow(),
        # Inherit the statement's customer tag, exactly as the rows inherit its
        # type — a ticket appended to a corporate statement is a corporate sale.
        party=CustomerParty(
            customer_type=statement.customer_type,
            agency_id=statement.customer_agency_id,
            corporate_id=statement.corporate_id,
            customer_id=statement.customer_id,
        ),
    ):
        db.add(ticket)

    await db.commit()
    await _rematch_series_contracts(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id, batch_id=batch_id,
    )
    return ConfirmTicketUploadResult(batch_id=batch_id, created_count=len(payload.rows))


# ── Manual entry: derive + split punched rows ──────────────────────────────

# Fields the server owns. A manual form may echo them back (TicketRow accepts
# them), but split_type/statement_type are set by the derivation, adm_acm_ra by
# _classify_ticket at confirm, and the rest by run-calculation.
_SERVER_OWNED_KEYS = (
    "split_type", "statement_type", "adm_acm_ra",
    "matched_deal_id", "matched_deal_type", "matched_deal_name",
    "calculated_incentive", "iata_commission", "incentive_breakdown",
    "exclusion_reason",
)

# B2B accepts both the slash chain it has always used ("DEL/BOM/HYD") and the
# space-separated pairs the manual form composes from punched legs
# ("DEL/BOM BOM/HYD") — the latter is the only form that can express an open jaw.
_SECTOR_B2B_RE     = re.compile(r"^[A-Z]{3}(/[A-Z]{3})+( +[A-Z]{3}/[A-Z]{3})*$")
_SECTOR_AIRLINE_RE = re.compile(r"^[A-Z]{3}/[A-Z]{3}( +[A-Z]{3}/[A-Z]{3})*$")


def _manual_row_warnings(rows: list[dict], statement_type: str) -> list[str]:
    """Soft checks on punched rows.

    Deliberately warnings, never errors: the XLS path never rejects a row, and a
    user must be able to punch a partial ticket, buffer it and fix it later. Each
    one names a downstream consequence rather than just flagging a blank.
    """
    warnings: list[str] = []
    sector_re = _SECTOR_AIRLINE_RE if statement_type == "AIRLINE" else _SECTOR_B2B_RE
    seen_splits: set[str] = set()

    def warn(message: str) -> None:
        # A split ticket arrives here as N legs that share a ticket number and
        # therefore produce N identical messages. Emit each one once.
        if message not in warnings:
            warnings.append(message)

    for i, row in enumerate(rows, start=1):
        label = row.get("ticket_number") or f"row {i}"

        if not row.get("airlines_code"):
            warn(
                f"{label}: no airline code — this ticket can never be matched to a deal."
            )
        if not row.get("ticket_date") and not row.get("departure_datetime"):
            warn(
                f"{label}: no ticket date and no departure date — deal matching will "
                f"fail with 'could not parse travel date'."
            )
        if not row.get("booking_class"):
            warn(
                f"{label}: booking class is blank — deal matching treats a blank class "
                f"as Economy, so Business/First deals will never match."
            )
        sector = (row.get("sector") or "").strip().upper()
        if sector and not sector_re.match(sector):
            warn(
                f"{label}: sector '{sector}' is not in AAA/BBB form — segment type "
                f"detection and multi-sector splitting may be wrong."
            )
        if statement_type == "B2B" and not row.get("segment_type"):
            warn(
                f"{label}: segment type is blank — Domestic/International deal filters "
                f"will not match."
            )

    # One note per split group rather than per resulting leg.
    for row in rows:
        if row.get("split_type") != "split":
            continue
        key = str(row.get("ticket_number") or "")
        if key in seen_splits:
            continue
        seen_splits.add(key)
        n = sum(1 for r in rows
                if r.get("split_type") == "split"
                and str(r.get("ticket_number") or "") == key)
        warnings.append(
            f"{key or 'multi-sector ticket'}: {n} legs — saved as {n} rows, with sell "
            f"fare, sell tax, tax YQ, sale YR, sale K3 and every tax breakup "
            f"component divided by {n}."
        )

    return warnings


@router.post("/manual/preview", response_model=TicketExtractionPreview)
async def preview_manual_tickets(
    payload:      ManualTicketPreviewPayload,
    current_user: User = Depends(get_current_user),
):
    """Normalize and split manually punched rows exactly as the XLS path would.

    Read-only — no DB session, no writes. The returned rows are posted verbatim
    to POST /tickets/upload/confirm, so a hand-punched ticket lands identical to
    an uploaded one.
    """
    statement_type = (payload.statement_type or "B2B").strip().upper()
    if statement_type not in ("B2B", "AIRLINE"):
        raise HTTPException(
            status_code=422,
            detail="statement_type must be 'B2B' or 'AIRLINE'.",
        )
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No rows to preview.")

    raw: list[dict] = []
    for i, row in enumerate(payload.rows, start=1):
        # exclude_none is load-bearing, not tidiness: _split_multi_sector_rows
        # and derive_ticket_row use setdefault(), which leaves a present-but-None
        # key alone. Dumping with None values would land split_type=NULL on every
        # non-split manual ticket instead of 'normal'.
        d = row.model_dump(exclude_none=True)
        for key in _SERVER_OWNED_KEYS:
            d.pop(key, None)
        d["row_order"] = d.get("row_order") or i
        raw.append(d)

    derived = derive_ticket_rows(raw, is_airline=(statement_type == "AIRLINE"))

    return TicketExtractionPreview(
        file_name=MANUAL_ENTRY_FILE_NAME,
        total_rows=len(derived),
        rows=[TicketRow(**r) for r in derived],
        warnings=_manual_row_warnings(derived, statement_type),
        xls_columns=[],
        suggested_mapping={},
        is_template_match=True,
        sample_row={},
    )


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
            customer_type=stmt.customer_type,
            customer_agency_id=stmt.customer_agency_id,
            corporate_id=stmt.corporate_id,
            customer_id=stmt.customer_id,
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
        customer_type=stmt.customer_type,
        customer_agency_id=stmt.customer_agency_id,
        corporate_id=stmt.corporate_id,
        customer_id=stmt.customer_id,
        statement_name=stmt.statement_name,
        agency=stmt.agency,
        valid_from=stmt.valid_from,
        valid_to=stmt.valid_to,
        file_name=stmt.file_name,
        file_url=stmt.file_url,
        ticket_count=int(ticket_count),
        created_at=stmt.created_at,
    )


# ── Income summary (saved per-statement aggregates) ─────────────────────────

# Must stay byte-identical to INCENTIVE_TYPE_COLS[].key on the frontend batch page
# and to the keys produced into UploadedTicket.incentive_breakdown by deal matching.
INCENTIVE_TYPE_KEYS = [
    "PLB", "Super PLB", "Transaction Fee", "Deposit Incentive (DI)",
    "Marketing Fund", "Ancillary", "Frontend", "Backend", "Cashback",
    "Segment Incentive", "Push Action",
]


@router.post("/statements/{batch_id}/income-summary", response_model=IncomeSummaryRead)
async def save_income_summary(
    batch_id:     str,
    payload:      IncomeSummaryCreate,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate a statement's tickets authoritatively and UPSERT one IncomeSummary row."""
    # Statement (mirror get_ticket_statement filters)
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

    # Tickets (mirror list_uploaded_tickets filters)
    tk_res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.batch_id == batch_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
        )
    )
    tickets = tk_res.scalars().all()

    # Aggregate per incentive type + grand total (null → 0)
    totals = {k: 0.0 for k in INCENTIVE_TYPE_KEYS}
    total_income = 0.0
    total_iata = 0.0
    for t in tickets:
        bd = t.incentive_breakdown or {}
        for k in INCENTIVE_TYPE_KEYS:
            v = bd.get(k)
            if v is not None:
                totals[k] += float(v)
        if t.calculated_incentive is not None:
            total_income += float(t.calculated_incentive)
        if t.iata_commission is not None:
            total_iata += float(t.iata_commission)
    totals = {k: round(v, 2) for k, v in totals.items()}
    total_income = round(total_income, 2)
    total_iata = round(total_iata, 2)

    stmt_type = getattr(stmt, "statement_type", "B2B") or "B2B"
    name = (payload.name or "").strip() or stmt.statement_name or f"{stmt_type} · {stmt.agency}"

    # Upsert on (tenant_id, created_by_id, batch_id)
    existing_res = await db.execute(
        select(IncomeSummary).where(
            IncomeSummary.tenant_id == current_user.tenant_id,
            IncomeSummary.created_by_id == current_user.id,
            IncomeSummary.batch_id == batch_id,
        )
    )
    obj = existing_res.scalar_one_or_none()
    if obj is None:
        obj = IncomeSummary(
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            batch_id=batch_id,
        )
        db.add(obj)

    obj.name             = name
    obj.statement_name   = stmt.statement_name
    obj.statement_type   = stmt_type
    obj.agency           = stmt.agency
    obj.valid_from       = stmt.valid_from
    obj.valid_to         = stmt.valid_to
    obj.ticket_count     = len(tickets)
    obj.incentive_totals = totals
    obj.total_income     = total_income
    obj.iata_commission_total = total_iata

    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/income-summaries", response_model=list[IncomeSummaryRead])
async def list_income_summaries(
    agency:     Optional[str] = Query(None),
    valid_from: Optional[date] = Query(None),
    valid_to:   Optional[date] = Query(None),
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List saved income summaries, filtered by agency and a valid-date overlap range."""
    q = select(IncomeSummary).where(
        IncomeSummary.tenant_id == current_user.tenant_id,
        IncomeSummary.created_by_id == current_user.id,
    )
    if agency:
        q = q.where(IncomeSummary.agency == agency)
    if valid_from:                                   # overlap: drop rows ending before the range start
        q = q.where(IncomeSummary.valid_to >= valid_from)
    if valid_to:                                     # overlap: drop rows starting after the range end
        q = q.where(IncomeSummary.valid_from <= valid_to)
    q = q.order_by(IncomeSummary.created_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.delete("/income-summaries/{summary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_income_summary(
    summary_id:   int,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    res = await db.execute(
        select(IncomeSummary).where(
            IncomeSummary.id == summary_id,
            IncomeSummary.tenant_id == current_user.tenant_id,
            IncomeSummary.created_by_id == current_user.id,
        )
    )
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Income summary not found")
    await db.delete(obj)
    await db.commit()


async def _load_income_summary_with_tickets(summary_id: int, db: AsyncSession, current_user: User):
    """Fetch a saved income summary + the (live) tickets of its statement."""
    res = await db.execute(
        select(IncomeSummary).where(
            IncomeSummary.id == summary_id,
            IncomeSummary.tenant_id == current_user.tenant_id,
            IncomeSummary.created_by_id == current_user.id,
        )
    )
    summary = res.scalar_one_or_none()
    if not summary:
        raise HTTPException(status_code=404, detail="Income summary not found")
    tk = await db.execute(
        select(UploadedTicket)
        .where(
            UploadedTicket.batch_id == summary.batch_id,
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
        )
        .order_by(UploadedTicket.id)
    )
    return summary, tk.scalars().all()


def _income_filename(summary, ext: str) -> str:
    safe = "".join(c for c in (summary.name or "income-statement") if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_")
    return f"{safe or 'income-statement'}.{ext}"


@router.get("/income-summaries/{summary_id}/pdf")
async def export_income_summary_pdf(
    summary_id:   int,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.income_statement_export import build_income_statement_pdf
    summary, tickets = await _load_income_summary_with_tickets(summary_id, db, current_user)
    buf = build_income_statement_pdf(summary, tickets)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={_income_filename(summary, 'pdf')}"},
    )


@router.get("/income-summaries/{summary_id}/xlsx")
async def export_income_summary_xlsx(
    summary_id:   int,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.income_statement_export import build_income_statement_xlsx
    summary, tickets = await _load_income_summary_with_tickets(summary_id, db, current_user)
    buf = build_income_statement_xlsx(summary, tickets)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={_income_filename(summary, 'xlsx')}"},
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


# NOTE: must stay above /uploads/{ticket_id} — declared after it, "page" would be
# captured as a ticket_id and fail int validation.
@router.get("/uploads/page", response_model=UploadedTicketsPage)
async def list_uploaded_tickets_paged(
    offset:     int = 0,
    limit:      int = Query(50, le=500),
    search:     Optional[str] = Query(None, description="Ticket no, PNR, pax, sector, customer"),
    airline:    Optional[str] = Query(None),
    statement_type: Optional[str] = Query(None),
    ticket_status:  Optional[str] = Query(None),
    batch_id:   Optional[str] = Query(None),
    date_from:  Optional[str] = Query(None, description="ticket_date >= (YYYY-MM-DD)"),
    date_to:    Optional[str] = Query(None, description="ticket_date <= (YYYY-MM-DD)"),
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every ticket the user owns, across all statements, paginated server-side.

    Backs the Internal Statement "All tickets" view. Separate from GET /uploads
    because that one returns an unbounded list with no total, which cannot drive
    a pager once a tenant has tens of thousands of rows.
    """
    filters = [
        UploadedTicket.tenant_id == current_user.tenant_id,
        UploadedTicket.created_by_id == current_user.id,
    ]
    if batch_id:
        filters.append(UploadedTicket.batch_id == batch_id)
    if airline:
        filters.append(UploadedTicket.airlines_code == airline)
    if statement_type:
        filters.append(UploadedTicket.statement_type == statement_type)
    if ticket_status:
        filters.append(UploadedTicket.ticket_status == ticket_status)
    # ticket_date is stored as a YYYY-MM-DD string, so a lexical compare is also
    # a chronological one — no cast needed.
    if date_from:
        filters.append(UploadedTicket.ticket_date >= date_from)
    if date_to:
        filters.append(UploadedTicket.ticket_date <= date_to)
    if search:
        like = f"%{search.strip()}%"
        filters.append(or_(
            UploadedTicket.ticket_number.ilike(like),
            UploadedTicket.gds_pnr.ilike(like),
            UploadedTicket.air_pnr.ilike(like),
            UploadedTicket.pax_name.ilike(like),
            UploadedTicket.last_name.ilike(like),
            UploadedTicket.first_name.ilike(like),
            UploadedTicket.sector.ilike(like),
            UploadedTicket.customer_name.ilike(like),
            UploadedTicket.airline_name.ilike(like),
            UploadedTicket.invoice_no.ilike(like),
        ))

    total = (await db.execute(
        select(func.count()).select_from(UploadedTicket).where(*filters)
    )).scalar() or 0

    rows = (await db.execute(
        select(UploadedTicket).where(*filters)
        .order_by(UploadedTicket.created_at.desc(), UploadedTicket.id.desc())
        .offset(offset).limit(limit)
    )).scalars().all()

    # Statement context for the rows on this page only — the flat view shows which
    # statement each ticket came from, and one lookup beats a join per row.
    batch_ids = {r.batch_id for r in rows}
    statements: dict[str, TicketStatement] = {}
    if batch_ids:
        res = await db.execute(
            select(TicketStatement).where(TicketStatement.batch_id.in_(batch_ids))
        )
        statements = {s.batch_id: s for s in res.scalars()}

    return UploadedTicketsPage(
        total=total,
        offset=offset,
        limit=limit,
        rows=[
            UploadedTicketWithStatement(
                **UploadedTicketRead.model_validate(r).model_dump(),
                statement_agency=(statements.get(r.batch_id).agency if statements.get(r.batch_id) else None),
                statement_name=(statements.get(r.batch_id).statement_name if statements.get(r.batch_id) else None),
            )
            for r in rows
        ],
    )


@router.get("/uploads/facets", response_model=UploadedTicketFacets)
async def uploaded_ticket_facets(
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct values for the All-tickets filter dropdowns."""
    scope = [
        UploadedTicket.tenant_id == current_user.tenant_id,
        UploadedTicket.created_by_id == current_user.id,
    ]

    async def distinct(col):
        res = await db.execute(
            select(col).where(*scope, col.isnot(None)).distinct().order_by(col)
        )
        return [v for v in res.scalars() if v]

    return UploadedTicketFacets(
        airlines=await distinct(UploadedTicket.airlines_code),
        statuses=await distinct(UploadedTicket.ticket_status),
        statement_types=await distinct(UploadedTicket.statement_type),
    )


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
            s = str(raw).strip()
            # ISO YYYY-MM-DD — parse directly to avoid dayfirst misreading
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return date.fromisoformat(s[:10])
            return dateutil_parser.parse(s, dayfirst=True).date()
        except Exception:
            continue
    return None


def _parse_issue_date(ticket_date: str | None, departure_datetime: str | None) -> date | None:
    """Ticket ISSUE/sale date (issue-preferred, departure fallback) for contract
    validity. Reuses the same parser with swapped preference order."""
    return _parse_travel_date(ticket_date, departure_datetime)


# ── Which deals this statement book runs against ───────────────────────────
# The /tickets statement book is the SELLING side: these rows are tickets sold to
# a sub-agency, a corporate or a walk-in, so the commission on them is what we PAY
# out under a floated deal — never the income we receive from an airline. The
# income side has its own runner in services/bsp_commission.py and keeps INBOUND.
_TICKET_RUN_DIRECTION = DealDirection.OUTBOUND


async def _resolve_ticket_scope(
    db: AsyncSession,
    ticket: UploadedTicket,
    statement: TicketStatement | None,
) -> CustomerScope:
    """WHO this ticket was sold to, for outgoing-deal matching.

    The TICKET's own tag wins: one statement can hold rows sold to different
    customers, and Create Tickets files them one at a time. Rows written before
    that tag existed carry none, so the statement's copy is the first fallback and
    its `agency_id` the second.

    The bare `agency` NAME is the last resort, and only when it resolves to
    exactly ONE agency. A vendor onboarded once per branch matches two rows, and
    guessing between them would pay one branch's rate on the other's tickets —
    the same reason Agency Billing refuses an ambiguous name. An unresolved name
    is not an error: the ticket simply reaches common deals only.
    """
    ct = (ticket.customer_type or "").strip().lower() or None
    if ct == "agency" and ticket.customer_agency_id:
        return CustomerScope("agency", agency_id=ticket.customer_agency_id,
                             name=(statement.agency if statement else None) or ticket.customer_name)
    if ct == "corporate" and ticket.corporate_id:
        return CustomerScope("corporate", corporate_id=ticket.corporate_id,
                             name=(statement.agency if statement else None) or ticket.customer_name)
    if ct == "direct":
        return CustomerScope("direct", name=ticket.customer_name)

    if statement is None:
        return CustomerScope()

    st = (statement.customer_type or "").strip().lower() or None
    if st == "agency" and statement.customer_agency_id:
        return CustomerScope("agency", agency_id=statement.customer_agency_id, name=statement.agency)
    if st == "corporate" and statement.corporate_id:
        return CustomerScope("corporate", corporate_id=statement.corporate_id, name=statement.agency)
    if st == "direct":
        return CustomerScope("direct", name=statement.agency)

    if statement.agency_id:
        return CustomerScope("agency", agency_id=statement.agency_id, name=statement.agency)

    if statement.agency:
        rows = (await db.execute(
            select(Agency.id).where(
                func.lower(Agency.name) == statement.agency.strip().lower(),
                Agency.user_id == ticket.created_by_id,
            )
        )).scalars().all()
        if len(rows) == 1:
            return CustomerScope("agency", agency_id=rows[0], name=statement.agency)

    return CustomerScope(name=statement.agency)


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
    # IATA commission defaults to 0; set to the computed amount when a deal matches.
    ticket.iata_commission = 0

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
    customer_scope = await _resolve_ticket_scope(db, ticket, statement)

    issue_date = _parse_issue_date(ticket.ticket_date, ticket.departure_datetime)

    match = await DealMatchingService.find_best_deal(
        db=db,
        airline_name=airline.name,
        travel_date=travel_date,
        tenant_id=tenant_id,
        created_by_id=ticket.created_by_id,
        issue_date=issue_date,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
        seat_selection=float(ticket.seat_selection) if ticket.seat_selection is not None else None,
        excess_baggage=float(ticket.excess_baggage) if ticket.excess_baggage is not None else None,
        meals=float(ticket.meals) if ticket.meals is not None else None,
        supplier_agency=supplier_agency,
        statement_type=ticket.statement_type,
        direction=_TICKET_RUN_DIRECTION,
        customer_scope=customer_scope,
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

        # IATA commission: the matched deal's IATA % applied to the ticket's sell fare
        # (base fare). Shown in its own column — NOT part of the incentive total. 0 if none.
        iata_pct = 0.0
        if match.iata_commission:
            try:
                iata_pct = float(str(match.iata_commission).strip().rstrip("%").strip())
            except (TypeError, ValueError):
                iata_pct = 0.0
        sell = float(ticket.sell_fare) if ticket.sell_fare is not None else 0.0
        ticket.iata_commission = round(iata_pct / 100.0 * sell, 2)

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
            iata_commission=float(ticket.iata_commission or 0),
            incentive_breakdown=ticket.incentive_breakdown or {},
            # Name the rung, so a user seeing an unexpected rate knows immediately
            # whether it came from this customer's own deal or the common one.
            message=(
                f"Matched outgoing deal ID {match.deal_id} "
                f"({'customer-specific' if match.scope_tier == SCOPE_SPECIFIC else 'common'}"
                f"{f' — {match.scope_label}' if match.scope_label else ''})."
            ),
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
            message=(
                "No matching approved outgoing deal found for "
                f"{customer_scope.name or customer_scope.kind or 'this customer'}."
            ),
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
    issue_date = _parse_issue_date(ticket.ticket_date, ticket.departure_datetime)

    # Same pool and same scope ladder the runner walks — a popup listing deals the
    # run would never reach is worse than no popup at all.
    stmt_res = await db.execute(
        select(TicketStatement).where(TicketStatement.batch_id == ticket.batch_id)
    )
    statement = stmt_res.scalar_one_or_none()
    customer_scope = await _resolve_ticket_scope(db, ticket, statement)

    all_matches = await DealMatchingService.find_all_deals(
        db=db,
        airline_name=airline.name,
        travel_date=travel_date,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        issue_date=issue_date,
        segment_type=ticket.segment_type,
        booking_class=ticket.booking_class,
        invoice_type=ticket.invoice_type,
        sell_fare=float(ticket.sell_fare) if ticket.sell_fare is not None else None,
        sell_tax_yq=float(ticket.sell_tax_yq) if ticket.sell_tax_yq is not None else None,
        sale_yr=float(ticket.sale_yr) if ticket.sale_yr is not None else None,
        seat_selection=float(ticket.seat_selection) if ticket.seat_selection is not None else None,
        excess_baggage=float(ticket.excess_baggage) if ticket.excess_baggage is not None else None,
        meals=float(ticket.meals) if ticket.meals is not None else None,
        statement_type=ticket.statement_type,
        direction=_TICKET_RUN_DIRECTION,
        customer_scope=customer_scope,
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
        if src and src.strip()[:10] == str(travel_date):
            date_detail = f"date from departure field: {travel_date}"
        else:
            date_detail = f"parsed from '{src}' → {travel_date}"
    else:
        date_detail = (
            f"departure='{ticket.departure_datetime}', ticket_date='{ticket.ticket_date}'; "
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
    customer_scope = await _resolve_ticket_scope(db, ticket, stmt_row)

    # ── Run diagnosis ─────────────────────────────────────────────────────
    issue_date = _parse_issue_date(ticket.ticket_date, ticket.departure_datetime)
    deals = await DealMatchingService.diagnose_match(
        db=db,
        airline_name=airline_name,
        travel_date=travel_date,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        issue_date=issue_date,
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
        direction=_TICKET_RUN_DIRECTION,
        customer_scope=customer_scope,
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
