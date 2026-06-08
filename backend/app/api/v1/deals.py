from __future__ import annotations

from datetime import date
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query, Form
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.airline import Airline
from app.models.uploaded_deal import (
    UploadedDeal,
    UploadedDealStatus,
    UploadedDealSourceType,
    DealIncentive,
    DealInclusionExclusion,
)
from app.models.airline_deal import AirlineDeal, ManualDealStatus, DealLifecycleStatus
from app.models.b2b_deal import B2BDeal
from app.models.deal_batch import DealBatch
from app.schemas.airline_deal import AirlineDealCreate, AirlineDealResponse
from app.schemas.b2b_deal import B2BDealCreate, B2BDealResponse
from app.models.approval_workflow import (
    ApprovalWorkflow,
    ApprovalWorkflowStep,
    DealApproval,
    DealApprovalStep,
    ApprovalActionStatus,
    WorkflowModule,
)
from app.schemas.uploaded_deal import (
    ExtractionPreview, ConfirmUploadPayload,
    UploadedDealRead, UploadedDealSummary, ExtractedRow,
    DealRepositoryItem, DealBatchRead,
    AIDeal, AIExtractResponse, AIConfirmPayload,
    DealUpdatePayload,
)
from app.schemas.approval_workflow import (
    ApprovalDecisionPayload,
    ApprovalInboxItem,
    DealApprovalRead,
    DealApprovalStepRead,
    BulkApprovePayload,
    BulkApproveResult,
    DealHistoryResponse,
    DealHistoryStepRead,
)
from app.services.deal_extraction import DealExtractionService
from app.services.ai_deal_extraction import AIDealExtractionService

router = APIRouter()


class UploadConfirmResult(BaseModel):
    created_count: int
    created_ids: list[int]
    batch_id: Optional[str] = None


class ClosingDealSummary(BaseModel):
    deal_id:         int
    deal_type:       str
    deal_no:         str
    airline_name:    Optional[str]
    airline_type:    Optional[str]
    source_agent:    Optional[str]
    deal_maker_name: Optional[str]
    valid_from:      Optional[date]
    valid_to:        Optional[date]
    contract_year:   Optional[str]
    business_type:   Optional[str]
    trigger_type:    Optional[str]
    payout_type:     Optional[str]
    entity_lcc:      Optional[str]
    incentive_types: list[str] = []
    incentive_data:  dict = {}
    incl_excl_types: list[str] = []
    incl_excl_data:  dict = {}
    remark:          Optional[str]

class ClosingPreviewResponse(BaseModel):
    is_final_step: bool
    closing_deals: list[ClosingDealSummary]

class BulkClosingPreviewPayload(BaseModel):
    deal_ids: list[int]


def _attach_deal_relations(
    deal_id: int,
    payload: ConfirmUploadPayload,
    db: AsyncSession,
    row: "ExtractedRow | None" = None,
) -> None:
    for inc_type in payload.incentive_types or []:
        db.add(DealIncentive(
            deal_id=deal_id,
            incentive_type=inc_type,
            data=(payload.incentive_data or {}).get(inc_type, {}),
        ))
    # Use per-row incl/excl if provided, otherwise fall back to deal-level
    ie_types = (row.incl_excl_types if row and row.incl_excl_types else None) or payload.incl_excl_types or []
    ie_data  = (row.incl_excl_data  if row and row.incl_excl_data  else None) or payload.incl_excl_data  or {}
    ie_vv    = (row.vice_versa      if row and row.vice_versa       else None) or payload.vice_versa      or {}
    for rule_type in ie_types:
        db.add(DealInclusionExclusion(
            deal_id=deal_id,
            rule_type=rule_type,
            data=ie_data.get(rule_type, {}),
            vice_versa=bool(ie_vv.get(rule_type, False)),
        ))


async def _seed_approval_for_deal(
    deal_id: int,
    deal_obj,
    current_user: User,
    db: AsyncSession,
    deal_type: str = "upload",
) -> None:
    """Route a newly-flushed deal through the tenant's approval workflow.

    Checks the workflow's deal_category:
    - 'proprietary': auto-approve the deal (no DealApproval record), set status=APPROVED,
                     lifecycle=ACTIVE, close conflicting active deals.
    - 'enterprise'  (default): create DealApproval + DealApprovalStep records and leave
                     deal in PENDING_APPROVAL / DRAFT.

    deal_type: 'upload' | 'airline' | 'b2b'
    """
    workflow_result = await db.execute(
        select(ApprovalWorkflow)
        .options(selectinload(ApprovalWorkflow.steps).selectinload(ApprovalWorkflowStep.approvers))
        .where(
            ApprovalWorkflow.tenant_id == current_user.tenant_id,
            ApprovalWorkflow.module == WorkflowModule.DEALS,
            ApprovalWorkflow.is_active == True,  # noqa: E712
        )
    )
    workflow = workflow_result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(
            status_code=400,
            detail="Deals approval workflow is not configured. Ask Super Admin to configure it first.",
        )

    if workflow.deal_category == "proprietary":
        # Platform admin has set deals to auto-approve — no human approval step needed
        deal_obj.status = ManualDealStatus.APPROVED
        deal_obj.deal_lifecycle_status = DealLifecycleStatus.ACTIVE
        await _close_matching_active_deals(deal_obj, deal_type, db)
        return

    # Enterprise path — normal step-based approval
    if not workflow.steps:
        raise HTTPException(
            status_code=400,
            detail="Deals approval workflow has no steps configured. Ask Super Admin to add approval steps.",
        )

    deal_approval = DealApproval(
        deal_type=deal_type,
        deal_id=deal_id,
        workflow_id=workflow.id,
        current_step_order=min(s.step_order for s in workflow.steps),
        status=ApprovalActionStatus.PENDING,
        submitted_by_id=current_user.id,
    )
    db.add(deal_approval)
    await db.flush()

    for s in sorted(workflow.steps, key=lambda x: x.step_order):
        for approver in s.approvers or []:
            db.add(
                DealApprovalStep(
                    deal_approval_id=deal_approval.id,
                    step_order=s.step_order,
                    role=s.role,
                    assigned_user_id=approver.user_id,
                    status=ApprovalActionStatus.PENDING,
                )
            )


# ══════════════════════════════════════════════════════════════════════════════
# UPLOAD FLOW  — Step 1: extract,  Step 2: confirm
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/upload/extract", response_model=ExtractionPreview)
async def extract_deal_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Step 1 — Upload a file (PDF / Excel / Word / image).
    Parses it and returns structured rows for the user to review.
    Nothing is saved to the database yet.
    """
    max_mb = 50
    # read up to max size
    chunk = await file.read(max_mb * 1024 * 1024 + 1)
    if len(chunk) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB limit")
    # rewind so the extraction service can read it
    import io
    file.file = io.BytesIO(chunk)  # type: ignore[assignment]
    await file.seek(0)

    result = await DealExtractionService.extract(file)

    rows = [ExtractedRow(**r) for r in result.get("rows", [])]
    return ExtractionPreview(
        source_type=result.get("source_type", "unknown"),
        file_name=result.get("file_name", file.filename or ""),
        confidence=result.get("confidence", 0.0),
        warning=result.get("warning"),
        rows=rows,
        doc_columns=result.get("doc_columns", []),
        raw_rows=result.get("raw_rows", []),
    )


def _fallback_valid_to(valid_from: date, contract_year: str) -> date:
    """Derive Contract Valid To from valid_from date and contract_year (FY/CY)."""
    if contract_year.upper() == "FY":
        # Financial Year: April 1 – March 31
        # Jan/Feb/Mar → FY ends March 31 of same year
        # Apr–Dec     → FY ends March 31 of next year
        end_year = valid_from.year if valid_from.month <= 3 else valid_from.year + 1
        return date(end_year, 3, 31)
    else:  # CY — Calendar Year
        return date(valid_from.year, 12, 31)


@router.post("/upload/ai-extract", response_model=AIExtractResponse)
async def ai_extract_deals(
    file: UploadFile = File(...),
    valid_from: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    AI-powered extraction — upload a PDF and get back fully structured deal objects
    split by class (Economy / Premium / Business). Skips column-mapping step.
    """
    max_mb = 50
    chunk = await file.read(max_mb * 1024 * 1024 + 1)
    if len(chunk) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB limit")
    import io as _io
    file.file = _io.BytesIO(chunk)  # type: ignore[assignment]
    await file.seek(0)

    result = await AIDealExtractionService.extract(file, max_deals=15)
    deals = [AIDeal(**d) for d in result.get("deals", [])]

    # Apply Contract Valid To fallback when AI didn't extract the date
    if valid_from and deals:
        vf_date: date | None = None
        try:
            vf_date = date.fromisoformat(valid_from)
        except ValueError:
            pass

        if vf_date:
            airline_names_lower = [d.airline_name.lower() for d in deals if d.airline_name]
            airline_rows = await db.execute(
                select(Airline.name, Airline.contract_year).where(
                    func.lower(Airline.name).in_(airline_names_lower)
                )
            )
            cy_map: dict[str, str] = {
                row.name.lower(): row.contract_year
                for row in airline_rows.all()
                if row.contract_year
            }

            for deal in deals:
                cy = cy_map.get((deal.airline_name or "").lower())
                if not cy:
                    continue
                fallback = _fallback_valid_to(vf_date, cy).isoformat()

                if not deal.contract_valid_to:
                    deal.contract_valid_to = fallback

                plb = (deal.incentive_data or {}).get("PLB")
                if isinstance(plb, dict) and not plb.get("validTo"):
                    plb["validTo"] = fallback

    return AIExtractResponse(
        deals=deals,
        file_name=result.get("file_name", file.filename or ""),
        confidence=result.get("confidence", 0.0),
        warning=result.get("warning"),
    )


