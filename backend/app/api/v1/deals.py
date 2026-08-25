from __future__ import annotations

from datetime import date
from typing import Optional
import logging
import uuid

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query, Form
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
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
    ExtractedRow,
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
from app.services.airline_resolver import (
    RESOLVED,
    AirlineIndex,
    AirlineMatch,
    carrier_code_from_row_field,
    resolve_and_create_airlines,
)
import json as _json
from app.models.deal import (
    DealStatement, Deal as UnifiedDeal, DealIncentiveConfig,
    DealIncentiveSlab, DealIncentiveSlabValue, DealRule, DealRuleCondition,
    DealSourceType, DealKind, DealTagType, DealStatusType, DealLifecycleType,
    DealDirection, DealScopeType, SlabTypeEnum, SlabValueTypeEnum, RuleOperatorEnum,
)
from app.models.agency import Agency
from app.models.agency_entity import AgencyEntity
from app.models.corporate import Corporate

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Outgoing-deal scope ────────────────────────────────────────────────────

class ResolvedScope(BaseModel):
    """The scope block to write onto a Deal, with the party already authorised."""
    scope_type:       DealScopeType
    agency_id:        Optional[int] = None
    corporate_id:     Optional[int] = None
    agency_entity_id: Optional[int] = None
    party_name:       Optional[str] = None
    # What supplier_name should read for this scope. Never blank: it is the
    # repository's "Supplier / Source" column and its search key, and a NULL there
    # collapses the whole Outgoing list to "—".
    supplier_label:   str


def _corporate_display_name(c: Corporate) -> str:
    return (c.company or "").strip() or f"{c.first_name} {c.last_name or ''}".strip()


