"""Dashboard analytics endpoints — aggregated KPIs, income summary, pending actions, supplier comparison."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline import Airline
from app.models.airline_class_master import AirlineClassMaster
from app.models.approval_workflow import DealApproval, ApprovalActionStatus
from app.models.uploaded_deal import UploadedDeal, UploadedDealStatus
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class MonthlyIncome(BaseModel):
    month: str
    income: float

class AirlineIncome(BaseModel):
    airline: str
    income: float

class SummaryResponse(BaseModel):
    total_income:      float
    total_tickets:     int
    active_deals:      int
    pending_count:     int
    monthly_income:    list[MonthlyIncome]
    income_by_airline: list[AirlineIncome]


class MonthlyBreakdown(BaseModel):
    month:       str
    commission:  float
    incentive:   float
    delta_comm:  float

class AirlineBreakdown(BaseModel):
    airline:    str
    commission: float
    incentive:  float
    delta_comm: float
    total:      float

class IncomeSummaryResponse(BaseModel):
    total:      float
    commission: float
    incentive:  float
    delta_comm: float
    monthly:    list[MonthlyBreakdown]
    by_airline: list[AirlineBreakdown]


class DealApprovalItem(BaseModel):
    id:           int
    deal_id:      int
    deal_ref:     str
    airline_name: str
    deal_type:    str
    submitted_by: str
    submitted_at: str

class ExtractionReviewItem(BaseModel):
    id:           int
    deal_ref:     str
    airline_name: str
    file_name:    str
    uploaded_at:  str

class UnmatchedTicketItem(BaseModel):
    id:            int
    ticket_number: str | None
    airlines_code: str | None
    airline_name:  str | None
    sector:        str | None
    booking_class: str | None
    ticket_date:   str | None

class PendingActionsResponse(BaseModel):
    deal_approvals:    list[DealApprovalItem]
    extraction_review: list[ExtractionReviewItem]
    unmatched_tickets: list[UnmatchedTicketItem]


class SupplierStat(BaseModel):
    name:           str
    total_income:   float
    deal_count:     int
    ticket_count:   int
    avg_commission: float

class SupplierComparisonResponse(BaseModel):
    suppliers: list[SupplierStat]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ym(date_str: str | None) -> str | None:
    """Extract YYYY-MM label from a date string like '2025-01-15', '15-01-2025', etc."""
    if not date_str:
        return None
    s = str(date_str).strip()
    # Try ISO first (YYYY-MM-DD)
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    # Try DD-MM-YYYY
    try:
        parts = s.replace("/", "-").split("-")
        if len(parts) == 3 and len(parts[2]) == 4:
            return f"{parts[2]}-{parts[1].zfill(2)}"
    except Exception:
        pass
    return None


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%d %b %Y") if dt else ""


def _f(v) -> float:
    """Coerce Decimal / None to float — DB returns NUMERIC as Decimal."""
    return float(v) if v is not None else 0.0


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = current_user.tenant_id

    tickets_res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.tenant_id == tid,
            UploadedTicket.created_by_id == current_user.id,
        )
    )
    tickets = tickets_res.scalars().all()

    total_income = sum(_f(t.comm_sell) + _f(t.calculated_incentive) for t in tickets)
    total_tickets = len(tickets)

    active_deals_res = await db.execute(
        select(func.count(UploadedDeal.id)).where(
            UploadedDeal.tenant_id == tid,
            UploadedDeal.created_by_id == current_user.id,
            UploadedDeal.status == UploadedDealStatus.APPROVED,
        )
    )
    active_deals = active_deals_res.scalar_one() or 0

    pending_res = await db.execute(
        select(func.count(DealApproval.id)).where(
            DealApproval.status == ApprovalActionStatus.PENDING,
            DealApproval.submitted_by_id == current_user.id,
        )
    )
    pending_deals = pending_res.scalar_one() or 0
    unmatched_count = sum(1 for t in tickets if t.matched_deal_id is None)
    pending_count = pending_deals + unmatched_count

    # Monthly income — last 12 months, sorted ascending
    monthly: dict[str, float] = defaultdict(float)
    for t in tickets:
        ym = _ym(t.ticket_date) or _ym(str(t.created_at)[:10] if t.created_at else None)
        if ym:
            monthly[ym] += _f(t.comm_sell) + _f(t.calculated_incentive)
    monthly_list = [
        MonthlyIncome(month=k, income=round(v, 2))
        for k, v in sorted(monthly.items())[-12:]
    ]

    # Income by airline — top 10
    by_airline: dict[str, float] = defaultdict(float)
    for t in tickets:
        key = t.airline_name or t.airlines_code or "Unknown"
        by_airline[key] += _f(t.comm_sell) + _f(t.calculated_incentive)
    airline_list = [
        AirlineIncome(airline=k, income=round(v, 2))
        for k, v in sorted(by_airline.items(), key=lambda x: -x[1])[:10]
    ]

    return SummaryResponse(
        total_income=round(total_income, 2),
        total_tickets=total_tickets,
        active_deals=active_deals,
        pending_count=pending_count,
        monthly_income=monthly_list,
        income_by_airline=airline_list,
    )


_DOM_VARIANTS  = {"DOM", "DOMESTIC", "D"}
_INT_VARIANTS  = {"INT", "INTL", "INTERNATIONAL", "I"}


class IncomeFiltersResponse(BaseModel):
    airlines:    list[str]
    segments:    list[str]
    class_types: list[str]


@router.get("/income-filters", response_model=IncomeFiltersResponse)
async def get_income_filters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    airline: str | None = Query(default=None),
):
    # Airlines from master (active only)
    a_res = await db.execute(
        select(Airline.name).where(Airline.is_active == True).order_by(Airline.name)
    )
    airlines = [r[0] for r in a_res.all()]

    # Segments are always the same two logical values
    segments = ["Domestic", "International"]

    # Class types from AirlineClassMaster, filtered by airline if provided
    ct_q = select(AirlineClassMaster.class_type).where(AirlineClassMaster.is_active == True).distinct()
    if airline:
        ct_q = ct_q.where(func.lower(AirlineClassMaster.airline_name) == airline.lower())
    ct_res = await db.execute(ct_q.order_by(AirlineClassMaster.class_type))
    class_types = [r[0] for r in ct_res.all()]

    return IncomeFiltersResponse(airlines=airlines, segments=segments, class_types=class_types)


@router.get("/income-summary", response_model=IncomeSummaryResponse)
async def get_income_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    airline: str | None = Query(default=None),
    segment: str | None = Query(default=None),
    class_type: str | None = Query(default=None),
):
    tid = current_user.tenant_id
    filters = [
        UploadedTicket.tenant_id == tid,
        UploadedTicket.created_by_id == current_user.id,
    ]

    if airline:
        filters.append(UploadedTicket.airline_name == airline)

    if segment:
        seg_upper = segment.upper()
        if seg_upper in _DOM_VARIANTS:
            filters.append(func.upper(UploadedTicket.segment_type).in_(list(_DOM_VARIANTS)))
        elif seg_upper in _INT_VARIANTS:
            filters.append(func.upper(UploadedTicket.segment_type).in_(list(_INT_VARIANTS)))

    if class_type:
        # Resolve class_type → class_codes via AirlineClassMaster for the selected airline
        cc_q = select(AirlineClassMaster.class_code).where(
            AirlineClassMaster.class_type == class_type,
            AirlineClassMaster.is_active == True,
        )
        if airline:
            cc_q = cc_q.where(func.lower(AirlineClassMaster.airline_name) == airline.lower())
        cc_res = await db.execute(cc_q)
        class_codes = [r[0] for r in cc_res.all()]
        if class_codes:
            filters.append(UploadedTicket.booking_class.in_(class_codes))

    tickets_res = await db.execute(select(UploadedTicket).where(*filters))
    tickets = tickets_res.scalars().all()

    total            = sum(_f(t.sell_fare) for t in tickets)
    total_commission = sum(_f(t.comm_sell) for t in tickets)
    total_incentive  = sum(_f(t.calculated_incentive) for t in tickets)
    total_delta_comm = sum(_f(t.comm_sell) - _f(t.calculated_incentive) for t in tickets)

    # Monthly breakdown
    m_comm:  dict[str, float] = defaultdict(float)
    m_inc:   dict[str, float] = defaultdict(float)
    m_delta: dict[str, float] = defaultdict(float)
    for t in tickets:
        ym = _ym(t.ticket_date) or _ym(str(t.created_at)[:10] if t.created_at else None)
        if ym:
            m_comm[ym]  += _f(t.comm_sell)
            m_inc[ym]   += _f(t.calculated_incentive)
            m_delta[ym] += _f(t.comm_sell) - _f(t.calculated_incentive)
    all_months = sorted(set(m_comm) | set(m_inc) | set(m_delta))[-12:]
    monthly = [
        MonthlyBreakdown(
            month=ym,
            commission=round(m_comm[ym], 2),
            incentive=round(m_inc[ym], 2),
            delta_comm=round(m_delta[ym], 2),
        )
        for ym in all_months
    ]

    # By airline
    a_comm:  dict[str, float] = defaultdict(float)
    a_inc:   dict[str, float] = defaultdict(float)
    a_delta: dict[str, float] = defaultdict(float)
    for t in tickets:
        key = t.airline_name or t.airlines_code or "Unknown"
        a_comm[key]  += _f(t.comm_sell)
        a_inc[key]   += _f(t.calculated_incentive)
        a_delta[key] += _f(t.comm_sell) - _f(t.calculated_incentive)
    all_airlines = sorted(a_comm, key=lambda k: -(a_comm[k] + a_inc[k] + a_delta[k]))[:15]
    by_airline = [
        AirlineBreakdown(
            airline=k,
            commission=round(a_comm[k], 2),
            incentive=round(a_inc[k], 2),
            delta_comm=round(a_delta[k], 2),
            total=round(a_comm[k] + a_inc[k] + a_delta[k], 2),
        )
        for k in all_airlines
    ]

    return IncomeSummaryResponse(
        total=round(total, 2),
        commission=round(total_commission, 2),
        incentive=round(total_incentive, 2),
        delta_comm=round(total_delta_comm, 2),
        monthly=monthly,
        by_airline=by_airline,
    )


@router.get("/pending-actions", response_model=PendingActionsResponse)
async def get_pending_actions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = current_user.tenant_id

    # --- Deal Approvals (pending) ---
    approvals_res = await db.execute(
        select(DealApproval).where(
            DealApproval.status == ApprovalActionStatus.PENDING,
            DealApproval.submitted_by_id == current_user.id,
        )
    )
    pending_approvals = approvals_res.scalars().all()

    # Fetch submitter names in one query
    submitter_ids = {a.submitted_by_id for a in pending_approvals}
    users_map: dict[int, str] = {}
    if submitter_ids:
        users_res = await db.execute(select(User).where(User.id.in_(submitter_ids)))
        for u in users_res.scalars():
            users_map[u.id] = u.full_name or u.email or str(u.id)

    # Fetch deal names for 'upload' type approvals
    upload_deal_ids = {a.deal_id for a in pending_approvals if a.deal_type == "upload"}
    deals_map: dict[int, UploadedDeal] = {}
    if upload_deal_ids:
        deals_res = await db.execute(
            select(UploadedDeal).where(UploadedDeal.id.in_(upload_deal_ids))
        )
        for d in deals_res.scalars():
            deals_map[d.id] = d

    deal_approvals = []
    for a in pending_approvals:
        deal = deals_map.get(a.deal_id)
        deal_approvals.append(DealApprovalItem(
            id=a.id,
            deal_id=a.deal_id,
            deal_ref=f"{a.deal_type.upper()}-{a.deal_id:04d}",
            airline_name=deal.airline_name or "—" if deal else "—",
            deal_type=a.deal_type,
            submitted_by=users_map.get(a.submitted_by_id, "—"),
            submitted_at=_fmt_dt(a.submitted_at),
        ))

    # --- Extraction Review (deals not yet approved) ---
    review_res = await db.execute(
        select(UploadedDeal).where(
            UploadedDeal.tenant_id == tid,
            UploadedDeal.created_by_id == current_user.id,
            UploadedDeal.status.in_([
                UploadedDealStatus.EXTRACTED,
                UploadedDealStatus.PENDING_APPROVAL,
            ]),
        ).order_by(UploadedDeal.created_at.desc()).limit(50)
    )
    review_deals = review_res.scalars().all()
    extraction_review = [
        ExtractionReviewItem(
            id=d.id,
            deal_ref=f"DEAL-{d.id:04d}",
            airline_name=d.airline_name or d.source_agent or "—",
            file_name=d.file_name or "—",
            uploaded_at=_fmt_dt(d.created_at),
        )
        for d in review_deals
    ]

    # --- Unmatched Tickets ---
    unmatched_res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.tenant_id == tid,
            UploadedTicket.created_by_id == current_user.id,
            UploadedTicket.matched_deal_id.is_(None),
        ).order_by(UploadedTicket.created_at.desc()).limit(50)
    )
    unmatched_tickets = [
        UnmatchedTicketItem(
            id=t.id,
            ticket_number=t.ticket_number,
            airlines_code=t.airlines_code,
            airline_name=t.airline_name,
            sector=t.sector,
            booking_class=t.booking_class,
            ticket_date=t.ticket_date,
        )
        for t in unmatched_res.scalars().all()
    ]

    return PendingActionsResponse(
        deal_approvals=deal_approvals,
        extraction_review=extraction_review,
        unmatched_tickets=unmatched_tickets,
    )


@router.get("/supplier-comparison", response_model=SupplierComparisonResponse)
async def get_supplier_comparison(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = current_user.tenant_id

    # All deals for this tenant grouped by source_agent
    deals_res = await db.execute(
        select(UploadedDeal).where(
            UploadedDeal.tenant_id == tid,
            UploadedDeal.created_by_id == current_user.id,
        )
    )
    all_deals = deals_res.scalars().all()

    # Build supplier deal map: name → {deal_count, deal_ids}
    supplier_deals: dict[str, list[int]] = defaultdict(list)
    for d in all_deals:
        name = d.source_agent or d.deal_maker_name or "Unknown"
        supplier_deals[name].append(d.id)

    if not supplier_deals:
        return SupplierComparisonResponse(suppliers=[])

    # All tickets for this tenant
    tickets_res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.tenant_id == tid,
            UploadedTicket.created_by_id == current_user.id,
        )
    )
    tickets = tickets_res.scalars().all()

    # Map deal_id → supplier name (reverse lookup)
    deal_to_supplier: dict[int, str] = {}
    for sup, deal_ids in supplier_deals.items():
        for did in deal_ids:
            deal_to_supplier[did] = sup

    # Aggregate per supplier from tickets
    sup_income: dict[str, float]  = defaultdict(float)
    sup_tickets: dict[str, int]   = defaultdict(int)
    sup_comm: dict[str, list[float]] = defaultdict(list)
    for t in tickets:
        sup_name = deal_to_supplier.get(t.matched_deal_id) if t.matched_deal_id else None
        if sup_name:
            sup_income[sup_name] += _f(t.comm_sell) + _f(t.calculated_incentive)
            sup_tickets[sup_name] += 1
            if t.comm_sell:
                sup_comm[sup_name].append(float(t.comm_sell))

    # Build result — all suppliers with deal counts, even those without matched tickets
    stats = []
    for sup_name, deal_ids in supplier_deals.items():
        income = sup_income.get(sup_name, 0.0)
        tcount = sup_tickets.get(sup_name, 0)
        comm_vals = sup_comm.get(sup_name, [])
        avg_comm = sum(comm_vals) / len(comm_vals) if comm_vals else 0.0
        stats.append(SupplierStat(
            name=sup_name,
            total_income=round(income, 2),
            deal_count=len(deal_ids),
            ticket_count=tcount,
            avg_commission=round(avg_comm, 2),
        ))

    # Sort by total income descending
    stats.sort(key=lambda s: -s.total_income)
    return SupplierComparisonResponse(suppliers=stats[:20])