@router.post("/upload/ai-confirm", response_model=UploadConfirmResult, status_code=status.HTTP_201_CREATED)
async def ai_confirm_deals(
    payload: AIConfirmPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk-create AirlineDeal records from AI-extracted deals.
    One record per deal object (i.e. one per airline × class).
    """
    batch_id = payload.batch_id or str(uuid.uuid4())

    batch = DealBatch(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        deal_type="airline",
        deal_tag=payload.deal_tag or "standard",
        supplier_name=payload.supplier_name or None,
        file_name=payload.file_name or None,
        file_type=payload.file_type or "pdf",
        incentive_types=[d.incentive_types[0] for d in payload.deals if d.incentive_types][:1] or [],
        created_by_id=current_user.id,
    )
    db.add(batch)
    await db.flush()

    created_ids: list[int] = []
    for deal in payload.deals:
        vf = date.fromisoformat(deal.contract_valid_from) if deal.contract_valid_from else None
        vt = date.fromisoformat(deal.contract_valid_to) if deal.contract_valid_to else None

        db_deal = AirlineDeal(
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            status=ManualDealStatus.PENDING_APPROVAL,
            deal_lifecycle_status=DealLifecycleStatus.DRAFT,
            deal_tag=payload.deal_tag or "standard",
            source_agent="ai_extraction",
            airline_type=deal.airline_type or None,
            airline_name=deal.airline_name or None,
            valid_from=vf,
            valid_to=vt,
            incentive_types=deal.incentive_types or [],
            incentive_data=deal.incentive_data or {},
            remark=deal.remark or None,
            batch_id=batch_id,
        )
        db.add(db_deal)
        await db.flush()
        await _seed_approval_for_deal(db_deal.id, current_user, db, deal_type="airline")
        created_ids.append(db_deal.id)

    await db.commit()
    return UploadConfirmResult(created_count=len(created_ids), created_ids=created_ids, batch_id=batch_id)


def _get_deal_segment(incentive_data: dict | None) -> str | None:
    """Extract flightType from any incentive entry in incentive_data JSON."""
    if not incentive_data:
        return None
    for val in incentive_data.values():
        if isinstance(val, dict):
            ft = val.get("flightType") or val.get("flight_type") or val.get("segment")
            if ft:
                return ft.strip().lower()
    return None


async def _find_prev_incl_excl(
    airline_name: str | None,
    supplier_name: str | None,
    segment_type: str | None,
    use_b2b: bool,
    tenant_id: int,
    db: AsyncSession,
) -> tuple[list, dict, dict] | None:
    """Return (incl_excl_types, incl_excl_data, vice_versa) from the most recent
    previous deal that matches airline + supplier + segment and has incl/excl set."""
    if not airline_name:
        return None
    airline_lower = airline_name.strip().lower()
    seg_lower = segment_type.strip().lower() if segment_type else None

    if use_b2b:
        q = (
            select(B2BDeal)
            .where(
                B2BDeal.tenant_id == tenant_id,
                func.lower(B2BDeal.airline_name) == airline_lower,
                B2BDeal.incl_excl_types.isnot(None),
            )
        )
        if supplier_name:
            q = q.where(func.lower(B2BDeal.supplier_name) == supplier_name.strip().lower())
        q = q.order_by(B2BDeal.created_at.desc()).limit(10)
        deals = (await db.execute(q)).scalars().all()
    else:
        q = (
            select(AirlineDeal)
            .where(
                AirlineDeal.tenant_id == tenant_id,
                func.lower(AirlineDeal.airline_name) == airline_lower,
                AirlineDeal.incl_excl_types.isnot(None),
            )
        )
        q = q.order_by(AirlineDeal.created_at.desc()).limit(10)
        deals = (await db.execute(q)).scalars().all()

    for deal in deals:
        if not deal.incl_excl_types:
            continue
        # Segment check: conflict only when both sides have a non-"both" segment that differs
        if seg_lower:
            deal_seg = _get_deal_segment(deal.incentive_data)
            if deal_seg and deal_seg != "both" and seg_lower != "both" and deal_seg != seg_lower:
                continue
        return (deal.incl_excl_types, deal.incl_excl_data or {}, deal.vice_versa or {})

    return None


@router.post("/upload/confirm", response_model=UploadConfirmResult, status_code=status.HTTP_201_CREATED)
async def confirm_upload(
    payload: ConfirmUploadPayload,
    file_name: str = Query(..., description="Original file name"),
    file_type: str = Query(..., description="File type: pdf/excel/word/image"),
    supplier_name: Optional[str] = Query(None, description="Supplier / agency name for batch record"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Step 2 — User has reviewed / edited the extracted rows and confirms.
    Routes each row to airline_deals or b2b_deals depending on deal type.
    """
    vf_deal = date.fromisoformat(payload.valid_from) if payload.valid_from else None
    vt_deal = date.fromisoformat(payload.valid_to)   if payload.valid_to   else None
    source_agent = payload.source_agent or file_name.rsplit(".", 1)[0]

    rows = payload.rows or []
    if not rows:
        rows = [ExtractedRow()]

    use_b2b = bool(payload.business_type)

    batch_id = str(uuid.uuid4())
    batch = DealBatch(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        deal_type="b2b" if use_b2b else "airline",
        deal_tag=payload.deal_tag or "standard",
        supplier_name=supplier_name or payload.source_agent or None,
        file_name=file_name or None,
        file_type=file_type or None,
        incentive_types=payload.incentive_types or [],
        valid_from=vf_deal,
        valid_to=vt_deal,
        created_by_id=current_user.id,
    )
    db.add(batch)
    await db.flush()

    created_ids: list[int] = []

    for r in rows:
        row_vf = date.fromisoformat(r.valid_from) if r.valid_from else None
        row_vt = date.fromisoformat(r.valid_to)   if r.valid_to   else None
        effective_vf = row_vf or vf_deal
        effective_vt = row_vt or vt_deal

        ie_types   = (r.incl_excl_types if r.incl_excl_types else None) or payload.incl_excl_types or []
        ie_data    = (r.incl_excl_data  if r.incl_excl_data  else None) or payload.incl_excl_data  or {}
        ie_vv      = (r.vice_versa      if r.vice_versa       else None) or payload.vice_versa      or {}
        # Use per-row incentive_data if provided; fall back to payload-level only when absent
        row_inc_data = r.incentive_data if r.incentive_data else (payload.incentive_data or {})

        # If toggle is on and this row has no incl/excl, copy from previous matching deal
        if payload.copy_prev_incl_excl and not ie_types:
            row_segment = _get_deal_segment(row_inc_data)
            prev = await _find_prev_incl_excl(
                airline_name=(r.airline_name or payload.airline_name),
                supplier_name=supplier_name,
                segment_type=row_segment,
                use_b2b=use_b2b,
                tenant_id=current_user.tenant_id,
                db=db,
            )
            if prev:
                ie_types, ie_data, ie_vv = prev

        if use_b2b:
            deal: B2BDeal | AirlineDeal = B2BDeal(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
                status=ManualDealStatus.PENDING_APPROVAL,
                deal_lifecycle_status=DealLifecycleStatus.DRAFT,
                deal_tag=payload.deal_tag or "standard",
                source_agent=source_agent,
                deal_maker_name=payload.deal_maker_name or None,
                supplier_name=supplier_name or None,
                remark=(r.remarks or payload.remark) or None,
                airline_type=payload.airline_type or None,
                airline_name=(r.airline_name or payload.airline_name) or None,
                valid_from=effective_vf,
                valid_to=effective_vt,
                entity=payload.entity or None,
                iata_number=(r.iata_code or payload.iata_number) or None,
                business_type=payload.business_type or None,
                entity_lcc=payload.entity_lcc or None,
                login_id=payload.login_id or None,
                incentive_types=payload.incentive_types or [],
                incentive_data=row_inc_data,
                incl_excl_types=ie_types,
                incl_excl_data=ie_data,
                vice_versa=ie_vv,
                batch_id=batch_id,
            )
            deal_type_key = "b2b"
        else:
            deal = AirlineDeal(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
                status=ManualDealStatus.PENDING_APPROVAL,
                deal_lifecycle_status=DealLifecycleStatus.DRAFT,
                deal_tag=payload.deal_tag or "standard",
                source_agent=source_agent,
                deal_maker_name=payload.deal_maker_name or None,
                remark=(r.remarks or payload.remark) or None,
                airline_type=payload.airline_type or None,
                airline_name=(r.airline_name or payload.airline_name) or None,
                contract_year=payload.contract_year or None,
                valid_from=effective_vf,
                valid_to=effective_vt,
                trigger_type=payload.trigger_type or None,
                payout_type=payload.payout_type or None,
                entity=payload.entity or None,
                iata_number=(r.iata_code or payload.iata_number) or None,
                business_type=payload.business_type or None,
                entity_lcc=payload.entity_lcc or None,
                login_id=payload.login_id or None,
                incentive_types=payload.incentive_types or [],
                incentive_data=row_inc_data,
                incl_excl_types=ie_types,
                incl_excl_data=ie_data,
                vice_versa=ie_vv,
                batch_id=batch_id,
            )
            deal_type_key = "airline"

        db.add(deal)
        await db.flush()
        await _seed_approval_for_deal(deal.id, deal, current_user, db, deal_type=deal_type_key)
        created_ids.append(deal.id)

    await db.commit()
    return UploadConfirmResult(created_count=len(created_ids), created_ids=created_ids, batch_id=batch_id)


# ══════════════════════════════════════════════════════════════════════════════
# MANUAL NEW DEAL  — same table as upload, source_type = "manual"
# ══════════════════════════════════════════════════════════════════════════════

class ManualDealPayload(ConfirmUploadPayload):
    """Exactly the same shape as ConfirmUploadPayload.
    source_type is forced to 'manual' server-side regardless of what is sent.
    file_name / file_type are derived automatically ("manual" / "manual").
    """
    pass


@router.post("/manual", response_model=UploadedDealRead, status_code=status.HTTP_201_CREATED)
async def create_manual_deal(
    payload: ManualDealPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Save a deal entered manually via the New Deal form.
    Stored in the same deals table with source_type='manual'.
    """
    issue_date: date | None = None
    if payload.issue_date:
        try:
            issue_date = date.fromisoformat(payload.issue_date)
        except ValueError:
            pass

    vf_deal = date.fromisoformat(payload.valid_from) if payload.valid_from else None
    vt_deal = date.fromisoformat(payload.valid_to)   if payload.valid_to   else None

    deal = UploadedDeal(
        source_type=UploadedDealSourceType.MANUAL,
        source_agent=payload.source_agent or "manual",
        issue_date=issue_date,
        file_name="manual",
        file_type="manual",
        status=UploadedDealStatus.PENDING_APPROVAL,
        deal_lifecycle_status=DealLifecycleStatus.DRAFT,
        notes=payload.notes,
        airline_type=payload.airline_type   or None,
        airline_name=payload.airline_name   or None,
        contract_year=payload.contract_year or None,
        valid_from=vf_deal,
        valid_to=vt_deal,
        trigger_type=payload.trigger_type   or None,
        payout_type=payload.payout_type     or None,
        entity=payload.entity               or None,
        remark=payload.remark               or None,
        iata_number=payload.iata_number     or None,
        business_type=payload.business_type or None,
        entity_lcc=payload.entity_lcc       or None,
        login_id=payload.login_id           or None,
        variant=(payload.rows[0].variant if payload.rows else None) or None,
        eco_commission=(payload.rows[0].eco_commission if payload.rows else None) or None,
        peco_commission=(payload.rows[0].peco_commission if payload.rows else None) or None,
        bus_commission=(payload.rows[0].bus_commission if payload.rows else None) or None,
        base_type=(payload.rows[0].base_type if payload.rows else None) or None,
        valid_on=(payload.rows[0].valid_on if payload.rows else None) or None,
        validity_raw=(payload.rows[0].validity_raw if payload.rows else None) or None,
        deal_maker_name=payload.deal_maker_name or None,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
    )
    db.add(deal)
    await db.flush()
    _attach_deal_relations(deal.id, payload, db)
    await _seed_approval_for_deal(deal.id, current_user, db, deal_type="upload")
    await db.commit()
    result = await db.execute(
        select(UploadedDeal)
        .options(selectinload(UploadedDeal.incentives), selectinload(UploadedDeal.incl_excl_rules))
        .where(UploadedDeal.id == deal.id)
    )
    return result.scalar_one()


# ══════════════════════════════════════════════════════════════════════════════
# CREATE DEAL — Airline  (POST /deals/manual/airline)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/manual/airline", response_model=AirlineDealResponse, status_code=status.HTTP_201_CREATED)
async def create_airline_deal(
    payload: AirlineDealCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vf = date.fromisoformat(payload.valid_from) if payload.valid_from else None
    vt = date.fromisoformat(payload.valid_to) if payload.valid_to else None

    deal = AirlineDeal(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        status=ManualDealStatus.PENDING_APPROVAL,
        deal_lifecycle_status=DealLifecycleStatus.DRAFT,
        source_agent=payload.source_agent or "manual",
        deal_maker_name=payload.deal_maker_name or None,
        remark=payload.remark or None,
        airline_type=payload.airline_type or None,
        airline_name=payload.airline_name or None,
        contract_year=payload.contract_year or None,
        valid_from=vf,
        valid_to=vt,
        trigger_type=payload.trigger_type or None,
        payout_type=payload.payout_type or None,
        entity=payload.entity or None,
        iata_number=payload.iata_number or None,
        business_type=payload.business_type or None,
        entity_lcc=payload.entity_lcc or None,
        login_id=payload.login_id or None,
        incentive_types=payload.incentive_types or [],
        incentive_data=payload.incentive_data or {},
        incl_excl_types=payload.incl_excl_types or [],
        incl_excl_data=payload.incl_excl_data or {},
        vice_versa=payload.vice_versa or {},
    )
    db.add(deal)
    await db.flush()
    await _seed_approval_for_deal(deal.id, deal, current_user, db, deal_type="airline")
    await db.commit()
    result = await db.execute(select(AirlineDeal).where(AirlineDeal.id == deal.id))
    return result.scalar_one()


# ══════════════════════════════════════════════════════════════════════════════
# CREATE DEAL — B2B  (POST /deals/manual/b2b)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/manual/b2b", response_model=B2BDealResponse, status_code=status.HTTP_201_CREATED)
async def create_b2b_deal(
    payload: B2BDealCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vf = date.fromisoformat(payload.valid_from) if payload.valid_from else None
    vt = date.fromisoformat(payload.valid_to) if payload.valid_to else None

    deal = B2BDeal(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        status=ManualDealStatus.PENDING_APPROVAL,
        deal_lifecycle_status=DealLifecycleStatus.DRAFT,
        source_agent=payload.source_agent or "manual",
        deal_maker_name=payload.deal_maker_name or None,
        supplier_name=payload.supplier_name or None,
        remark=payload.remark or None,
        airline_type=payload.airline_type or None,
        airline_name=payload.airline_name or None,
        valid_from=vf,
        valid_to=vt,
        entity=payload.entity or None,
        iata_number=payload.iata_number or None,
        business_type=payload.business_type or None,
        entity_lcc=payload.entity_lcc or None,
        login_id=payload.login_id or None,
        incentive_types=payload.incentive_types or [],
        incentive_data=payload.incentive_data or {},
        incl_excl_types=payload.incl_excl_types or [],
        incl_excl_data=payload.incl_excl_data or {},
        vice_versa=payload.vice_versa or {},
    )
    db.add(deal)
    await db.flush()
    await _seed_approval_for_deal(deal.id, deal, current_user, db, deal_type="b2b")
    await db.commit()
    result = await db.execute(select(B2BDeal).where(B2BDeal.id == deal.id))
    return result.scalar_one()


# ══════════════════════════════════════════════════════════════════════════════
# DEAL REPOSITORY  — unified list from all 3 tables
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/repository", response_model=list[DealRepositoryItem])
async def get_deal_repository(
    batch_id: Optional[str] = Query(None, description="Filter by batch_id"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all deals for the tenant from upload, airline_deals, and b2b_deals tables."""
    items: list[DealRepositoryItem] = []

    # 1. Upload-table deals (file uploads + legacy manual)
    upload_q = (
        select(UploadedDeal)
        .options(selectinload(UploadedDeal.incentives), selectinload(UploadedDeal.incl_excl_rules))
        .where(UploadedDeal.tenant_id == current_user.tenant_id)
    )
    upload_result = await db.execute(upload_q)
    for d in upload_result.scalars().all():
        items.append(DealRepositoryItem(
            id=d.id,
            deal_no=f"UPL-{d.id:04d}",
            deal_type="upload",
            source_agent=d.source_agent,
            airline_type=d.airline_type,
            airline_name=d.airline_name,
            contract_year=d.contract_year,
            valid_from=d.valid_from,
            valid_to=d.valid_to,
            trigger_type=d.trigger_type,
            payout_type=d.payout_type,
            business_type=d.business_type,
            entity_lcc=d.entity_lcc,
            remark=d.remark,
            deal_maker_name=d.deal_maker_name,
            incentive_types=d.incentive_types,
            incentive_data=d.incentive_data,
            incl_excl_types=d.incl_excl_types,
            incl_excl_data=d.incl_excl_data,
            deal_tag=getattr(d, "deal_tag", "standard") or "standard",
            status=d.status.value if hasattr(d.status, "value") else str(d.status),
            deal_lifecycle_status=d.deal_lifecycle_status.value if hasattr(d.deal_lifecycle_status, "value") else str(d.deal_lifecycle_status or "draft"),
            created_at=d.created_at,
            file_type=d.file_type,
        ))

    # 2. Airline deals
    airline_q = select(AirlineDeal).where(AirlineDeal.tenant_id == current_user.tenant_id)
    if batch_id:
        airline_q = airline_q.where(AirlineDeal.batch_id == batch_id)
    airline_result = await db.execute(airline_q)
    for d in airline_result.scalars().all():
        items.append(DealRepositoryItem(
            id=d.id,
            deal_no=f"AIR-{d.id:04d}",
            deal_type="airline",
            source_agent=d.source_agent,
            airline_type=d.airline_type,
            airline_name=d.airline_name,
            contract_year=d.contract_year,
            valid_from=d.valid_from,
            valid_to=d.valid_to,
            trigger_type=d.trigger_type,
            payout_type=d.payout_type,
            business_type=d.business_type,
            entity_lcc=d.entity_lcc,
            remark=d.remark,
            deal_maker_name=d.deal_maker_name,
            incentive_types=d.incentive_types or [],
            incentive_data=d.incentive_data or {},
            incl_excl_types=d.incl_excl_types or [],
            incl_excl_data=d.incl_excl_data or {},
            deal_tag=d.deal_tag or "standard",
            status=d.status.value if hasattr(d.status, "value") else str(d.status),
            deal_lifecycle_status=d.deal_lifecycle_status.value if hasattr(d.deal_lifecycle_status, "value") else str(d.deal_lifecycle_status or "draft"),
            created_at=d.created_at,
            file_type=None,
        ))

    # 3. B2B deals
    b2b_q = select(B2BDeal).where(B2BDeal.tenant_id == current_user.tenant_id)
    if batch_id:
        b2b_q = b2b_q.where(B2BDeal.batch_id == batch_id)
    b2b_result = await db.execute(b2b_q)
    for d in b2b_result.scalars().all():
        items.append(DealRepositoryItem(
            id=d.id,
            deal_no=f"B2B-{d.id:04d}",
            deal_type="b2b",
            source_agent=d.source_agent,
            airline_type=d.airline_type,
            airline_name=d.airline_name,
            contract_year=None,
            valid_from=d.valid_from,
            valid_to=d.valid_to,
            trigger_type=None,
            payout_type=None,
            business_type=d.business_type,
            entity_lcc=d.entity_lcc,
            remark=d.remark,
            deal_maker_name=d.deal_maker_name,
            incentive_types=d.incentive_types or [],
            incentive_data=d.incentive_data or {},
            incl_excl_types=d.incl_excl_types or [],
            incl_excl_data=d.incl_excl_data or {},
            deal_tag=d.deal_tag or "standard",
            status=d.status.value if hasattr(d.status, "value") else str(d.status),
            deal_lifecycle_status=d.deal_lifecycle_status.value if hasattr(d.deal_lifecycle_status, "value") else str(d.deal_lifecycle_status or "draft"),
            created_at=d.created_at,
            file_type=None,
        ))

    items.sort(key=lambda x: x.created_at, reverse=True)
    return items


# ══════════════════════════════════════════════════════════════════════════════
# DEAL BATCHES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/batches", response_model=list[DealBatchRead])
async def list_deal_batches(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all deal upload batches for the tenant, with deal count per batch."""
    from app.models.user import User as UserModel
    batches_result = await db.execute(
        select(DealBatch)
        .where(DealBatch.tenant_id == current_user.tenant_id)
        .order_by(DealBatch.created_at.desc())
    )
    batches = batches_result.scalars().all()

    airline_counts_result = await db.execute(
        select(AirlineDeal.batch_id, func.count(AirlineDeal.id))
        .where(AirlineDeal.tenant_id == current_user.tenant_id, AirlineDeal.batch_id != None)  # noqa: E711
        .group_by(AirlineDeal.batch_id)
    )
    b2b_counts_result = await db.execute(
        select(B2BDeal.batch_id, func.count(B2BDeal.id))
        .where(B2BDeal.tenant_id == current_user.tenant_id, B2BDeal.batch_id != None)  # noqa: E711
        .group_by(B2BDeal.batch_id)
    )
    deal_counts: dict[str, int] = {}
    for bid, cnt in airline_counts_result.all():
        deal_counts[bid] = deal_counts.get(bid, 0) + cnt
    for bid, cnt in b2b_counts_result.all():
        deal_counts[bid] = deal_counts.get(bid, 0) + cnt

    airline_lc_result = await db.execute(
        select(AirlineDeal.batch_id, AirlineDeal.deal_lifecycle_status, func.count(AirlineDeal.id))
        .where(AirlineDeal.tenant_id == current_user.tenant_id, AirlineDeal.batch_id != None)  # noqa: E711
        .group_by(AirlineDeal.batch_id, AirlineDeal.deal_lifecycle_status)
    )
    b2b_lc_result = await db.execute(
        select(B2BDeal.batch_id, B2BDeal.deal_lifecycle_status, func.count(B2BDeal.id))
        .where(B2BDeal.tenant_id == current_user.tenant_id, B2BDeal.batch_id != None)  # noqa: E711
        .group_by(B2BDeal.batch_id, B2BDeal.deal_lifecycle_status)
    )
    lifecycle_counts: dict[str, dict[str, int]] = {}
    for bid, status, cnt in airline_lc_result.all():
        if bid is None:
            continue
        s = status.value if hasattr(status, "value") else str(status)
        lc = lifecycle_counts.setdefault(bid, {})
        lc[s] = lc.get(s, 0) + int(cnt)
    for bid, status, cnt in b2b_lc_result.all():
        if bid is None:
            continue
        s = status.value if hasattr(status, "value") else str(status)
        lc = lifecycle_counts.setdefault(bid, {})
        lc[s] = lc.get(s, 0) + int(cnt)

    user_ids = list({b.created_by_id for b in batches})
    user_names: dict[int, str] = {}
    if user_ids:
        users_result = await db.execute(select(UserModel).where(UserModel.id.in_(user_ids)))
        for u in users_result.scalars().all():
            user_names[u.id] = u.full_name or u.email or str(u.id)

    return [
        DealBatchRead(
            batch_id=b.batch_id,
            deal_type=b.deal_type,
            deal_tag=getattr(b, "deal_tag", "standard") or "standard",
            supplier_name=b.supplier_name,
            file_name=b.file_name,
            file_type=b.file_type,
            incentive_types=b.incentive_types or [],
            valid_from=b.valid_from,
            valid_to=b.valid_to,
            deal_count=deal_counts.get(b.batch_id, 0),
            lifecycle_counts=lifecycle_counts.get(b.batch_id, {}),
            created_by_name=user_names.get(b.created_by_id),
            created_at=b.created_at,
        )
        for b in batches
    ]


@router.get("/batches/{batch_id}", response_model=DealBatchRead)
async def get_deal_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single deal batch by batch_id."""
    from app.models.user import User as UserModel
    result = await db.execute(
        select(DealBatch).where(
            DealBatch.batch_id == batch_id,
            DealBatch.tenant_id == current_user.tenant_id,
        )
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    airline_cnt = await db.execute(
        select(func.count(AirlineDeal.id))
        .where(AirlineDeal.batch_id == batch_id, AirlineDeal.tenant_id == current_user.tenant_id)
    )
    b2b_cnt = await db.execute(
        select(func.count(B2BDeal.id))
        .where(B2BDeal.batch_id == batch_id, B2BDeal.tenant_id == current_user.tenant_id)
    )
    deal_count = (airline_cnt.scalar() or 0) + (b2b_cnt.scalar() or 0)

    user_result = await db.execute(select(UserModel).where(UserModel.id == batch.created_by_id))
    user = user_result.scalar_one_or_none()
    created_by_name = user.full_name or user.email if user else None

    return DealBatchRead(
        batch_id=batch.batch_id,
        deal_type=batch.deal_type,
        deal_tag=getattr(batch, "deal_tag", "standard") or "standard",
        supplier_name=batch.supplier_name,
        file_name=batch.file_name,
        file_type=batch.file_type,
        incentive_types=batch.incentive_types or [],
        valid_from=batch.valid_from,
        valid_to=batch.valid_to,
        deal_count=deal_count,
        created_by_name=created_by_name,
        created_at=batch.created_at,
    )


@router.get("/repository/{deal_id}/history", response_model=DealHistoryResponse)
async def get_repository_deal_history(
    deal_id: int,
    deal_type: str = Query("upload", description="'upload' | 'airline' | 'b2b'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unified history endpoint for any deal type."""
    # Fetch the deal's created_by_id and created_at from the right table
    if deal_type == "airline":
        result = await db.execute(
            select(AirlineDeal).where(
                AirlineDeal.id == deal_id,
                AirlineDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        created_by_id = deal.created_by_id
        created_at = deal.created_at
        source_type_str = "manual"
        status_str = deal.status.value if hasattr(deal.status, "value") else str(deal.status)
    elif deal_type == "b2b":
        result = await db.execute(
            select(B2BDeal).where(
                B2BDeal.id == deal_id,
                B2BDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        created_by_id = deal.created_by_id
        created_at = deal.created_at
        source_type_str = "manual"
        status_str = deal.status.value if hasattr(deal.status, "value") else str(deal.status)
    else:
        result = await db.execute(
            select(UploadedDeal).where(
                UploadedDeal.id == deal_id,
                UploadedDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        created_by_id = deal.created_by_id
        created_at = deal.created_at
        source_type_str = deal.source_type.value if hasattr(deal.source_type, "value") else str(deal.source_type)
        status_str = deal.status.value if hasattr(deal.status, "value") else str(deal.status)

    # Find the DealApproval using the polymorphic (deal_type, deal_id) key
    approval_result = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.deal_type == deal_type, DealApproval.deal_id == deal_id)
    )
    approval = approval_result.scalar_one_or_none()

    user_ids: set[int] = {created_by_id}
    steps = approval.steps if approval else []
    for s in steps:
        user_ids.add(s.assigned_user_id)
        if s.acted_by_id:
            user_ids.add(s.acted_by_id)

    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    user_map: dict[int, str] = {u.id: u.full_name for u in users_result.scalars().all()}

    return DealHistoryResponse(
        deal_id=deal_id,
        created_by_name=user_map.get(created_by_id, f"User #{created_by_id}"),
        created_at=created_at,
        source_type=source_type_str,
        status=status_str,
        steps=[
            DealHistoryStepRead(
                step_order=s.step_order,
                role=s.role,
                assigned_user_name=user_map.get(s.assigned_user_id, f"User #{s.assigned_user_id}"),
                status=s.status.value if hasattr(s.status, "value") else str(s.status),
                acted_by_name=user_map.get(s.acted_by_id) if s.acted_by_id else None,
                acted_at=s.acted_at,
                reason=s.reason,
            )
            for s in sorted(steps, key=lambda x: (x.step_order, x.id))
        ],
    )


@router.patch("/repository/{deal_id}", status_code=200, response_model=DealRepositoryItem)
async def update_repository_deal(
    deal_id: int,
    payload: DealUpdatePayload,
    deal_type: str = Query("airline", description="'upload' | 'airline' | 'b2b'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update any deal in the repository (upload / airline / b2b table)."""
    if deal_type == "airline":
        result = await db.execute(
            select(AirlineDeal).where(
                AirlineDeal.id == deal_id,
                AirlineDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
    elif deal_type == "b2b":
        result = await db.execute(
            select(B2BDeal).where(
                B2BDeal.id == deal_id,
                B2BDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
    else:
        result = await db.execute(
            select(UploadedDeal).where(
                UploadedDeal.id == deal_id,
                UploadedDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()

    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field in ("valid_from", "valid_to") and isinstance(value, str):
            value = date.fromisoformat(value) if value else None
        if hasattr(deal, field):
            setattr(deal, field, value)

    await db.commit()
    await db.refresh(deal)

    status_str = deal.status.value if hasattr(deal.status, "value") else str(deal.status)
    lifecycle_str = deal.deal_lifecycle_status.value if hasattr(deal.deal_lifecycle_status, "value") else str(deal.deal_lifecycle_status or "draft")
    _prefix_map = {"airline": "AIR", "b2b": "B2B", "upload": "UPL"}
    return DealRepositoryItem(
        id=deal.id,
        deal_no=f"{_prefix_map.get(deal_type, 'UPL')}-{deal.id:04d}",
        deal_type=deal_type,
        source_agent=deal.source_agent,
        airline_type=deal.airline_type,
        airline_name=deal.airline_name,
        contract_year=getattr(deal, "contract_year", None),
        valid_from=deal.valid_from,
        valid_to=deal.valid_to,
        trigger_type=getattr(deal, "trigger_type", None),
        payout_type=getattr(deal, "payout_type", None),
        business_type=getattr(deal, "business_type", None),
        entity_lcc=getattr(deal, "entity_lcc", None),
        remark=deal.remark,
        deal_maker_name=deal.deal_maker_name,
        incentive_types=deal.incentive_types or [],
        incentive_data=deal.incentive_data or {},
        incl_excl_types=deal.incl_excl_types or [],
        incl_excl_data=deal.incl_excl_data or {},
        status=status_str,
        deal_lifecycle_status=lifecycle_str,
        created_at=deal.created_at,
        file_type=None,
    )


# ── Delete a deal from the repository ────────────────────────────────────

@router.delete("/repository/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository_deal(
    deal_id: int,
    deal_type: str = Query("airline", description="'upload' | 'airline' | 'b2b'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete any deal in the repository (upload / airline / b2b table)."""
    if deal_type == "airline":
        result = await db.execute(
            select(AirlineDeal).where(
                AirlineDeal.id == deal_id,
                AirlineDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
    elif deal_type == "b2b":
        result = await db.execute(
            select(B2BDeal).where(
                B2BDeal.id == deal_id,
                B2BDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
    else:
        result = await db.execute(
            select(UploadedDeal).where(
                UploadedDeal.id == deal_id,
                UploadedDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()

    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    await db.delete(deal)
    await db.commit()


# ── Resubmit a rejected deal ──────────────────────────────────────────────

@router.post("/repository/{deal_id}/resubmit")
async def resubmit_deal(
    deal_id: int,
    deal_type: str = Query(..., description="'upload' | 'airline' | 'b2b'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resubmit a rejected deal for approval by resetting the approval workflow."""
    if deal_type == "airline":
        result = await db.execute(
            select(AirlineDeal).where(
                AirlineDeal.id == deal_id,
                AirlineDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
        rejected_status = ManualDealStatus.REJECTED
        pending_status  = ManualDealStatus.PENDING_APPROVAL
    elif deal_type == "b2b":
        result = await db.execute(
            select(B2BDeal).where(
                B2BDeal.id == deal_id,
                B2BDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
        rejected_status = ManualDealStatus.REJECTED
        pending_status  = ManualDealStatus.PENDING_APPROVAL
    else:
        result = await db.execute(
            select(UploadedDeal).where(
                UploadedDeal.id == deal_id,
                UploadedDeal.tenant_id == current_user.tenant_id,
            )
        )
        deal = result.scalar_one_or_none()
        rejected_status = UploadedDealStatus.REJECTED
        pending_status  = UploadedDealStatus.PENDING_APPROVAL

    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if deal.status != rejected_status:
        raise HTTPException(status_code=400, detail="Deal is not in rejected status")
    if deal.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the deal creator can resubmit")

    # Delete existing DealApproval and its steps (unique constraint requires clean slate)
    approval_result = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.deal_type == deal_type, DealApproval.deal_id == deal_id)
    )
    existing_approval = approval_result.scalar_one_or_none()
    if existing_approval:
        for step in existing_approval.steps:
            await db.delete(step)
        await db.delete(existing_approval)
        await db.flush()

    deal.status = pending_status
    await _seed_approval_for_deal(deal_id, current_user, db, deal_type=deal_type)
    await db.commit()
    return {"success": True, "message": "Deal resubmitted for approval"}


# ── List uploaded deals ────────────────────────────────────────────────────

@router.get("/uploads", response_model=list[UploadedDealSummary])
async def list_deals_repository(
    skip:   int = 0,
    limit:  int = 100,
    db:     AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all deals for the current user's tenant."""
    q = (
        select(UploadedDeal)
        .options(
            selectinload(UploadedDeal.incentives),
            selectinload(UploadedDeal.incl_excl_rules),
        )
        .where(UploadedDeal.tenant_id == current_user.tenant_id)
        .order_by(UploadedDeal.created_at.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(q)
    deals  = result.scalars().all()

    summaries = []
    for d in deals:
        summaries.append(UploadedDealSummary(
            id=d.id,
            source_type=d.source_type,
            source_agent=d.source_agent,
            issue_date=d.issue_date,
            file_name=d.file_name,
            file_type=d.file_type,
            status=d.status,
            notes=d.notes,
            created_at=d.created_at,
            row_count=1,
            airline_type=d.airline_type,
            airline_name=d.airline_name,
            contract_year=d.contract_year,
            valid_from=d.valid_from,
            valid_to=d.valid_to,
            trigger_type=d.trigger_type,
            payout_type=d.payout_type,
            business_type=d.business_type,
            entity_lcc=d.entity_lcc,
            remark=d.remark,
            deal_maker_name=d.deal_maker_name,
            incentive_types=d.incentive_types,
            incentive_data=d.incentive_data,
            incl_excl_types=d.incl_excl_types,
            incl_excl_data=d.incl_excl_data,
        ))
    return summaries


@router.get("/uploads/{upload_id}", response_model=UploadedDealRead)
async def get_uploaded_deal(
    upload_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UploadedDeal).options(selectinload(UploadedDeal.incentives), selectinload(UploadedDeal.incl_excl_rules))
        .where(
            UploadedDeal.id == upload_id,
            UploadedDeal.tenant_id == current_user.tenant_id,
        )
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_uploaded_deal(
    upload_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UploadedDeal).where(
            UploadedDeal.id == upload_id,
            UploadedDeal.tenant_id == current_user.tenant_id,
        )
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    await db.delete(deal)
    await db.commit()


@router.get("/uploads/{deal_id}/history", response_model=DealHistoryResponse)
async def get_deal_history(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return full creation + approval history for a deal, with user names resolved."""
    deal_result = await db.execute(
        select(UploadedDeal).where(
            UploadedDeal.id == deal_id,
            UploadedDeal.tenant_id == current_user.tenant_id,
        )
    )
    deal = deal_result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    approval_result = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.deal_id == deal_id)
    )
    approval = approval_result.scalar_one_or_none()

    user_ids: set[int] = {deal.created_by_id}
    steps = approval.steps if approval else []
    for s in steps:
        user_ids.add(s.assigned_user_id)
        if s.acted_by_id:
            user_ids.add(s.acted_by_id)

    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    user_map: dict[int, str] = {u.id: u.full_name for u in users_result.scalars().all()}

    return DealHistoryResponse(
        deal_id=deal.id,
        created_by_name=user_map.get(deal.created_by_id, f"User #{deal.created_by_id}"),
        created_at=deal.created_at,
        source_type=deal.source_type.value if hasattr(deal.source_type, "value") else str(deal.source_type),
        status=deal.status.value if hasattr(deal.status, "value") else str(deal.status),
        steps=[
            DealHistoryStepRead(
                step_order=s.step_order,
                role=s.role,
                assigned_user_name=user_map.get(s.assigned_user_id, f"User #{s.assigned_user_id}"),
                status=s.status.value if hasattr(s.status, "value") else str(s.status),
                acted_by_name=user_map.get(s.acted_by_id) if s.acted_by_id else None,
                acted_at=s.acted_at,
                reason=s.reason,
            )
            for s in sorted(steps, key=lambda x: (x.step_order, x.id))
        ],
    )


@router.get("/approvals/inbox", response_model=list[ApprovalInboxItem])
async def approvals_inbox(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all deals pending the current user's approval action, across all deal tables."""
    # 1. Find all DealApproval records where this user is assigned at the current pending step
    stmt = (
        select(DealApproval)
        .join(DealApprovalStep, DealApprovalStep.deal_approval_id == DealApproval.id)
        .where(
            DealApproval.status == ApprovalActionStatus.PENDING,
            DealApproval.current_step_order == DealApprovalStep.step_order,
            DealApprovalStep.assigned_user_id == current_user.id,
            DealApprovalStep.status == ApprovalActionStatus.PENDING,
        )
        .order_by(DealApproval.submitted_at.desc())
    )
    result = await db.execute(stmt)
    approvals = result.scalars().all()

    # 2. Group by deal_type for efficient batch lookup
    airline_ids  = [a.deal_id for a in approvals if a.deal_type == "airline"]
    b2b_ids      = [a.deal_id for a in approvals if a.deal_type == "b2b"]
    upload_ids   = [a.deal_id for a in approvals if a.deal_type == "upload"]

    airline_map: dict[int, AirlineDeal]   = {}
    b2b_map:     dict[int, B2BDeal]       = {}
    upload_map:  dict[int, UploadedDeal]  = {}

    if airline_ids:
        rows = await db.execute(
            select(AirlineDeal).where(
                AirlineDeal.id.in_(airline_ids),
                AirlineDeal.tenant_id == current_user.tenant_id,
            )
        )
        airline_map = {d.id: d for d in rows.scalars().all()}

    if b2b_ids:
        rows = await db.execute(
            select(B2BDeal).where(
                B2BDeal.id.in_(b2b_ids),
                B2BDeal.tenant_id == current_user.tenant_id,
            )
        )
        b2b_map = {d.id: d for d in rows.scalars().all()}

    if upload_ids:
        rows = await db.execute(
            select(UploadedDeal).where(
                UploadedDeal.id.in_(upload_ids),
                UploadedDeal.tenant_id == current_user.tenant_id,
            )
        )
        upload_map = {d.id: d for d in rows.scalars().all()}

    # 3. Build response — id = DealApproval.id (routing key), deal_id = deal's own ID
    items: list[ApprovalInboxItem] = []
    for approval in approvals:
        status_str = approval.status.value if hasattr(approval.status, "value") else str(approval.status)

        if approval.deal_type == "airline":
            deal = airline_map.get(approval.deal_id)
            if not deal:
                continue
            items.append(ApprovalInboxItem(
                id=approval.id, deal_id=deal.id, deal_type="airline",
                source_agent=deal.source_agent,
                airline_name=deal.airline_name, airline_type=deal.airline_type,
                status=status_str, created_at=deal.created_at,
                valid_from=deal.valid_from, valid_to=deal.valid_to,
                business_type=deal.business_type,
                incentive_types=deal.incentive_types or [],
                incentive_data=deal.incentive_data or {},
                incl_excl_types=deal.incl_excl_types or [],
                incl_excl_data=deal.incl_excl_data or {},
                deal_maker_name=deal.deal_maker_name,
                contract_year=deal.contract_year,
                trigger_type=deal.trigger_type,
                payout_type=deal.payout_type,
                entity_lcc=deal.entity_lcc,
                remark=deal.remark,
                deal_no=f"AIR-{deal.id:04d}",
            ))
        elif approval.deal_type == "b2b":
            deal_b2b = b2b_map.get(approval.deal_id)
            if not deal_b2b:
                continue
            items.append(ApprovalInboxItem(
                id=approval.id, deal_id=deal_b2b.id, deal_type="b2b",
                source_agent=deal_b2b.source_agent,
                airline_name=deal_b2b.airline_name, airline_type=deal_b2b.airline_type,
                status=status_str, created_at=deal_b2b.created_at,
                valid_from=deal_b2b.valid_from, valid_to=deal_b2b.valid_to,
                business_type=deal_b2b.business_type,
                incentive_types=deal_b2b.incentive_types or [],
                incentive_data=deal_b2b.incentive_data or {},
                incl_excl_types=deal_b2b.incl_excl_types or [],
                incl_excl_data=deal_b2b.incl_excl_data or {},
                deal_maker_name=deal_b2b.deal_maker_name,
                contract_year=getattr(deal_b2b, "contract_year", None),
                trigger_type=getattr(deal_b2b, "trigger_type", None),
                payout_type=getattr(deal_b2b, "payout_type", None),
                entity_lcc=deal_b2b.entity_lcc,
                remark=deal_b2b.remark,
                deal_no=f"B2B-{deal_b2b.id:04d}",
            ))
        else:
            deal_up = upload_map.get(approval.deal_id)
            if not deal_up:
                continue
            items.append(ApprovalInboxItem(
                id=approval.id, deal_id=deal_up.id, deal_type="upload",
                source_agent=deal_up.source_agent,
                airline_name=deal_up.airline_name, airline_type=deal_up.airline_type,
                status=status_str, created_at=deal_up.created_at,
                valid_from=deal_up.valid_from, valid_to=deal_up.valid_to,
                business_type=deal_up.business_type,
                incentive_types=deal_up.incentive_types or [],
                incentive_data=deal_up.incentive_data or {},
                incl_excl_types=deal_up.incl_excl_types or [],
                incl_excl_data=deal_up.incl_excl_data or {},
                deal_maker_name=deal_up.deal_maker_name,
                contract_year=deal_up.contract_year,
                trigger_type=deal_up.trigger_type,
                payout_type=deal_up.payout_type,
                entity_lcc=deal_up.entity_lcc,
                remark=deal_up.remark,
                deal_no=f"UPL-{deal_up.id:04d}",
            ))

    return items


@router.get("/approvals/{approval_id}", response_model=DealApprovalRead)
async def get_deal_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Deal approval not found")

    role_value = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    is_super_admin = role_value == "super_admin"
    is_assigned = any(s.assigned_user_id == current_user.id for s in approval.steps)
    if not is_super_admin and not is_assigned:
        raise HTTPException(status_code=403, detail="Not allowed to view this approval")
    visible_steps = approval.steps
    if not is_super_admin:
        visible_steps = [
            s
            for s in approval.steps
            if s.step_order < approval.current_step_order
            or (s.step_order == approval.current_step_order and s.assigned_user_id == current_user.id)
        ]
    return DealApprovalRead(
        id=approval.id,
        deal_id=approval.deal_id,
        workflow_id=approval.workflow_id,
        current_step_order=approval.current_step_order,
        status=approval.status.value if hasattr(approval.status, "value") else str(approval.status),
        submitted_by_id=approval.submitted_by_id,
        submitted_at=approval.submitted_at,
        updated_at=approval.updated_at,
        steps=[
            DealApprovalStepRead(
                id=s.id,
                step_order=s.step_order,
                role=s.role,
                assigned_user_id=s.assigned_user_id,
                status=s.status.value if hasattr(s.status, "value") else str(s.status),
                acted_by_id=s.acted_by_id,
                acted_at=s.acted_at,
                reason=s.reason,
            )
            for s in sorted(visible_steps, key=lambda x: (x.step_order, x.id))
        ],
    )


async def _load_deal_for_approval(approval: DealApproval, db: AsyncSession):
    """Return (deal_object, deal_type_str) for a DealApproval record."""
    if approval.deal_type == "airline":
        r = await db.execute(select(AirlineDeal).where(AirlineDeal.id == approval.deal_id))
        return r.scalar_one(), "airline"
    elif approval.deal_type == "b2b":
        r = await db.execute(select(B2BDeal).where(B2BDeal.id == approval.deal_id))
        return r.scalar_one(), "b2b"
    else:
        r = await db.execute(select(UploadedDeal).where(UploadedDeal.id == approval.deal_id))
        return r.scalar_one(), "upload"


async def _find_matching_active_deals(
    new_deal,
    new_deal_type: str,
    db: AsyncSession,
) -> list[ClosingDealSummary]:
    """Return summaries of ACTIVE deals that would be closed when new_deal is approved."""
    inc_data  = new_deal.incentive_data or {}
    inc_types = new_deal.incentive_types or []
    primary   = inc_types[0] if inc_types else None
    pdata     = inc_data.get(primary, {}) if (primary and isinstance(inc_data, dict)) else {}
    new_flight_type = pdata.get("flightType")
    new_class       = pdata.get("class")

    _prefix = {"airline": "AIR", "b2b": "B2B", "upload": "UPL"}
    summaries: list[ClosingDealSummary] = []
    for Model, dtype in [(AirlineDeal, "airline"), (B2BDeal, "b2b"), (UploadedDeal, "upload")]:
        filters = [
            Model.tenant_id             == new_deal.tenant_id,
            Model.deal_lifecycle_status == DealLifecycleStatus.ACTIVE,
            Model.deal_maker_name       == new_deal.deal_maker_name,
            Model.airline_name          == new_deal.airline_name,
            Model.airline_type          == new_deal.airline_type,
        ]
        if dtype == new_deal_type:
            filters.append(Model.id != new_deal.id)
        result = await db.execute(select(Model).where(*filters))
        for d in result.scalars().all():
            d_data  = d.incentive_data or {}
            d_types = d.incentive_types or []
            d_p     = d_types[0] if d_types else None
            d_pd    = d_data.get(d_p, {}) if (d_p and isinstance(d_data, dict)) else {}
            if d_pd.get("flightType") == new_flight_type and d_pd.get("class") == new_class:
                summaries.append(ClosingDealSummary(
                    deal_id=d.id,
                    deal_type=dtype,
                    deal_no=f"{_prefix[dtype]}-{d.id:04d}",
                    airline_name=getattr(d, "airline_name", None),
                    airline_type=getattr(d, "airline_type", None),
                    source_agent=getattr(d, "source_agent", None),
                    deal_maker_name=getattr(d, "deal_maker_name", None),
                    valid_from=getattr(d, "valid_from", None),
                    valid_to=getattr(d, "valid_to", None),
                    contract_year=getattr(d, "contract_year", None),
                    business_type=getattr(d, "business_type", None),
                    trigger_type=getattr(d, "trigger_type", None),
                    payout_type=getattr(d, "payout_type", None),
                    entity_lcc=getattr(d, "entity_lcc", None),
                    incentive_types=list(getattr(d, "incentive_types", None) or []),
                    incentive_data=dict(getattr(d, "incentive_data", None) or {}),
                    incl_excl_types=list(getattr(d, "incl_excl_types", None) or []),
                    incl_excl_data=dict(getattr(d, "incl_excl_data", None) or {}),
                    remark=getattr(d, "remark", None),
                ))
    return summaries


async def _close_matching_active_deals(
    new_deal,
    new_deal_type: str,
    db: AsyncSession,
) -> None:
    """When a deal is finally approved, close all active deals on the same tenant
    that match on: deal_maker_name, airline_name, airline_type, flightType, class."""
    inc_data   = (new_deal.incentive_data or {}) if not callable(getattr(new_deal, 'incentive_data', None)) else new_deal.incentive_data
    inc_types  = (new_deal.incentive_types or []) if not callable(getattr(new_deal, 'incentive_types', None)) else new_deal.incentive_types
    primary    = inc_types[0] if inc_types else None
    pdata      = inc_data.get(primary, {}) if (primary and isinstance(inc_data, dict)) else {}
    new_flight_type = pdata.get("flightType")
    new_class       = pdata.get("class")

    for Model, dtype in [(AirlineDeal, "airline"), (B2BDeal, "b2b"), (UploadedDeal, "upload")]:
        filters = [
            Model.tenant_id             == new_deal.tenant_id,
            Model.deal_lifecycle_status == DealLifecycleStatus.ACTIVE,
            Model.deal_maker_name       == new_deal.deal_maker_name,
            Model.airline_name          == new_deal.airline_name,
            Model.airline_type          == new_deal.airline_type,
        ]
        # Exclude the deal we just approved
        if dtype == new_deal_type:
            filters.append(Model.id != new_deal.id)

        result = await db.execute(select(Model).where(*filters))
        for d in result.scalars().all():
            d_data   = (d.incentive_data or {}) if not callable(getattr(d, 'incentive_data', None)) else d.incentive_data
            d_types  = (d.incentive_types or []) if not callable(getattr(d, 'incentive_types', None)) else d.incentive_types
            d_primary = d_types[0] if d_types else None
            d_pdata  = d_data.get(d_primary, {}) if (d_primary and isinstance(d_data, dict)) else {}
            if d_pdata.get("flightType") == new_flight_type and d_pdata.get("class") == new_class:
                d.deal_lifecycle_status = DealLifecycleStatus.CLOSED


async def _apply_decision(
    approval_id: int,
    decision: ApprovalActionStatus,
    reason: str | None,
    db: AsyncSession,
    current_user: User,
) -> DealApproval:
    result = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Deal approval not found")
    current_step_rows = [s for s in approval.steps if s.step_order == approval.current_step_order]
    if not current_step_rows:
        raise HTTPException(status_code=400, detail="Invalid approval state")
    current_user_row = next((s for s in current_step_rows if s.assigned_user_id == current_user.id), None)
    if not current_user_row:
        raise HTTPException(status_code=403, detail="Only assigned approver can act")
    if current_user_row.status != ApprovalActionStatus.PENDING:
        raise HTTPException(status_code=400, detail="Current step already actioned")

    current_user_row.status = decision
    current_user_row.acted_by_id = current_user.id
    from datetime import datetime
    now = datetime.utcnow()
    current_user_row.acted_at = now
    current_user_row.reason = reason

    # Fetch the deal from the correct table based on deal_type
    deal_type = approval.deal_type
    if deal_type == "airline":
        deal_result = await db.execute(select(AirlineDeal).where(AirlineDeal.id == approval.deal_id))
        deal = deal_result.scalar_one()
        approved_status = ManualDealStatus.APPROVED
        rejected_status = ManualDealStatus.REJECTED
    elif deal_type == "b2b":
        deal_result = await db.execute(select(B2BDeal).where(B2BDeal.id == approval.deal_id))
        deal = deal_result.scalar_one()
        approved_status = ManualDealStatus.APPROVED
        rejected_status = ManualDealStatus.REJECTED
    else:
        deal_result = await db.execute(select(UploadedDeal).where(UploadedDeal.id == approval.deal_id))
        deal = deal_result.scalar_one()
        approved_status = UploadedDealStatus.APPROVED
        rejected_status = UploadedDealStatus.REJECTED

    if decision == ApprovalActionStatus.REJECTED:
        if any(s.status == ApprovalActionStatus.APPROVED for s in current_step_rows):
            raise HTTPException(status_code=400, detail="Step already approved; cannot reject now")
        approval.status = ApprovalActionStatus.REJECTED
        deal.status = rejected_status
        for sibling in current_step_rows:
            if sibling.id != current_user_row.id and sibling.status == ApprovalActionStatus.PENDING:
                sibling.status = ApprovalActionStatus.REJECTED
                sibling.acted_at = now
                sibling.reason = "Auto-closed due to peer rejection"
    else:
        # approve-wins for current step: close all sibling pending rows
        for sibling in current_step_rows:
            if sibling.id != current_user_row.id and sibling.status == ApprovalActionStatus.PENDING:
                sibling.status = ApprovalActionStatus.SKIPPED
                sibling.acted_at = now
                sibling.reason = "Auto-closed due to peer approval"
        next_step = next((s for s in approval.steps if s.step_order > approval.current_step_order), None)
        if next_step:
            approval.current_step_order = next_step.step_order
        else:
            approval.status = ApprovalActionStatus.APPROVED
            deal.status = approved_status
            deal.deal_lifecycle_status = DealLifecycleStatus.ACTIVE
            await _close_matching_active_deals(deal, deal_type, db)

    await db.commit()
    refresh = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.id == approval.id)
    )
    return refresh.scalar_one()


@router.get("/approvals/{approval_id}/closing-preview", response_model=ClosingPreviewResponse)
async def get_closing_preview(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return which ACTIVE deals would be closed if this approval reaches final approval."""
    result = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    is_final = not any(s.step_order > approval.current_step_order for s in approval.steps)
    if not is_final:
        return ClosingPreviewResponse(is_final_step=False, closing_deals=[])

    deal, deal_type = await _load_deal_for_approval(approval, db)
    closing = await _find_matching_active_deals(deal, deal_type, db)
    return ClosingPreviewResponse(is_final_step=True, closing_deals=closing)


@router.post("/approvals/bulk-closing-preview", response_model=dict[str, ClosingPreviewResponse])
async def bulk_closing_preview(
    payload: BulkClosingPreviewPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return closing preview for each approval_id in one batch call."""
    out: dict[str, ClosingPreviewResponse] = {}
    for aid in payload.deal_ids:
        try:
            r = await db.execute(
                select(DealApproval)
                .options(selectinload(DealApproval.steps))
                .where(DealApproval.id == aid)
            )
            approval = r.scalar_one_or_none()
            if not approval:
                out[str(aid)] = ClosingPreviewResponse(is_final_step=False, closing_deals=[])
                continue
            is_final = not any(s.step_order > approval.current_step_order for s in approval.steps)
            if not is_final:
                out[str(aid)] = ClosingPreviewResponse(is_final_step=False, closing_deals=[])
                continue
            deal, deal_type = await _load_deal_for_approval(approval, db)
            closing = await _find_matching_active_deals(deal, deal_type, db)
            out[str(aid)] = ClosingPreviewResponse(is_final_step=True, closing_deals=closing)
        except Exception:
            out[str(aid)] = ClosingPreviewResponse(is_final_step=False, closing_deals=[])
    return out


@router.post("/approvals/{approval_id}/approve", response_model=DealApprovalRead)
async def approve_deal_step(
    approval_id: int,
    payload: ApprovalDecisionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _apply_decision(
        approval_id=approval_id,
        decision=ApprovalActionStatus.APPROVED,
        reason=payload.reason,
        db=db,
        current_user=current_user,
    )


@router.post("/approvals/{approval_id}/reject", response_model=DealApprovalRead)
async def reject_deal_step(
    approval_id: int,
    payload: ApprovalDecisionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Rejection reason is required")
    return await _apply_decision(
        approval_id=approval_id,
        decision=ApprovalActionStatus.REJECTED,
        reason=payload.reason.strip(),
        db=db,
        current_user=current_user,
    )


@router.post("/approvals/bulk-approve", response_model=BulkApproveResult)
async def bulk_approve_deals(
    payload: BulkApprovePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approved: list[int] = []
    failed: list[dict] = []
    for approval_id in payload.deal_ids:   # deal_ids field now carries DealApproval.id values
        try:
            await _apply_decision(
                approval_id=approval_id,
                decision=ApprovalActionStatus.APPROVED,
                reason=payload.reason,
                db=db,
                current_user=current_user,
            )
            approved.append(approval_id)
        except HTTPException as exc:
            await db.rollback()
            failed.append({"deal_id": approval_id, "reason": str(exc.detail)})
    return BulkApproveResult(approved=approved, failed=failed)