async def _resolve_scope(
    db: AsyncSession,
    current_user: User,
    direction: DealDirection,
    scope_type: Optional[str],
    agency_id: Optional[int],
    corporate_id: Optional[int],
    agency_entity_id: Optional[int],
    fallback_label: Optional[str] = None,
) -> ResolvedScope:
    """Authorise the named party and return the scope to persist.

    The Pydantic mixin has already checked the SHAPE (that the right id
    accompanies the scope). What it cannot check is OWNERSHIP, which is why this
    exists: a foreign key alone would happily let one user pin a deal to another
    user's agency by guessing an integer. Note the two masters are scoped
    differently — agencies by `user_id` alone, corporates by tenant + creator.

    An inbound deal is forced to ALL rather than rejected: income received from an
    airline has no customer, and inbound clients send no scope at all.
    """
    if direction != DealDirection.OUTBOUND:
        return ResolvedScope(
            scope_type=DealScopeType.ALL,
            supplier_label=(fallback_label or "").strip() or "—",
        )

    st = DealScopeType(scope_type or DealScopeType.ALL.value)

    if st == DealScopeType.AGENCY:
        agency = (await db.execute(
            select(Agency).where(Agency.id == agency_id, Agency.user_id == current_user.id)
        )).scalar_one_or_none()
        if not agency:
            raise HTTPException(status_code=400, detail=f"Agency id {agency_id} not found in your agencies.")

        entity_id = None
        if agency_entity_id is not None:
            entity = (await db.execute(
                select(AgencyEntity).where(
                    AgencyEntity.id == agency_entity_id,
                    AgencyEntity.agency_id == agency.id,
                    AgencyEntity.user_id == current_user.id,
                )
            )).scalar_one_or_none()
            if not entity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Entity id {agency_entity_id} does not belong to agency '{agency.name}'.",
                )
            entity_id = entity.id

        # The agency NAME only. `Deal.supplier_name` is String(255) and so is
        # agencies.name, an exact fit — the full "name — branch · channel" label
        # would overflow. Branch and channel render from agency_id.
        return ResolvedScope(
            scope_type=st, agency_id=agency.id, agency_entity_id=entity_id,
            party_name=agency.name, supplier_label=agency.name,
        )

    if st == DealScopeType.CORPORATE:
        corporate = (await db.execute(
            select(Corporate).where(
                Corporate.id == corporate_id,
                Corporate.tenant_id == current_user.tenant_id,
                Corporate.created_by_id == current_user.id,
            )
        )).scalar_one_or_none()
        if not corporate:
            raise HTTPException(status_code=400, detail=f"Corporate id {corporate_id} not found in your corporates.")
        name = _corporate_display_name(corporate)
        return ResolvedScope(
            scope_type=st, corporate_id=corporate.id,
            party_name=name, supplier_label=name,
        )

    # The only remaining party-less scope.
    return ResolvedScope(
        scope_type=DealScopeType.ALL,
        party_name="All Customers", supplier_label="All Customers",
    )


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

    The whole document is read. Rows are enumerated deterministically from the
    PDF's table structure and sent to the model in chunks, so sheet size is not
    a limit — there is deliberately no max-deals cap.
    """
    max_mb = 50
    chunk = await file.read(max_mb * 1024 * 1024 + 1)
    if len(chunk) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB limit")
    import io as _io
    file.file = _io.BytesIO(chunk)  # type: ignore[assignment]
    await file.seek(0)

    result = await AIDealExtractionService.extract(file)
    if result.get("unreadable"):
        # Better an honest refusal than a wrong-but-plausible layout — the
        # column-mapping path handles anything this parser can't.
        raise HTTPException(
            status_code=422,
            detail="This PDF's table structure could not be read. "
                   "Turn off AI Extraction and use column mapping instead.",
        )
    deals = [AIDeal(**d) for d in result.get("deals", [])]

    # ── Airline-master resolution — READ ONLY ────────────────────────────────
    # Nothing is written here on purpose: a previewed-then-cancelled upload must
    # leave the master untouched. Missing airlines are created in
    # /upload/confirm, which is also the only place that sees the reviewer's
    # edits. The status fields are advisory for the UI; confirm re-resolves from
    # scratch and never trusts them.
    index = await AirlineIndex.load(db)
    resolutions: dict[tuple[str | None, str | None], AirlineMatch] = {}
    splits: dict[tuple[str | None, str | None], list[AirlineMatch]] = {}

    def _apply(deal: AIDeal, match: AirlineMatch) -> AIDeal:
        deal.airline_status = match.status
        deal.airline_master_name = match.canonical_name
        deal.airline_note = match.note
        deal.airline_code = match.code or deal.airline_code
        # `saved_name` is the master's canonical name ONLY when the row resolved;
        # for conflict / new / unresolved it is the sheet's own wording with just
        # the channel qualifier removed. Assigning it unconditionally is what
        # keeps this identical to what confirm_upload will write — the two must
        # never disagree, or the review table shows one name and the save stores
        # another.
        deal.airline_name = match.saved_name or deal.airline_name
        return deal

    # (source row, carrier, class) — a split row must sit with its own carrier,
    # not interleaved by class across all three.
    _CLASS_RANK = {"Economy": 0, "Premium": 1, "Business": 2}
    ordered: list[tuple[tuple[int, int, int], AIDeal]] = []

    for deal in deals:
        key = (deal.airline_name, deal.airline_code)
        match = resolutions.get(key)
        if match is None:
            # One sheet yields ~345 deal objects but only ~110 distinct pairs —
            # Air India's 10 source rows x 3 classes collapse to about 2.
            match = resolutions[key] = index.resolve(*key)
        rank = _CLASS_RANK.get((deal.incentive_data.get("PLB") or {}).get("class"), 9)

        # A row quoting one rate for several carriers is several deals.
        # "AirFrance / KLM / Delta" x Economy/Premium/Business is nine, and the
        # split has to happen here rather than in the extraction service, which
        # has no database and so cannot tell a carrier list from a trade name.
        #
        # Attempted for every status except RESOLVED, not just MULTI_CARRIER: the
        # sheet that transposes the columns ("AF/KL (NDC)" in the name cell,
        # "AirFrance / KLM" in the code cell) leaves no usable code, so it lands
        # in UNRESOLVED while still naming two carriers. `split_carriers` refuses
        # anything it cannot account for in full, so widening the trigger cannot
        # invent a split — a single-carrier row has one fragment and is rejected.
        if match.status != RESOLVED:
            carriers = splits.get(key)
            if carriers is None:
                carriers = splits[key] = index.split_carriers(*key)
            if len(carriers) >= 2:
                for ix, carrier in enumerate(carriers):
                    ordered.append(((deal.src_n or 0, ix, rank),
                                    _apply(deal.model_copy(deep=True), carrier)))
                continue

        ordered.append(((deal.src_n or 0, 0, rank), _apply(deal, match)))

    ordered.sort(key=lambda pair: pair[0])
    deals = [deal for _, deal in ordered]

    # Counted over distinct airlines rather than rows, and after the split, so a
    # carrier list reads as the carriers it became.
    airline_summary: dict[str, int] = {}
    for key, match in resolutions.items():
        for m in (splits.get(key) or [match]):
            airline_summary[m.status] = airline_summary.get(m.status, 0) + 1

    # Apply Contract Valid To fallback when AI didn't extract the date.
    # Reads contract_year off the index already loaded above; before the names
    # were resolved this lookup could never match, because every name still
    # carried its "(XO SALE)" qualifier.
    if valid_from and deals:
        vf_date: date | None = None
        try:
            vf_date = date.fromisoformat(valid_from)
        except ValueError:
            pass

        if vf_date:
            for deal in deals:
                cy = index.contract_year_for(deal.airline_name)
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
        airline_summary=airline_summary,
    )


@router.post("/upload/ai-confirm", response_model=UploadConfirmResult, status_code=status.HTTP_201_CREATED)
async def ai_confirm_deals(
    payload: AIConfirmPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk-create unified Deal records from AI-extracted deals.
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

    statement = DealStatement(
        tenant_id=current_user.tenant_id,
        source_type=DealSourceType.UPLOAD,
        deal_type=DealKind.AIRLINE,
        deal_tag=DealTagType(payload.deal_tag or "standard"),
        file_name=payload.file_name or None,
        file_type=payload.file_type or "pdf",
        batch_id=batch_id,
        supplier_name=payload.supplier_name or None,
        created_by_id=current_user.id,
    )
    db.add(statement)
    await db.flush()

    created_ids: list[int] = []
    for ai_deal in payload.deals:
        vf = date.fromisoformat(ai_deal.contract_valid_from) if ai_deal.contract_valid_from else None
        vt = date.fromisoformat(ai_deal.contract_valid_to) if ai_deal.contract_valid_to else None

        deal = UnifiedDeal(
            statement_id=statement.id,
            tenant_id=current_user.tenant_id,
            deal_type=DealKind.AIRLINE,
            source_agent="ai_extraction",
            airline_type=ai_deal.airline_type or None,
            airline_name=ai_deal.airline_name or None,
            valid_from=vf,
            valid_to=vt,
            remark=ai_deal.remark or None,
            status=DealStatusType.PENDING_APPROVAL,
            deal_lifecycle_status=DealLifecycleType.DRAFT,
            created_by_id=current_user.id,
        )
        db.add(deal)
        await db.flush()

        await _attach_unified_deal_relations(
            deal_id=deal.id,
            incentive_types=ai_deal.incentive_types or [],
            incentive_data=ai_deal.incentive_data or {},
            incl_excl_types=[],
            incl_excl_data={},
            vice_versa={},
            db=db,
        )
        await _seed_approval_unified(deal, current_user, db)
        created_ids.append(deal.id)

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


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED DEAL HELPERS — write to new normalized tables
# ══════════════════════════════════════════════════════════════════════════════

_RULE_CAT_MAP = {
    "Inclusion For Trigger": "trigger_inclusion",
    "Exclusion For Trigger": "trigger_exclusion",
    "Inclusion For Payout":  "payout_inclusion",
    "Exclusion For Payout":  "payout_exclusion",
}

_SLAB_META_KEYS = frozenset({
    "quarterlyFreq", "halfYearlyFreq",
    "validFrom", "validTo",
    "baseTargetNumPct", "baseTargetAmtNumPct", "baseTargetAmount",
    "targetFrom", "targetTo",
    "segment", "class", "slabClass",
})


_REVERSE_RULE_CAT = {v: k for k, v in _RULE_CAT_MAP.items()}


def _resolve_rule_payload(incl_excl_data: dict, vice_versa: dict, rule_type: str, inc_type: str) -> tuple[dict, bool]:
    """Resolve a rule's condition fields + vice_versa flag for one incentive type.

    Supports both the legacy flat shape (one shared field-set per rule_type,
    used by upload routes) and the per-incentive-type nested shape sent by the
    manual create form (incl_excl_data[rule_type][inc_type] = {field: value}).
    """
    raw = incl_excl_data.get(rule_type) or {}
    if raw and all(isinstance(v, dict) for v in raw.values()):
        fields = raw.get(inc_type) or {}
    else:
        fields = raw

    vv_raw = vice_versa.get(rule_type)
    vv = bool(vv_raw.get(inc_type, False)) if isinstance(vv_raw, dict) else bool(vv_raw or False)
    return fields, vv


def _build_inc_data_from_configs(
    incentives: list,
) -> tuple[list[str], dict]:
    """Reconstruct (incentive_types, incentive_data) from DealIncentiveConfig rows.
    Includes slab rows and slab values so the frontend can render slab tables.
    """
    inc_types = [i.incentive_type for i in sorted(incentives, key=lambda x: x.incentive_order)]
    inc_data: dict = {}
    for inc in incentives:
        d: dict = {k: v for k, v in {
            "validFrom":             inc.contract_valid_from.isoformat() if inc.contract_valid_from else None,
            "validTo":               inc.contract_valid_to.isoformat() if inc.contract_valid_to else None,
            "travelValidFrom":       inc.travel_valid_from.isoformat() if inc.travel_valid_from else None,
            "travelValidTo":         inc.travel_valid_to.isoformat() if inc.travel_valid_to else None,
            "frequency":             inc.frequency,
            "flightType":            inc.flight_type,
            "class":                 inc.class_,
            "routeType":             inc.route_type,
            "triggerBased":          inc.trigger_based,
            "targetBased":           inc.target_based,
            "targetCalcCols":        inc.target_calc_cols,
            "payoutCalcCols":        inc.payout_calc_cols,
            "amountBasedType":       inc.amount_based_type,
            "baseTargetAmount":      str(inc.base_target_amount) if inc.base_target_amount is not None else None,
            "incentiveNumPct":       inc.incentive_num_pct,
            "incentiveAmtPct":       str(inc.incentive_amt_pct) if inc.incentive_amt_pct is not None else None,
            "cappedIncentive":       str(inc.capped_incentive) if inc.capped_incentive is not None else None,
            "cappedIncentiveAmount": str(inc.capped_incentive_amount) if inc.capped_incentive_amount is not None else None,
            "marketFundType":        inc.market_fund_type,
            "exchangeRate":          str(inc.exchange_rate) if inc.exchange_rate is not None else None,
            "cashbackTargetType":    inc.cashback_target_type,
            "diType":                inc.di_type,
            "ancillaryItems":        inc.ancillary_items,
        }.items() if v is not None}

        # Append slab rows (populated when slabs relationship is eager-loaded)
        slabs = getattr(inc, "slabs", None) or []
        if slabs:
            slab_list = []
            for slab in sorted(slabs, key=lambda s: s.slab_order):
                slab_d: dict = {k: v for k, v in {
                    "slabType":           slab.slab_type.value if hasattr(slab.slab_type, "value") else str(slab.slab_type),
                    "slabOrder":          slab.slab_order,
                    "quarterlyFreq":      slab.quarterly_freq,
                    "halfYearlyFreq":     slab.half_yearly_freq,
                    "validFrom":          slab.valid_from.isoformat() if slab.valid_from else None,
                    "validTo":            slab.valid_to.isoformat() if slab.valid_to else None,
                    "baseTargetAmtNumPct": slab.base_target_amt_num_pct,
                    "baseTargetAmount":   str(slab.base_target_amount) if slab.base_target_amount is not None else None,
                    "targetFrom":         slab.target_from.isoformat() if slab.target_from else None,
                    "targetTo":           slab.target_to.isoformat() if slab.target_to else None,
                    "segment":            slab.segment,
                    "class":              slab.class_,
                }.items() if v is not None}
                values: dict = {}
                for sv in (getattr(slab, "values", None) or []):
                    values[sv.value_key] = float(sv.value) if sv.value is not None else None
                if values:
                    slab_d["values"] = values
                slab_list.append(slab_d)
            d["slabs"] = slab_list

        inc_data[inc.incentive_type] = d
    return inc_types, inc_data


def _build_ie_from_rules(rules: list) -> tuple[list[str], dict, dict]:
    """Reconstruct (incl_excl_types, incl_excl_data, vice_versa) from DealRule rows."""
    ie_types: list[str] = []
    ie_data:  dict = {}
    ie_vv:    dict = {}
    for rule in sorted(rules, key=lambda x: x.rule_order):
        rt = _REVERSE_RULE_CAT.get(rule.rule_category, rule.rule_category)
        ie_types.append(rt)
        ie_vv[rt] = rule.vice_versa
        conds: dict = {}
        for cond in sorted(rule.conditions, key=lambda x: x.condition_order):
            if cond.operator in ("in", "not_in"):
                conds[cond.condition_field] = cond.value_list or []
            elif cond.operator == "between":
                conds[cond.condition_field + "From"] = cond.value_from
                conds[cond.condition_field + "To"]   = cond.value_to
            else:
                conds[cond.condition_field] = cond.value_text
        ie_data[rt] = conds
    return ie_types, ie_data, ie_vv


def _sd(s) -> "date | None":
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _sn(v) -> "float | None":
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# Ancillary sub-types: (parent flat key, num/pct flat key, amount flat key, label).
# Mirrors ANCILLARY_ITEMS in the frontend's IncentiveInclExclShared.tsx.
_ANCILLARY_FLAT = [
    ("baggageType",  "baggageNumPct",  "baggageAmt",   "Baggage Type"),
    ("meals",        "mealsNumPct",    "mealsAmt",     "Meals"),
    ("seatFees",     "seatFeesNumPct", "seatFeesAmt",  "Seat Fees"),
    ("transport",    "transportNumPct","transportAmt", "Transport"),
    ("groupBooking", "groupNumPct",    "groupAmt",     "Group Booking Fee"),
    ("loungeAccess", "loungeNumPct",   "loungeAmt",    "Lounge Access"),
    ("cabFacility",  "cabNumPct",      "cabAmt",       "Cab Facility"),
]


def _ancillary_from_flat(d: dict) -> dict | None:
    """Assemble the ancillary_items JSON blob from the flat baggage*/meals*/… keys
    that the manual create form and the multi-tab upload both send. Returns None when
    no ancillary sub-type was filled, so deals without ancillary stay untouched."""
    out: dict = {}
    for parent, numpct, amt, label in _ANCILLARY_FLAT:
        with_type = d.get(parent)
        num_pct   = d.get(numpct)
        amount    = d.get(amt)
        if with_type or num_pct or amount:
            out[label] = {
                "withType": with_type or None,
                "numPct":   num_pct or None,
                "amount":   _sn(amount),
            }
    return out or None


def _build_inc_config(deal_id: int, inc_type: str, d: dict, order: int) -> DealIncentiveConfig:
    return DealIncentiveConfig(
        deal_id=deal_id,
        incentive_type=inc_type,
        incentive_order=order,
        contract_valid_from=_sd(d.get("validFrom")),
        contract_valid_to=_sd(d.get("validTo")),
        travel_valid_from=_sd(d.get("travelValidFrom")),
        travel_valid_to=_sd(d.get("travelValidTo")),
        frequency=d.get("frequency") or None,
        flight_type=d.get("flightType") or None,
        class_=d.get("class") or None,
        route_type=d.get("routeType") or None,
        trigger_based=d.get("triggerBased") or None,
        target_based=d.get("targetBased") or None,
        target_calc_cols=d.get("targetCalcCols") or None,
        payout_calc_cols=d.get("payoutCalcCols") or None,
        amount_based_type=d.get("amountBasedType") or None,
        base_target_amount=_sn(d.get("baseTargetAmount")),
        incentive_num_pct=d.get("incentiveNumPct") or None,
        incentive_amt_pct=_sn(d.get("incentiveAmtPct")),
        capped_incentive=_sn(d.get("cappedIncentive")),
        capped_incentive_amount=_sn(d.get("cappedIncentiveAmount")),
        market_fund_type=d.get("marketFundType") or None,
        exchange_rate=_sn(d.get("exchangeRate")),
        cashback_period_from=_sd(d.get("periodFrom")),
        cashback_period_to=_sd(d.get("periodTo")),
        cashback_target_type=d.get("cashbackTargetType") or None,
        cashback_target_value=_sn(d.get("cashbackTargetValue")),
        di_type=d.get("diType") or None,
        di_currency=(
            d.get("diCurrencySingle")
            or d.get("diCurrencyTranche")
            or d.get("diCurrencyBank")
            or d.get("diCurrencyCard")
        ) or None,
        bulk_deposit_type=d.get("bulkDepositType") or None,
        bulk_single_num_pct=_sn(d.get("bulkSingleNumPct")),
        bulk_single_amt=_sn(d.get("bulkSingleAmt")),
        bulk_single_capped=_sn(d.get("bulkSingleCapped")),
        bulk_tranches=d.get("bulkTranches") or None,
        normal_deposit_type=d.get("normalDepositType") or None,
        bank_transfer_num_pct=_sn(d.get("bankTransferNumPct")),
        bank_transfer_amt=_sn(d.get("bankTransferAmt")),
        credit_card_type=d.get("creditCardType") or None,
        bank_name=d.get("bankName") or None,
        credit_card_num_pct=_sn(d.get("creditCardNumPct")),
        credit_card_amt=_sn(d.get("creditCardAmt")),
        ancillary_items=d.get("ancillaryItems") or _ancillary_from_flat(d),
    )


def _parse_slab_list(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return raw if isinstance(raw, list) else []


async def _add_slabs_for_inc(incentive_id: int, d: dict, db: AsyncSession) -> None:
    """Create DealIncentiveSlab + DealIncentiveSlabValue rows for one incentive config.

    Reads the form-shaped slab keys (amountSlabs / segmentSlabs / siSlabs). Use
    _normalize_inc_entry_slabs first when feeding repository-shaped data (which
    carries a single ``slabs`` array instead).
    """
    for slab_key, slab_type_val in [
        ("amountSlabs", SlabTypeEnum.AMOUNT),
        ("segmentSlabs", SlabTypeEnum.SEGMENT),
        ("siSlabs", SlabTypeEnum.SI),
    ]:
        for slab_order, row in enumerate(_parse_slab_list(d.get(slab_key))):
            slab = DealIncentiveSlab(
                incentive_id=incentive_id,
                slab_type=slab_type_val,
                slab_order=slab_order,
                quarterly_freq=row.get("quarterlyFreq") or None,
                half_yearly_freq=row.get("halfYearlyFreq") or None,
                valid_from=_sd(row.get("validFrom")),
                valid_to=_sd(row.get("validTo")),
                base_target_amt_num_pct=row.get("baseTargetNumPct") or row.get("baseTargetAmtNumPct") or None,
                base_target_amount=_sn(row.get("baseTargetAmount")),
                target_from=_sd(row.get("targetFrom")),
                target_to=_sd(row.get("targetTo")),
                segment=row.get("segment") or None,
                class_=row.get("class") or row.get("slabClass") or None,
            )
            db.add(slab)
            await db.flush()

            for key, val in row.items():
                if key in _SLAB_META_KEYS:
                    continue
                fval = _sn(val)
                if fval is None:
                    continue
                db.add(DealIncentiveSlabValue(
                    slab_id=slab.id,
                    value_key=key,
                    value_type=SlabValueTypeEnum.NUMBER,
                    value=fval,
                ))


async def _add_conditions(rule_id: int, fields: dict, db: AsyncSession) -> None:
    """Create DealRuleCondition rows for one rule. Skips empty values."""
    cond_order = 0
    for field, val in fields.items():
        if val is None or val == "" or val == []:
            continue
        if isinstance(val, list):
            operator, kw = RuleOperatorEnum.IN, {"value_list": val}
        elif isinstance(val, bool):
            operator, kw = RuleOperatorEnum.EQUALS, {"value_text": str(val).lower()}
        else:
            operator, kw = RuleOperatorEnum.EQUALS, {"value_text": str(val)}
        db.add(DealRuleCondition(
            rule_id=rule_id,
            condition_field=field,
            operator=operator,
            condition_order=cond_order,
            **kw,
        ))
        cond_order += 1


async def _attach_unified_deal_relations(
    deal_id: int,
    incentive_types: list[str],
    incentive_data: dict,
    incl_excl_types: list[str],
    incl_excl_data: dict,
    vice_versa: dict,
    db: AsyncSession,
) -> None:
    """Create DealIncentiveConfig + slabs + slab_values + rules + conditions for a unified deal."""
    for order, inc_type in enumerate(incentive_types):
        d = incentive_data.get(inc_type) or {}

        inc_obj = _build_inc_config(deal_id, inc_type, d, order)
        db.add(inc_obj)
        await db.flush()

        await _add_slabs_for_inc(inc_obj.id, d, db)

        for rule_order, rule_type in enumerate(incl_excl_types):
            category = _RULE_CAT_MAP.get(rule_type, rule_type.lower().replace(" ", "_"))
            fields, rule_vv = _resolve_rule_payload(incl_excl_data, vice_versa, rule_type, inc_type)
            # A rule with no conditions constrains nothing — build_rule_dict returns {} and
            # every consumer skips it. Writing the empty container anyway produced 4 rows per
            # incentive of pure noise. Matches _rebuild_unified_relations, which already
            # skips them, so create and edit finally agree.
            if not fields and not rule_vv:
                continue
            rule = DealRule(
                incentive_id=inc_obj.id,
                rule_category=category,
                vice_versa=rule_vv,
                rule_order=rule_order,
            )
            db.add(rule)
            await db.flush()
            await _add_conditions(rule.id, fields, db)


def _normalize_inc_entry_slabs(entry: dict) -> dict:
    """Convert a repository-shaped incentive entry (one ``slabs`` array of
    {slabType, ...values}) into the form-shaped amountSlabs / segmentSlabs /
    siSlabs lists that _add_slabs_for_inc consumes.

    Form-shaped entries (which already carry amountSlabs/segmentSlabs/siSlabs)
    pass through unchanged. This lets the repository round-trip its own output
    on edit, even when only one incentive in a deal was modified.
    """
    slabs = entry.get("slabs")
    if not slabs:
        return entry
    e = dict(entry)
    grouped: dict[str, list] = {"amount": [], "segment": [], "si": []}
    for s in slabs:
        st = (s.get("slabType") or "amount").lower()
        row = {k: v for k, v in s.items() if k not in ("slabType", "slabOrder", "values")}
        for vk, vv in (s.get("values") or {}).items():
            row[vk] = vv
        grouped.get(st, grouped["amount"]).append(row)
    if grouped["amount"] and not e.get("amountSlabs"):
        e["amountSlabs"] = grouped["amount"]
    if grouped["segment"] and not e.get("segmentSlabs"):
        e["segmentSlabs"] = grouped["segment"]
    if grouped["si"] and not e.get("siSlabs"):
        e["siSlabs"] = grouped["si"]
    e.pop("slabs", None)
    return e


async def _rebuild_unified_relations(
    deal_id: int,
    incentive_types: list[str],
    incentive_data: dict,
    incl_excl_data: dict,
    db: AsyncSession,
) -> None:
    """Recreate all incentive/slab/rule rows for a unified deal from repository-
    shaped data (what GET /repository returns and the edit popups send back).

    incentive_data: {inc_type: {fields..., slabs:[...] | amountSlabs:[...]}}
    incl_excl_data: {inc_type: {rule_type: {field: value}}}  (per-incentive), or
                    {rule_type: {field: value}}  (flat — applied to every incentive)

    Caller is responsible for deleting the deal's existing incentives first.
    Only rule types that carry at least one non-empty condition produce a rule,
    so cleared rule types disappear from the Incl/Excl column.
    """
    # incl_excl_data may arrive in two shapes:
    #   rule-major (create form / GET .../form): {rule_type: {inc_type: fields}} or
    #                                             {rule_type: fields}  (flat, all incentives)
    #   inc-major  (IncentiveRulesModal):         {inc_type: {rule_type: fields}}
    rule_major = bool(incl_excl_data) and any(k in _RULE_CAT_MAP for k in incl_excl_data)

    for order, inc_type in enumerate(incentive_types):
        d = _normalize_inc_entry_slabs(incentive_data.get(inc_type) or {})

        inc_obj = _build_inc_config(deal_id, inc_type, d, order)
        db.add(inc_obj)
        await db.flush()

        await _add_slabs_for_inc(inc_obj.id, d, db)

        # Resolve this incentive's {rule_type: fields} regardless of the arriving shape.
        if rule_major:
            inc_rules = {}
            for rule_type in incl_excl_data:
                fields_raw, _vv = _resolve_rule_payload(incl_excl_data, {}, rule_type, inc_type)
                if fields_raw:
                    inc_rules[rule_type] = fields_raw
        else:
            inc_rules = incl_excl_data.get(inc_type) or {}
        rule_order = 0
        for rule_type, conds in inc_rules.items():
            fields = {k: v for k, v in (conds or {}).items() if v not in (None, "", [])}
            if not fields:
                continue
            category = _RULE_CAT_MAP.get(rule_type, rule_type.lower().replace(" ", "_"))
            rule = DealRule(
                incentive_id=inc_obj.id,
                rule_category=category,
                vice_versa=False,
                rule_order=rule_order,
            )
            db.add(rule)
            await db.flush()
            await _add_conditions(rule.id, fields, db)
            rule_order += 1


def _unified_deal_to_repo_item(d: UnifiedDeal) -> DealRepositoryItem:
    """Serialize a unified Deal (with incentives/slabs/rules eager-loaded) into a
    DealRepositoryItem. Shared by the repository list and the update endpoint so
    both always reconstruct the normalized incentive/incl-excl data identically.
    """
    inc_types, inc_data = _build_inc_data_from_configs(d.incentives)
    # Build per-incentive incl/excl: {inc_type: {rule_type: conditions}}
    all_ie_types: list[str] = []
    all_ie_data: dict = {}
    for inc in (d.incentives or []):
        if getattr(inc, "rules", None):
            _types, _data, _ = _build_ie_from_rules(inc.rules)
            if _types:
                all_ie_data[inc.incentive_type] = _data
                for rt in _types:
                    if rt not in all_ie_types:
                        all_ie_types.append(rt)
    is_b2b = d.deal_type == DealKind.B2B
    prefix = "B2B" if is_b2b else "AIR"
    return DealRepositoryItem(
        id=d.id,
        deal_no=f"{prefix}-{d.id:06d}",
        deal_type="unified",
        source_agent=d.source_agent,
        airline_type=d.airline_type,
        airline_name=d.airline_name,
        contract_year=d.contract_year,
        valid_from=d.valid_from,
        valid_to=d.valid_to,
        trigger_type=d.trigger_type,
        payout_type=d.payout_type,
        business_type=d.business_type,
        entity=d.entity,
        entity_lcc=d.entity_lcc,
        login_id=d.login_id,
        login_ids=d.login_ids,
        remark=d.remark,
        deal_maker_name=d.deal_maker_name,
        incentive_types=inc_types,
        incentive_data=inc_data,
        incl_excl_types=all_ie_types,
        incl_excl_data=all_ie_data,
        deal_tag=d.statement.deal_tag.value if d.statement and hasattr(d.statement.deal_tag, "value") else "standard",
        status=d.status.value if hasattr(d.status, "value") else str(d.status),
        deal_lifecycle_status=d.deal_lifecycle_status.value if hasattr(d.deal_lifecycle_status, "value") else str(d.deal_lifecycle_status or "draft"),
        created_at=d.created_at,
        file_type=None,
        batch_id=d.statement.batch_id if d.statement else None,
        supplier_name=d.supplier_name,
        direction=d.direction.value if hasattr(d.direction, "value") else str(d.direction or "inbound"),
        scope_type=d.scope_type.value if hasattr(d.scope_type, "value") else str(d.scope_type or "all"),
        agency_id=d.agency_id,
        corporate_id=d.corporate_id,
        agency_entity_id=d.agency_entity_id,
        scope_party_name=d.scope_party_name,
    )


async def _seed_approval_unified(
    deal: UnifiedDeal,
    current_user: User,
    db: AsyncSession,
) -> None:
    """Route a unified Deal through the tenant approval workflow."""
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
        deal.status = DealStatusType.APPROVED
        deal.deal_lifecycle_status = DealLifecycleType.ACTIVE
        await _close_matching_unified_deals(deal, db)
        return

    if not workflow.steps:
        raise HTTPException(
            status_code=400,
            detail="Deals approval workflow has no steps configured. Ask Super Admin to add approval steps.",
        )

    deal_approval = DealApproval(
        deal_type="unified",
        deal_id=deal.id,
        unified_deal_id=deal.id,
        workflow_id=workflow.id,
        current_step_order=min(s.step_order for s in workflow.steps),
        status=ApprovalActionStatus.PENDING,
        submitted_by_id=current_user.id,
    )
    db.add(deal_approval)
    await db.flush()

    for s in sorted(workflow.steps, key=lambda x: x.step_order):
        for approver in s.approvers or []:
            db.add(DealApprovalStep(
                deal_approval_id=deal_approval.id,
                step_order=s.step_order,
                role=s.role,
                assigned_user_id=approver.user_id,
                status=ApprovalActionStatus.PENDING,
            ))


async def _close_matching_unified_deals(
    new_deal: UnifiedDeal,
    db: AsyncSession,
) -> None:
    """Close active unified deals that conflict with the newly approved deal."""
    inc_result = await db.execute(
        select(DealIncentiveConfig)
        .where(DealIncentiveConfig.deal_id == new_deal.id)
        .order_by(DealIncentiveConfig.incentive_order)
        .limit(1)
    )
    primary = inc_result.scalar_one_or_none()
    new_flight_type = primary.flight_type if primary else None
    new_class = primary.class_ if primary else None

    result = await db.execute(
        select(UnifiedDeal)
        .options(selectinload(UnifiedDeal.incentives))
        .where(
            UnifiedDeal.tenant_id == new_deal.tenant_id,
            UnifiedDeal.created_by_id == new_deal.created_by_id,
            UnifiedDeal.deal_lifecycle_status == DealLifecycleType.ACTIVE,
            # Never close across directions. An incoming deal (income you earn) and
            # an outgoing one (commission you pay) can name the same airline and the
            # same maker without conflicting — they are different sides of the book.
            UnifiedDeal.direction == new_deal.direction,
            # Never close across SCOPES either. An agency-specific deal and a
            # common one for the same airline are not rivals — they are the two
            # rungs of the priority ladder the commission engine walks down, so
            # closing one when the other is approved destroys the arrangement.
            # Two deals conflict only when they would reach the same party.
            UnifiedDeal.scope_type == new_deal.scope_type,
            UnifiedDeal.agency_id.is_not_distinct_from(new_deal.agency_id),
            UnifiedDeal.corporate_id.is_not_distinct_from(new_deal.corporate_id),
            UnifiedDeal.deal_maker_name == new_deal.deal_maker_name,
            UnifiedDeal.airline_name == new_deal.airline_name,
            UnifiedDeal.airline_type == new_deal.airline_type,
            UnifiedDeal.id != new_deal.id,
            # Never close a deal that came from the SAME upload. A contract
            # legitimately lists one airline several times — Lords carries two
            # Korean Air rows and two Japan Airlines rows at different rates —
            # and without this a proprietary-category workflow has each row
            # close the previous one as it is created, quietly discarding most
            # of the sheet. Harmless for step-based workflows, which never
            # reach this function at all.
            UnifiedDeal.statement_id != new_deal.statement_id,
        )
    )
    for d in result.scalars().all():
        d_primary = d.incentives[0] if d.incentives else None
        if (
            d_primary
            and d_primary.flight_type == new_flight_type
            and d_primary.class_ == new_class
        ):
            d.deal_lifecycle_status = DealLifecycleType.CLOSED


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
    Writes to unified deal_statements → deals → deal_incentives chain.
    """
    vf_deal = date.fromisoformat(payload.valid_from) if payload.valid_from else None
    vt_deal = date.fromisoformat(payload.valid_to)   if payload.valid_to   else None
    source_agent = payload.source_agent or file_name.rsplit(".", 1)[0]

    rows = payload.rows or []
    if not rows:
        rows = [ExtractedRow()]

    # Floated (outbound) deals are always B2B — you can't float a deal back to an airline.
    direction = DealDirection.OUTBOUND if (payload.direction or "").lower() == "outbound" else DealDirection.INBOUND
    use_b2b = bool(payload.business_type) or direction == DealDirection.OUTBOUND
    batch_id = str(uuid.uuid4())

    # WHO this deal is for. Outbound only; inbound is forced to ALL. The label it
    # returns replaces the typed supplier name on an outbound deal, so a Common
    # deal reads "All Agencies" rather than blank.
    scope = await _resolve_scope(
        db, current_user, direction,
        payload.scope_type, payload.agency_id, payload.corporate_id, payload.agency_entity_id,
        fallback_label=supplier_name or payload.source_agent,
    )
    if direction == DealDirection.OUTBOUND:
        supplier_name = scope.supplier_label

    # Keep DealBatch for /batches endpoint backward compat
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

    # One DealStatement per upload session
    statement = DealStatement(
        tenant_id=current_user.tenant_id,
        source_type=DealSourceType.UPLOAD,
        deal_type=DealKind.B2B if use_b2b else DealKind.AIRLINE,
        deal_tag=DealTagType(payload.deal_tag or "standard"),
        direction=direction,
        file_name=file_name or None,
        file_type=file_type or None,
        batch_id=batch_id,
        column_map=payload.column_map or None,
        supplier_name=supplier_name or None,
        created_by_id=current_user.id,
    )
    db.add(statement)
    await db.flush()

    # ── Airline-master resolution / creation ────────────────────────────────
    # Runs once for the whole batch, before the deal loop, so a sheet listing
    # "AI" on ten rows x three classes resolves once and creates one master row.
    #
    # Built from the payload, NOT from anything the extract step cached: if the
    # reviewer retyped the airline name, that edit is what must be resolved.
    #
    # Applies to the column-mapping path too, which fails `deal_matching` the
    # same way; that path has no airline_code field but `deal_extraction`
    # already cleans the sheet's CODE column into `iata_code`, so it is read as
    # a fallback — guarded so a 7-8 digit agency IATA number can never be
    # mistaken for a carrier designator.
    def _airline_key(r) -> tuple[str | None, str | None]:
        name = (r.airline_name or payload.airline_name or "") or None
        code = r.airline_code or carrier_code_from_row_field(r.iata_code)
        return name, code

    airline_pairs = {_airline_key(r) for r in rows}
    airline_matches, _airline_summary = await resolve_and_create_airlines(
        db, airline_pairs, current_user,
    )
    logger.info("deal upload %s airline resolution: %s", batch_id, _airline_summary)

    created_ids: list[int] = []

    for r in rows:
        row_vf = date.fromisoformat(r.valid_from) if r.valid_from else None
        row_vt = date.fromisoformat(r.valid_to)   if r.valid_to   else None
        effective_vf = row_vf or vf_deal
        effective_vt = row_vt or vt_deal

        ie_types = (r.incl_excl_types if r.incl_excl_types else None) or payload.incl_excl_types or []
        ie_data  = (r.incl_excl_data  if r.incl_excl_data  else None) or payload.incl_excl_data  or {}
        ie_vv    = (r.vice_versa      if r.vice_versa       else None) or payload.vice_versa      or {}
        row_inc_data = r.incentive_data if r.incentive_data else (payload.incentive_data or {})

        # Multi-tab workbooks carry per-deal headers on each row; single-sheet / AI /
        # manual paths leave these None and fall back to the deal-level payload.
        deal = UnifiedDeal(
            statement_id=statement.id,
            tenant_id=current_user.tenant_id,
            deal_type=DealKind.B2B if use_b2b else DealKind.AIRLINE,
            direction=direction,
            scope_type=scope.scope_type,
            agency_id=scope.agency_id,
            corporate_id=scope.corporate_id,
            agency_entity_id=scope.agency_entity_id,
            scope_party_name=scope.party_name,
            source_agent=source_agent,
            deal_maker_name=(r.deal_maker_name or payload.deal_maker_name) or None,
            # Outbound ignores any per-row supplier cell: the counterparty is the
            # scope, picked once for the whole upload. Letting a stray sheet column
            # win would name a different party on some rows than on others.
            supplier_name=(
                supplier_name if direction == DealDirection.OUTBOUND
                else ((r.supplier_name or supplier_name) if use_b2b else None)
            ),
            remark=(r.remarks or payload.remark) or None,
            airline_type=(r.airline_type or payload.airline_type) or None,
            # The master's canonical name when the row resolved, the
            # channel-qualifier-stripped name otherwise. Never the raw
            # "Virgin Atlantic (XO SALE)" — that string cannot match a ticket.
            airline_name=(airline_matches[_airline_key(r)].saved_name
                          or r.airline_name or payload.airline_name) or None,
            contract_year=None if use_b2b else (r.contract_year or payload.contract_year or None),
            valid_from=effective_vf,
            valid_to=effective_vt,
            trigger_type=None if use_b2b else (r.trigger_type or payload.trigger_type or None),
            payout_type=None if use_b2b else (r.payout_type or payload.payout_type or None),
            entity=payload.entity or None,
            iata_number=(r.iata_code or payload.iata_number) or None,
            iata_commission=(r.iata_commission or payload.iata_commission) or None,
            business_type=(r.business_type or payload.business_type) or None,
            entity_lcc=(r.entity_lcc or payload.entity_lcc) or None,
            # Row-wins everywhere except outbound, where the login IDs are picked
            # once from the scoped agency's own credentials — a free-text per-row
            # cell must not silently override a real selection.
            login_id=(
                (payload.login_id or r.login_id) if direction == DealDirection.OUTBOUND
                else (r.login_id or payload.login_id)
            ) or None,
            login_ids=payload.login_ids or None,
            status=DealStatusType.PENDING_APPROVAL,
            deal_lifecycle_status=DealLifecycleType.DRAFT,
            created_by_id=current_user.id,
        )
        db.add(deal)
        await db.flush()

        await _attach_unified_deal_relations(
            deal_id=deal.id,
            incentive_types=(r.incentive_types or payload.incentive_types or []),
            incentive_data=row_inc_data,
            incl_excl_types=ie_types,
            incl_excl_data=ie_data,
            vice_versa=ie_vv,
            db=db,
        )
        await _seed_approval_unified(deal, current_user, db)
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
    batch_id = str(uuid.uuid4())

    batch = DealBatch(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        deal_type="airline",
        deal_tag=payload.deal_tag or "standard",
        supplier_name=payload.airline_name or payload.deal_maker_name or None,
        file_name="manual",
        file_type="manual",
        incentive_types=payload.incentive_types or [],
        valid_from=vf,
        valid_to=vt,
        created_by_id=current_user.id,
    )
    db.add(batch)
    await db.flush()

    statement = DealStatement(
        tenant_id=current_user.tenant_id,
        source_type=DealSourceType.MANUAL,
        deal_type=DealKind.AIRLINE,
        deal_tag=DealTagType(payload.deal_tag or "standard"),
        file_type="manual",
        batch_id=batch_id,
        created_by_id=current_user.id,
    )
    db.add(statement)
    await db.flush()

    deal = UnifiedDeal(
        statement_id=statement.id,
        tenant_id=current_user.tenant_id,
        deal_type=DealKind.AIRLINE,
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
        iata_commission=payload.iata_commission or None,
        business_type=payload.business_type or None,
        entity_lcc=payload.entity_lcc or None,
        login_id=payload.login_id or None,
        login_ids=payload.login_ids or None,
        status=DealStatusType.PENDING_APPROVAL,
        deal_lifecycle_status=DealLifecycleType.DRAFT,
        created_by_id=current_user.id,
    )
    db.add(deal)
    await db.flush()

    await _attach_unified_deal_relations(
        deal_id=deal.id,
        incentive_types=payload.incentive_types or [],
        incentive_data=payload.incentive_data or {},
        incl_excl_types=payload.incl_excl_types or [],
        incl_excl_data=payload.incl_excl_data or {},
        vice_versa=payload.vice_versa or {},
        db=db,
    )
    await _seed_approval_unified(deal, current_user, db)
    await db.commit()

    return {
        "id": deal.id,
        "status": deal.status,
        "deal_lifecycle_status": deal.deal_lifecycle_status,
        "deal_tag": payload.deal_tag or "standard",
        "source_agent": deal.source_agent,
        "deal_maker_name": deal.deal_maker_name,
        "remark": deal.remark,
        "airline_type": deal.airline_type,
        "airline_name": deal.airline_name,
        "contract_year": deal.contract_year,
        "valid_from": deal.valid_from,
        "valid_to": deal.valid_to,
        "trigger_type": deal.trigger_type,
        "payout_type": deal.payout_type,
        "entity": deal.entity,
        "iata_number": deal.iata_number,
        "iata_commission": deal.iata_commission,
        "business_type": deal.business_type,
        "entity_lcc": deal.entity_lcc,
        "login_id": deal.login_id,
        "login_ids": deal.login_ids,
        "incentive_types": payload.incentive_types or [],
        "incentive_data": payload.incentive_data or {},
        "incl_excl_types": payload.incl_excl_types or [],
        "incl_excl_data": payload.incl_excl_data or {},
        "vice_versa": payload.vice_versa or {},
        "tenant_id": deal.tenant_id,
        "created_at": deal.created_at,
    }


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
    batch_id = str(uuid.uuid4())
    # inbound = deal received from this supplier; outbound = deal floated to it.
    direction = DealDirection.OUTBOUND if (payload.direction or "").lower() == "outbound" else DealDirection.INBOUND

    # WHO this deal is for. Outbound only; inbound is forced to ALL. On an outbound
    # deal the resolved label replaces the typed supplier name entirely, so a
    # Common deal reads "All Agencies" instead of leaving the repository blank.
    scope = await _resolve_scope(
        db, current_user, direction,
        payload.scope_type, payload.agency_id, payload.corporate_id, payload.agency_entity_id,
        fallback_label=payload.supplier_name,
    )
    supplier_name = (
        scope.supplier_label if direction == DealDirection.OUTBOUND
        else (payload.supplier_name or None)
    )

    batch = DealBatch(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        deal_type="b2b",
        deal_tag=payload.deal_tag or "standard",
        supplier_name=supplier_name,
        file_name="manual",
        file_type="manual",
        incentive_types=payload.incentive_types or [],
        valid_from=vf,
        valid_to=vt,
        created_by_id=current_user.id,
    )
    db.add(batch)
    await db.flush()

    statement = DealStatement(
        tenant_id=current_user.tenant_id,
        source_type=DealSourceType.MANUAL,
        deal_type=DealKind.B2B,
        deal_tag=DealTagType(payload.deal_tag or "standard"),
        direction=direction,
        file_type="manual",
        batch_id=batch_id,
        supplier_name=supplier_name,
        created_by_id=current_user.id,
    )
    db.add(statement)
    await db.flush()

    deal = UnifiedDeal(
        statement_id=statement.id,
        tenant_id=current_user.tenant_id,
        deal_type=DealKind.B2B,
        direction=direction,
        scope_type=scope.scope_type,
        agency_id=scope.agency_id,
        corporate_id=scope.corporate_id,
        agency_entity_id=scope.agency_entity_id,
        scope_party_name=scope.party_name,
        source_agent=payload.source_agent or "manual",
        deal_maker_name=payload.deal_maker_name or None,
        supplier_name=supplier_name,
        remark=payload.remark or None,
        airline_type=payload.airline_type or None,
        airline_name=payload.airline_name or None,
        contract_year=payload.contract_year or None,
        valid_from=vf,
        valid_to=vt,
        entity=payload.entity or None,
        iata_number=payload.iata_number or None,
        iata_commission=payload.iata_commission or None,
        business_type=payload.business_type or None,
        entity_lcc=payload.entity_lcc or None,
        login_id=payload.login_id or None,
        login_ids=payload.login_ids or None,
        status=DealStatusType.PENDING_APPROVAL,
        deal_lifecycle_status=DealLifecycleType.DRAFT,
        created_by_id=current_user.id,
    )
    db.add(deal)
    await db.flush()

    await _attach_unified_deal_relations(
        deal_id=deal.id,
        incentive_types=payload.incentive_types or [],
        incentive_data=payload.incentive_data or {},
        incl_excl_types=payload.incl_excl_types or [],
        incl_excl_data=payload.incl_excl_data or {},
        vice_versa=payload.vice_versa or {},
        db=db,
    )
    await _seed_approval_unified(deal, current_user, db)
    await db.commit()

    return {
        "id": deal.id,
        "status": deal.status,
        "deal_lifecycle_status": deal.deal_lifecycle_status,
        "deal_tag": payload.deal_tag or "standard",
        "direction": deal.direction.value,
        "source_agent": deal.source_agent,
        "deal_maker_name": deal.deal_maker_name,
        "supplier_name": deal.supplier_name,
        "remark": deal.remark,
        "airline_type": deal.airline_type,
        "airline_name": deal.airline_name,
        "contract_year": deal.contract_year,
        "valid_from": deal.valid_from,
        "valid_to": deal.valid_to,
        "entity": deal.entity,
        "iata_number": deal.iata_number,
        "iata_commission": deal.iata_commission,
        "business_type": deal.business_type,
        "entity_lcc": deal.entity_lcc,
        "login_id": deal.login_id,
        "login_ids": deal.login_ids,
        "incentive_types": payload.incentive_types or [],
        "incentive_data": payload.incentive_data or {},
        "incl_excl_types": payload.incl_excl_types or [],
        "incl_excl_data": payload.incl_excl_data or {},
        "vice_versa": payload.vice_versa or {},
        "tenant_id": deal.tenant_id,
        "created_at": deal.created_at,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DEAL REPOSITORY  — unified list from all 3 tables
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/repository", response_model=list[DealRepositoryItem])
async def get_deal_repository(
    batch_id: Optional[str] = Query(None, description="Filter by batch_id"),
    direction: str = Query("inbound", description="'inbound' (received) | 'outbound' (floated) | 'all'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return deals for the tenant from the unified table and legacy tables.

    Defaults to inbound (deals you received) so floated deals never appear in the
    normal repository view. Pass direction=outbound for the floated view, or 'all'.
    Legacy tables predate the direction column and are always inbound.
    """
    direction = (direction or "inbound").lower()
    items: list[DealRepositoryItem] = []

    # 1. Unified deals (new schema — all manual + upload created after migration)
    unified_q = (
        select(UnifiedDeal)
        .options(
            selectinload(UnifiedDeal.statement),
            selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.slabs).selectinload(DealIncentiveSlab.values),
            selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.rules).selectinload(DealRule.conditions),
        )
        .where(
            UnifiedDeal.tenant_id == current_user.tenant_id,
            UnifiedDeal.created_by_id == current_user.id,
        )
    )
    if direction != "all":
        unified_q = unified_q.where(UnifiedDeal.direction == direction)
    if batch_id:
        unified_q = unified_q.join(DealStatement, DealStatement.id == UnifiedDeal.statement_id).where(
            DealStatement.batch_id == batch_id
        )
    unified_result = await db.execute(unified_q)
    for d in unified_result.scalars().all():
        items.append(_unified_deal_to_repo_item(d))

    # Outbound (floated) deals live only in the unified table — legacy tables are all
    # inbound, so skip them entirely for the floated view.
    if direction == "outbound":
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items

    items.sort(key=lambda x: x.created_at, reverse=True)
    return items


@router.get("/repository/{deal_id}/form")
async def get_deal_form(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full form-shaped payload for one unified deal, for pre-filling the Create Deal
    page in edit mode. Reconstructs incentive_data (with slab rows), transposes the
    per-incentive incl/excl rules into the create-form shape {rule_type: {inc_type:
    fields}} (+ matching vice_versa), and returns every header field the form holds.
    """
    q = (
        select(UnifiedDeal)
        .options(
            selectinload(UnifiedDeal.statement),
            selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.slabs).selectinload(DealIncentiveSlab.values),
            selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.rules).selectinload(DealRule.conditions),
        )
        .where(
            UnifiedDeal.id == deal_id,
            UnifiedDeal.tenant_id == current_user.tenant_id,
            UnifiedDeal.created_by_id == current_user.id,
        )
    )
    deal = (await db.execute(q)).scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    inc_types, inc_data = _build_inc_data_from_configs(deal.incentives)

    # Transpose {inc: {rule: fields}} → create-form {rule: {inc: fields}}; same for VV.
    ie_types: list[str] = []
    ie_data: dict = {}
    vice_versa: dict = {}
    for inc in (deal.incentives or []):
        if not getattr(inc, "rules", None):
            continue
        types, data, vv = _build_ie_from_rules(inc.rules)
        for rt in types:
            if rt not in ie_types:
                ie_types.append(rt)
            ie_data.setdefault(rt, {})[inc.incentive_type] = data.get(rt, {})
            vice_versa.setdefault(rt, {})[inc.incentive_type] = bool(vv.get(rt, False))

    stmt = deal.statement
    return {
        "id": deal.id,
        "deal_type": deal.deal_type.value if hasattr(deal.deal_type, "value") else str(deal.deal_type),
        "deal_tag": stmt.deal_tag.value if stmt and hasattr(stmt.deal_tag, "value") else "standard",
        # Read-only for the edit form: it decides which repository's form to render
        # (Incoming vs Outgoing). Without it the form defaulted to "inbound" and an
        # edited outgoing deal came back wearing the incoming form. Deliberately NOT
        # accepted on DealUpdatePayload — a PATCH must never move a deal between the
        # two repositories.
        "direction": deal.direction.value if hasattr(deal.direction, "value") else str(deal.direction or "inbound"),
        # Outgoing-deal scope, so the edit form re-opens on the right branch with
        # the right party already selected.
        "scope_type": deal.scope_type.value if hasattr(deal.scope_type, "value") else str(deal.scope_type or "all"),
        "agency_id": deal.agency_id,
        "corporate_id": deal.corporate_id,
        "agency_entity_id": deal.agency_entity_id,
        "scope_party_name": deal.scope_party_name,
        "airline_type": deal.airline_type,
        "airline_name": deal.airline_name,
        "valid_from": deal.valid_from.isoformat() if deal.valid_from else None,
        "valid_to": deal.valid_to.isoformat() if deal.valid_to else None,
        "contract_year": deal.contract_year,
        "trigger_type": deal.trigger_type,
        "payout_type": deal.payout_type,
        "business_type": deal.business_type,
        "entity": deal.entity,
        "entity_lcc": deal.entity_lcc,
        "login_id": deal.login_id,
        "login_ids": deal.login_ids or [],
        "iata_number": deal.iata_number,
        "iata_commission": deal.iata_commission,
        "supplier_name": deal.supplier_name,
        "remark": deal.remark,
        "deal_maker_name": deal.deal_maker_name,
        "incentive_types": inc_types,
        "incentive_data": inc_data,
        "incl_excl_types": ie_types,
        "incl_excl_data": ie_data,
        "vice_versa": vice_versa,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DEAL BATCHES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/batches", response_model=list[DealBatchRead])
async def list_deal_batches(
    direction: str = Query("inbound", description="'inbound' (received) | 'outbound' (floated) | 'all'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List deal upload batches for the tenant, with deal count per batch.

    Defaults to inbound so floated batches don't appear in the normal view. A batch's
    direction is taken from its DealStatement; pass direction=outbound or 'all'.
    """
    direction = (direction or "inbound").lower()
    from app.models.user import User as UserModel
    batches_result = await db.execute(
        select(DealBatch)
        .where(
            DealBatch.tenant_id == current_user.tenant_id,
            DealBatch.created_by_id == current_user.id,
        )
        .order_by(DealBatch.created_at.desc())
    )
    batches = batches_result.scalars().all()

    # Restrict to batches whose statement matches the requested direction.
    if direction != "all":
        dir_result = await db.execute(
            select(DealStatement.batch_id).where(
                DealStatement.tenant_id == current_user.tenant_id,
                DealStatement.created_by_id == current_user.id,
                DealStatement.batch_id.isnot(None),
                DealStatement.direction == DealDirection(direction),
            )
        )
        allowed = {bid for (bid,) in dir_result.all()}
        batches = [b for b in batches if b.batch_id in allowed]

    unified_counts_result = await db.execute(
        select(DealStatement.batch_id, func.count(UnifiedDeal.id))
        .join(UnifiedDeal, UnifiedDeal.statement_id == DealStatement.id)
        .where(DealStatement.tenant_id == current_user.tenant_id, DealStatement.created_by_id == current_user.id, DealStatement.batch_id.isnot(None))
        .group_by(DealStatement.batch_id)
    )
    deal_counts: dict[str, int] = {}
    for bid, cnt in unified_counts_result.all():
        deal_counts[bid] = deal_counts.get(bid, 0) + cnt

    unified_lc_result = await db.execute(
        select(DealStatement.batch_id, UnifiedDeal.deal_lifecycle_status, func.count(UnifiedDeal.id))
        .join(UnifiedDeal, UnifiedDeal.statement_id == DealStatement.id)
        .where(DealStatement.tenant_id == current_user.tenant_id, DealStatement.created_by_id == current_user.id, DealStatement.batch_id.isnot(None))
        .group_by(DealStatement.batch_id, UnifiedDeal.deal_lifecycle_status)
    )
    lifecycle_counts: dict[str, dict[str, int]] = {}
    for bid, status, cnt in unified_lc_result.all():
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
            file_url=b.file_url,
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
            DealBatch.created_by_id == current_user.id,
        )
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    unified_cnt = await db.execute(
        select(func.count(UnifiedDeal.id))
        .join(DealStatement, DealStatement.id == UnifiedDeal.statement_id)
        .where(DealStatement.batch_id == batch_id, DealStatement.tenant_id == current_user.tenant_id, DealStatement.created_by_id == current_user.id)
    )
    deal_count = unified_cnt.scalar() or 0

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
        file_url=batch.file_url,
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
    result = await db.execute(
        select(UnifiedDeal).where(
            UnifiedDeal.id == deal_id,
            UnifiedDeal.tenant_id == current_user.tenant_id,
            UnifiedDeal.created_by_id == current_user.id,
        )
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    created_by_id = deal.created_by_id
    created_at = deal.created_at
    source_type_str = "manual"
    status_str = deal.status.value if hasattr(deal.status, "value") else str(deal.status)

    # Find the DealApproval using the (deal_type, deal_id) key
    approval_result = await db.execute(
        select(DealApproval)
        .options(selectinload(DealApproval.steps))
        .where(DealApproval.deal_type == "unified", DealApproval.deal_id == deal_id)
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
    """Update any deal in the repository. All deals live in the unified schema."""
    return await _update_unified_deal(deal_id, payload, current_user, db)


async def _update_unified_deal(
    deal_id: int,
    payload: DealUpdatePayload,
    current_user: User,
    db: AsyncSession,
) -> DealRepositoryItem:
    """Update a unified Deal: header fields are set directly; incentive_data /
    incl_excl_data (when present) rebuild the normalized child tables.

    The response always re-serializes the freshly-loaded deal via
    _unified_deal_to_repo_item, so the Incentive Types / Incl-Excl columns keep
    their values after a header-only edit and reflect edits after a popup save —
    fixing the bug where those columns went blank on save.
    """
    eager = (
        selectinload(UnifiedDeal.statement),
        selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.slabs).selectinload(DealIncentiveSlab.values),
        selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.rules).selectinload(DealRule.conditions),
    )
    result = await db.execute(
        select(UnifiedDeal).options(*eager).where(
            UnifiedDeal.id == deal_id,
            UnifiedDeal.tenant_id == current_user.tenant_id,
            UnifiedDeal.created_by_id == current_user.id,
        )
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    # 1. Header fields — everything except the normalized incentive/incl-excl keys
    #    and the scope block, which needs the explicit handling in step 1b.
    normalized_keys = {
        "incentive_types", "incentive_data", "incl_excl_types", "incl_excl_data", "vice_versa",
        "scope_type", "agency_id", "corporate_id", "agency_entity_id",
    }
    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field in normalized_keys:
            continue
        if field in ("valid_from", "valid_to") and isinstance(value, str):
            value = date.fromisoformat(value) if value else None
        if hasattr(deal, field):
            setattr(deal, field, value)

    # 1b. Scope — cannot ride the loop above, because that loop runs on
    #     exclude_none=True. Switching a deal from Agency Specific back to Common
    #     sends agency_id=None, which exclude_none drops, leaving scope_type='all'
    #     beside a still-populated agency_id — a CHECK violation surfacing as a 500.
    #     (exclude_none stays for the rest: the Create Deal form unconditionally
    #     sends iata_number=null and entity_lcc=null, and dropping those is what
    #     stops an edit from wiping them.)
    #
    #     model_fields_set is what distinguishes "not sent" from "sent as null".
    #     Re-deriving the ids from the scope afterwards means no client payload can
    #     reach the CHECK at all — it degrades to a backstop against direct SQL.
    if "scope_type" in payload.model_fields_set and payload.scope_type is not None:
        scope = await _resolve_scope(
            db, current_user, deal.direction,
            payload.scope_type, payload.agency_id, payload.corporate_id, payload.agency_entity_id,
            fallback_label=payload.supplier_name or deal.supplier_name,
        )
        deal.scope_type       = scope.scope_type
        deal.agency_id        = scope.agency_id
        deal.corporate_id     = scope.corporate_id
        deal.agency_entity_id = scope.agency_entity_id
        deal.scope_party_name = scope.party_name
        if deal.direction == DealDirection.OUTBOUND:
            deal.supplier_name = scope.supplier_label

    # 2. Rebuild incentive/slab/rule rows only when the edit touched them.
    touches_relations = (
        payload.incentive_data is not None
        or payload.incl_excl_data is not None
        or bool(payload.incentive_types)
    )
    if touches_relations:
        existing_inc_types, existing_inc_data = _build_inc_data_from_configs(deal.incentives)
        existing_ie_data: dict = {}
        for inc in (deal.incentives or []):
            if getattr(inc, "rules", None):
                _types, _data, _ = _build_ie_from_rules(inc.rules)
                if _types:
                    existing_ie_data[inc.incentive_type] = _data

        final_inc_data = payload.incentive_data if payload.incentive_data is not None else existing_inc_data
        if payload.incentive_types:
            final_inc_types = list(payload.incentive_types)
        elif payload.incentive_data is not None:
            final_inc_types = list(payload.incentive_data.keys())
        else:
            final_inc_types = existing_inc_types
        final_ie_data = payload.incl_excl_data if payload.incl_excl_data is not None else existing_ie_data

        # Clear existing children, then recreate (cascade removes slabs/values/rules/conditions).
        for inc in list(deal.incentives):
            await db.delete(inc)
        await db.flush()

        await _rebuild_unified_relations(
            deal_id=deal.id,
            incentive_types=final_inc_types,
            incentive_data=final_inc_data,
            incl_excl_data=final_ie_data,
            db=db,
        )

    await db.commit()

    # 3. Re-load with relations eager so the response carries reconstructed data.
    #    The session uses expire_on_commit=False, so the just-committed `deal` is
    #    still cached in the identity map with its STALE incentives collection
    #    (the rows we deleted/replaced above). Without populate_existing the eager
    #    loaders won't overwrite that already-loaded collection, and the response
    #    would echo pre-edit incentive/incl-excl data even though the DB is correct
    #    — the bug where edits only showed up after a page refresh.
    result = await db.execute(
        select(UnifiedDeal)
        .options(*eager)
        .where(UnifiedDeal.id == deal_id)
        .execution_options(populate_existing=True)
    )
    deal = result.scalar_one()
    return _unified_deal_to_repo_item(deal)


# ── Delete a deal from the repository ────────────────────────────────────

@router.delete("/repository/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository_deal(
    deal_id: int,
    deal_type: str = Query("airline", description="'upload' | 'airline' | 'b2b'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete any deal in the repository (unified / upload / airline / b2b table)."""
    result = await db.execute(
        select(UnifiedDeal).where(
            UnifiedDeal.id == deal_id,
            UnifiedDeal.tenant_id == current_user.tenant_id,
            UnifiedDeal.created_by_id == current_user.id,
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
    result = await db.execute(
        select(UnifiedDeal).where(
            UnifiedDeal.id == deal_id,
            UnifiedDeal.tenant_id == current_user.tenant_id,
            UnifiedDeal.created_by_id == current_user.id,
        )
    )
    deal = result.scalar_one_or_none()
    rejected_status = DealStatusType.REJECTED
    pending_status  = DealStatusType.PENDING_APPROVAL

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
        .where(DealApproval.deal_type == "unified", DealApproval.deal_id == deal_id)
    )
    existing_approval = approval_result.scalar_one_or_none()
    if existing_approval:
        for step in existing_approval.steps:
            await db.delete(step)
        await db.delete(existing_approval)
        await db.flush()

    deal.status = pending_status
    await _seed_approval_unified(deal, current_user, db)
    await db.commit()
    return {"success": True, "message": "Deal resubmitted for approval"}


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

    # 2. Batch-load the unified deals (all deals are unified)
    unified_ids = [a.deal_id for a in approvals if a.deal_type == "unified"]
    unified_map: dict[int, UnifiedDeal] = {}
    if unified_ids:
        rows = await db.execute(
            select(UnifiedDeal)
            .options(
                selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.slabs).selectinload(DealIncentiveSlab.values),
                selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.rules).selectinload(DealRule.conditions),
            )
            .where(UnifiedDeal.id.in_(unified_ids), UnifiedDeal.tenant_id == current_user.tenant_id)
        )
        unified_map = {d.id: d for d in rows.scalars().all()}

    # 3. Build response — id = DealApproval.id (routing key), deal_id = deal's own ID
    items: list[ApprovalInboxItem] = []
    for approval in approvals:
        status_str = approval.status.value if hasattr(approval.status, "value") else str(approval.status)

        if approval.deal_type != "unified":
            continue  # legacy deal approvals have been removed
        ud = unified_map.get(approval.deal_id)
        if not ud:
            continue
        inc_types, inc_data = _build_inc_data_from_configs(ud.incentives)
        _all_ie_types: list[str] = []
        _all_ie_data: dict = {}
        for _inc in (ud.incentives or []):
            if getattr(_inc, "rules", None):
                _t, _d, _ = _build_ie_from_rules(_inc.rules)
                if _t:
                    _all_ie_data[_inc.incentive_type] = _d
                    for _rt in _t:
                        if _rt not in _all_ie_types:
                            _all_ie_types.append(_rt)
        ie_types, ie_data = _all_ie_types, _all_ie_data
        is_b2b = ud.deal_type == DealKind.B2B
        items.append(ApprovalInboxItem(
            id=approval.id, deal_id=ud.id,
            deal_type="b2b" if is_b2b else "airline",
            source_agent=ud.source_agent,
            airline_name=ud.airline_name, airline_type=ud.airline_type,
            status=status_str, created_at=ud.created_at,
            valid_from=ud.valid_from, valid_to=ud.valid_to,
            business_type=ud.business_type,
            incentive_types=inc_types,
            incentive_data=inc_data,
            incl_excl_types=ie_types,
            incl_excl_data=ie_data,
            deal_maker_name=ud.deal_maker_name,
            contract_year=ud.contract_year,
            trigger_type=ud.trigger_type,
            payout_type=ud.payout_type,
            entity_lcc=ud.entity_lcc,
            remark=ud.remark,
            deal_no=f"{'B2B' if is_b2b else 'AIR'}-{ud.id:06d}",
            batch_id=None,
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
    """Return (deal_object, deal_type_str) for a DealApproval record. All deals are unified."""
    r = await db.execute(select(UnifiedDeal).where(UnifiedDeal.id == approval.deal_id))
    return r.scalar_one(), "unified"


async def _find_matching_active_deals(
    new_deal,
    new_deal_type: str,
    db: AsyncSession,
) -> list[ClosingDealSummary]:
    """Return summaries of ACTIVE deals that would be closed when new_deal is approved."""
    summaries: list[ClosingDealSummary] = []

    # Determine new deal's primary flight_type + class (works for both unified and legacy)
    if new_deal_type == "unified":
        inc_result = await db.execute(
            select(DealIncentiveConfig)
            .where(DealIncentiveConfig.deal_id == new_deal.id)
            .order_by(DealIncentiveConfig.incentive_order).limit(1)
        )
        primary_inc = inc_result.scalar_one_or_none()
        new_flight_type = primary_inc.flight_type if primary_inc else None
        new_class = primary_inc.class_ if primary_inc else None
    else:
        inc_data  = getattr(new_deal, "incentive_data", {}) or {}
        inc_types = getattr(new_deal, "incentive_types", []) or []
        primary   = inc_types[0] if inc_types else None
        pdata     = inc_data.get(primary, {}) if (primary and isinstance(inc_data, dict)) else {}
        new_flight_type = pdata.get("flightType")
        new_class = pdata.get("class")

    base_filters_unified = [
        UnifiedDeal.tenant_id             == new_deal.tenant_id,
        UnifiedDeal.deal_lifecycle_status == DealLifecycleType.ACTIVE,
        UnifiedDeal.deal_maker_name       == new_deal.deal_maker_name,
        UnifiedDeal.airline_name          == new_deal.airline_name,
        UnifiedDeal.airline_type          == new_deal.airline_type,
    ]
    if new_deal_type == "unified":
        base_filters_unified.append(UnifiedDeal.id != new_deal.id)
    uni_result = await db.execute(
        select(UnifiedDeal)
        .options(
            selectinload(UnifiedDeal.incentives).selectinload(DealIncentiveConfig.slabs).selectinload(DealIncentiveSlab.values),
        )
        .where(*base_filters_unified)
    )
    for d in uni_result.scalars().all():
        d_primary = d.incentives[0] if d.incentives else None
        if d_primary and d_primary.flight_type == new_flight_type and d_primary.class_ == new_class:
            is_b2b = d.deal_type == DealKind.B2B
            inc_types, inc_data = _build_inc_data_from_configs(d.incentives)
            summaries.append(ClosingDealSummary(
                deal_id=d.id,
                deal_type="b2b" if is_b2b else "airline",
                deal_no=f"{'B2B' if is_b2b else 'AIR'}-{d.id:06d}",
                airline_name=d.airline_name,
                airline_type=d.airline_type,
                source_agent=d.source_agent,
                deal_maker_name=d.deal_maker_name,
                valid_from=d.valid_from,
                valid_to=d.valid_to,
                contract_year=d.contract_year,
                business_type=d.business_type,
                trigger_type=d.trigger_type,
                payout_type=d.payout_type,
                entity_lcc=d.entity_lcc,
                incentive_types=inc_types,
                incentive_data=inc_data,
                incl_excl_types=[],
                incl_excl_data={},
                remark=d.remark,
            ))

    return summaries


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

    # All deals are unified.
    deal_type = approval.deal_type
    deal_result = await db.execute(select(UnifiedDeal).where(UnifiedDeal.id == approval.deal_id))
    deal = deal_result.scalar_one()
    approved_status = DealStatusType.APPROVED
    rejected_status = DealStatusType.REJECTED

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
            deal.deal_lifecycle_status = DealLifecycleType.ACTIVE
            await _close_matching_unified_deals(deal, db)

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


# ── GCS file upload & preview ─────────────────────────────────────────────────

@router.post("/batches/{batch_id}/file")
async def upload_batch_file(
    batch_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload the source file for a deal batch to GCS. Called right after confirm."""
    import logging, mimetypes
    from app.services import gcs as gcs_service
    from app.config import settings
    log = logging.getLogger(__name__)

    log.info("[DEAL FILE UPLOAD] batch_id=%s | filename=%s | tenant=%s",
             batch_id, file.filename, current_user.tenant_id)

    batch = await db.scalar(
        select(DealBatch).where(
            DealBatch.batch_id == batch_id,
            DealBatch.tenant_id == current_user.tenant_id,
            DealBatch.created_by_id == current_user.id,
        )
    )
    if not batch:
        log.error("[DEAL FILE UPLOAD] Batch not found: %s", batch_id)
        raise HTTPException(status_code=404, detail="Batch not found")

    log.info("[DEAL FILE UPLOAD] Batch found. Reading file content...")
    bucket_name = settings.GCS_DEALS_BUCKET_NAME
    log.info("[DEAL FILE UPLOAD] GCS_DEALS_BUCKET_NAME=%r", bucket_name)

    content = await file.read()
    log.info("[DEAL FILE UPLOAD] File read complete | size=%d bytes", len(content))

    ct = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    blob_name = f"deals/{current_user.tenant_id}/{batch_id}/{file.filename}"
    log.info("[DEAL FILE UPLOAD] Uploading to GCS | blob=%s | content_type=%s", blob_name, ct)

    try:
        await gcs_service.upload_bytes(content, blob_name, ct, bucket_name)
        log.info("[DEAL FILE UPLOAD] GCS upload SUCCESS | blob=%s", blob_name)
    except Exception as e:
        log.error("[DEAL FILE UPLOAD] GCS upload FAILED: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"GCS upload failed: {e}")

    batch.file_url = blob_name
    await db.commit()
    log.info("[DEAL FILE UPLOAD] DB updated with file_url | batch_id=%s", batch_id)
    return {"file_url": blob_name}


@router.get("/batches/{batch_id}/file-url")
async def get_batch_file_url(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a short-lived signed URL for previewing the batch source file."""
    from app.services import gcs as gcs_service
    from app.config import settings

    batch = await db.scalar(
        select(DealBatch).where(
            DealBatch.batch_id == batch_id,
            DealBatch.tenant_id == current_user.tenant_id,
            DealBatch.created_by_id == current_user.id,
        )
    )
    if not batch or not batch.file_url:
        raise HTTPException(status_code=404, detail="No file attached to this batch")
    bucket_name = settings.GCS_DEALS_BUCKET_NAME
    is_pdf = (batch.file_type or "").lower() == "pdf"
    url = await gcs_service.generate_signed_url(batch.file_url, bucket_name, expiry_minutes=60, inline=is_pdf)
    return {"url": url, "file_type": batch.file_type or ""}
