"""Agency Billing — bill the tickets belonging to an onboarded agency.

Mirrors the customer billing flow in `customers.py`, but scoped to an Agency
(from the Customer Directory). An agency's tickets are every UploadedTicket whose
statement `agency` matches the agency name. Agencies have no stored default markup,
so markup comes only from the per-ticket "additional markup"; GST uses the agency
formula (18% on markup − discount). Billings are stored in the shared `billings`
table with `agency_id` set (and `customer_id` NULL).
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency import CHANNELS, Agency, norm_channel
from app.models.agency_ledger import AgencyLedger
from app.models.billing import Billing
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User
from app.models.tenant import Tenant
from app.schemas.customer import SoldTicketRead, SoldTicketsSummary
from app.schemas.billing import (
    BillingCreate, BillingUpdate, BillingRead, BillingListItem,
    AgencyLite, AgencyTicketsResponse,
)
from app.services.billing_calc import (
    to_float as _f,
    compute_gst as _compute_gst,
    safe_date as _safe_date,
    passenger_name as _passenger_name,
)
from app.services.billing_pdf import build_billing_pdf
from app.services.agency_account import agency_statement_scope, current_terms

router = APIRouter()

# Agencies carry no per-agency default markup (unlike customers). Markup on an
# agency bill comes solely from the per-ticket additional markup entered by the
# user; GST is computed with the "agency" rule (tax on markup only).
_AGENCY_BILLING_TYPE = "agency"


def _resolve_channel(agency: Agency, channel: Optional[str]) -> str:
    """Which channel an agency invoice belongs to.

    Mirrors agency_account._resolve_channel: omitting it is fine for an agency
    that trades on one channel and refused for one that trades on both, because
    guessing picks whose money gets spent.
    """
    ch = norm_channel(channel)
    if ch is None:
        if agency.channels in CHANNELS:
            return agency.channels
        raise HTTPException(
            status_code=400,
            detail="This agency trades on GDS and LCC — say which channel this billing is for.",
        )
    if ch not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")
    if agency.channels != "BOTH" and agency.channels != ch:
        raise HTTPException(
            status_code=400,
            detail=f"This agency trades on {agency.channels} only — it has no {ch} account.",
        )
    return ch


async def _get_owned_agency(agency_id: int, db: AsyncSession, current_user: User) -> Agency:
    result = await db.execute(
        select(Agency).where(Agency.id == agency_id, Agency.user_id == current_user.id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Agency not found")
    return obj


async def _get_owned_agency_billing(billing_id: int, agency_id: int, db: AsyncSession, current_user: User) -> Billing:
    result = await db.execute(
        select(Billing).where(
            Billing.id == billing_id,
            Billing.agency_id == agency_id,
            Billing.tenant_id == current_user.tenant_id,
            Billing.created_by_id == current_user.id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Billing not found")
    return obj


async def _load_agency_tickets(agency: Agency, db: AsyncSession, current_user: User) -> list[UploadedTicket]:
    """All uploaded tickets tagged to this agency BRANCH.

    Resolution lives in agency_statement_scope: an explicit `agency_id` on the
    statement always wins, and the bare-name fallback applies only when that
    vendor name resolves to one agency. Two branches of one vendor would
    otherwise both match, and the first to bill would take the other's tickets
    for good — uploaded_tickets.billing_id is a single FK.
    """
    clause, _ambiguous = await agency_statement_scope(db, agency, current_user)
    q = (
        select(UploadedTicket)
        .join(TicketStatement, UploadedTicket.batch_id == TicketStatement.batch_id)
        .where(
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
            clause,
        )
        .order_by(UploadedTicket.created_at.desc())
    )
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Tickets ──────────────────────────────────────────────────────────────────

@router.get("/{agency_id}/tickets", response_model=AgencyTicketsResponse)
async def get_agency_tickets(
    agency_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    date_field: str = "ticket",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agency = await _get_owned_agency(agency_id, db, current_user)
    tickets = await _load_agency_tickets(agency, db, current_user)

    # Filter by date range (date fields are strings; parse in Python).
    # date_field='travel' uses departure/travel date, else the ticket issue date.
    # Tickets with no parseable date are excluded when a range is set.
    if date_from or date_to:
        use_travel = date_field == "travel"
        in_range: list[UploadedTicket] = []
        for t in tickets:
            d = _safe_date(t.departure_datetime, t.travel_dt) if use_travel else _safe_date(t.ticket_date)
            if d is None:
                continue
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            in_range.append(t)
        tickets = in_range

    rows: list[SoldTicketRead] = []
    total_base = total_markup = total_gst = total_with_markup = 0.0
    for t in tickets:
        base = _f(t.total_amt) if t.total_amt is not None else _f(t.sell_fare)
        markup_amount = 0.0  # no per-agency default markup
        gst_amount = _compute_gst(base, markup_amount, _AGENCY_BILLING_TYPE)
        total = base + markup_amount + gst_amount
        total_base += base
        total_markup += markup_amount
        total_gst += gst_amount
        total_with_markup += total
        rows.append(SoldTicketRead(
            id=t.id,
            ticket_number=t.ticket_number,
            airline_name=t.airline_name,
            airlines_code=t.airlines_code,
            first_name=t.first_name,
            last_name=t.last_name,
            pax_name=t.pax_name,
            sector=t.sector,
            booking_class=t.booking_class,
            ticket_date=t.ticket_date,
            ticket_status=t.ticket_status,
            sell_fare=_f(t.sell_fare) if t.sell_fare is not None else None,
            total_amt=_f(t.total_amt) if t.total_amt is not None else None,
            calculated_incentive=_f(t.calculated_incentive) if t.calculated_incentive is not None else None,
            incentive_breakdown=t.incentive_breakdown,
            is_billed=bool(t.is_billed),
            billing_id=t.billing_id,
            base_amount=round(base, 2),
            markup_amount=round(markup_amount, 2),
            gst_amount=round(gst_amount, 2),
            total_with_markup=round(total, 2),
        ))

    return AgencyTicketsResponse(
        agency=AgencyLite.model_validate(agency),
        tickets=rows,
        summary=SoldTicketsSummary(
            count=len(rows),
            total_base=round(total_base, 2),
            total_markup=round(total_markup, 2),
            total_gst=round(total_gst, 2),
            total_with_markup=round(total_with_markup, 2),
        ),
    )


# ── Billing ──────────────────────────────────────────────────────────────────

@router.post("/{agency_id}/billings", response_model=BillingRead, status_code=status.HTTP_201_CREATED)
async def create_agency_billing(
    agency_id: int,
    payload: BillingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agency = await _get_owned_agency(agency_id, db, current_user)
    # Which account this invoice draws down. An agency that is cash on GDS and
    # credit on LCC settles them separately, so posting to the wrong one would
    # spend a deposit that was never meant for these tickets.
    channel = _resolve_channel(agency, payload.channel)
    if not payload.billing_name.strip():
        raise HTTPException(status_code=400, detail="billing_name is required.")
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one ticket is required to create a billing.")

    ticket_ids = [it.ticket_id for it in payload.items]
    addl_map = {it.ticket_id: _f(it.additional_markup) for it in payload.items}
    disc_map = {it.ticket_id: _f(it.discount) for it in payload.items}

    res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id.in_(ticket_ids),
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
        )
    )
    tickets = res.scalars().all()
    if not tickets:
        raise HTTPException(status_code=400, detail="No matching tickets found for this billing.")

    # Every id must resolve — a partial match used to bill fewer tickets silently.
    missing = set(ticket_ids) - {t.id for t in tickets}
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"{len(missing)} of the selected tickets no longer exist. Refresh and try again.",
        )

    # An agency's tickets are the ones under a statement scoped to it. Resolving the
    # same clause the list endpoint uses is what makes its ambiguous-agency refusal
    # bind on POST too, instead of only on GET.
    scope_clause, _ambiguous = await agency_statement_scope(db, agency, current_user)
    allowed = {
        b for (b,) in (await db.execute(
            select(TicketStatement.batch_id).where(scope_clause)
        )).all()
    }
    foreign = [t.ticket_number or t.pax_name or str(t.id) for t in tickets
               if t.batch_id not in allowed]
    if foreign:
        raise HTTPException(
            status_code=400,
            detail=("These tickets are not tagged to this agency: "
                    f"{', '.join(foreign[:5])}{'…' if len(foreign) > 5 else ''}."),
        )

    # A ticket may belong to at most one billing (customer or agency). The UI
    # prevents selecting already-billed rows, so one here means a stale view.
    already = [t.ticket_number or str(t.id) for t in tickets if t.is_billed]
    if already:
        raise HTTPException(status_code=400, detail=f"Already billed: {', '.join(already)}. Refresh and try again.")

    line_items: list[dict] = []
    total_base = total_markup = total_addl = total_gst = grand = 0.0
    for t in tickets:
        base = _f(t.total_amt) if t.total_amt is not None else _f(t.sell_fare)
        agency_markup = 0.0  # no per-agency default markup
        addl = addl_map.get(t.id, 0.0)
        disc = disc_map.get(t.id, 0.0)
        total_mk = agency_markup + addl
        # Discount reduces the taxable value first, then GST applies on the reduced amount.
        gst = _compute_gst(base, total_mk, _AGENCY_BILLING_TYPE, disc)
        line_total = base + total_mk - disc + gst
        total_base += base
        total_markup += agency_markup
        total_addl += addl
        total_gst += gst
        grand += line_total
        line_items.append({
            "ticket_id": t.id,
            "ticket_number": t.ticket_number,
            "airline_name": t.airline_name,
            "airlines_code": t.airlines_code,
            "passenger": _passenger_name(t),
            "sector": t.sector,
            "ticket_date": t.ticket_date,
            "base_amount": round(base, 2),
            "markup_amount": round(agency_markup, 2),
            "additional_markup": round(addl, 2),
            "discount": round(disc, 2),
            "gst_amount": round(gst, 2),
            "total": round(line_total, 2),
        })

    billing = Billing(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        customer_id=None,
        agency_id=agency.id,
        billing_name=payload.billing_name.strip(),
        period_from=payload.period_from,
        period_to=payload.period_to,
        billing_type=_AGENCY_BILLING_TYPE,
        total_base=round(total_base, 2),
        total_markup=round(total_markup, 2),
        total_additional_markup=round(total_addl, 2),
        total_gst=round(total_gst, 2),
        grand_total=round(grand, 2),
        line_items=line_items,
    )
    db.add(billing)
    await db.flush()  # assign billing.id before linking tickets
    for t in tickets:
        t.is_billed = True
        t.billing_id = billing.id

    # Raising a billing is what draws down the agency's account, so it posts an
    # invoice entry. Doing it here (rather than a separate call the UI must
    # remember) is what keeps the ledger and `billings` from drifting apart.
    terms = await current_terms(db, agency.id, channel)
    db.add(AgencyLedger(
        agency_id=agency.id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        terms_id=terms.id if terms else None,
        channel=channel,
        entry_date=payload.period_to or date.today(),
        entry_type="invoice",
        amount=-Decimal(str(round(grand, 2))),
        billing_id=billing.id,
        note=billing.billing_name,
        created_by_id=current_user.id,
    ))
    await db.commit()
    await db.refresh(billing)
    return billing


@router.get("/{agency_id}/billings", response_model=list[BillingListItem])
async def list_agency_billings(
    agency_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_agency(agency_id, db, current_user)
    res = await db.execute(
        select(Billing)
        .where(
            Billing.agency_id == agency_id,
            Billing.tenant_id == current_user.tenant_id,
            Billing.created_by_id == current_user.id,
        )
        .order_by(Billing.created_at.desc())
    )
    billings = res.scalars().all()
    return [
        BillingListItem(
            id=b.id,
            billing_name=b.billing_name,
            period_from=b.period_from,
            period_to=b.period_to,
            total_base=_f(b.total_base),
            total_markup=_f(b.total_markup),
            total_additional_markup=_f(b.total_additional_markup),
            total_gst=_f(b.total_gst),
            grand_total=_f(b.grand_total),
            item_count=len(b.line_items or []),
            created_at=b.created_at,
        )
        for b in billings
    ]


@router.get("/{agency_id}/billings/{billing_id}", response_model=BillingRead)
async def get_agency_billing(
    agency_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_agency(agency_id, db, current_user)
    return await _get_owned_agency_billing(billing_id, agency_id, db, current_user)


@router.patch("/{agency_id}/billings/{billing_id}", response_model=BillingRead)
async def update_agency_billing(
    agency_id: int,
    billing_id: int,
    payload: BillingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_agency(agency_id, db, current_user)
    billing = await _get_owned_agency_billing(billing_id, agency_id, db, current_user)

    addl_map = {it.ticket_id: _f(it.additional_markup) for it in payload.items}

    new_items: list[dict] = []
    total_base = total_markup = total_addl = total_gst = grand = 0.0
    for it in (billing.line_items or []):
        base = _f(it.get("base_amount"))
        markup = _f(it.get("markup_amount"))
        addl = addl_map.get(it.get("ticket_id"), _f(it.get("additional_markup")))
        disc = _f(it.get("discount"))   # preserved from creation (not edited in the popup)
        gst = _compute_gst(base, markup + addl, billing.billing_type, disc)
        line_total = base + markup + addl - disc + gst
        total_base += base
        total_markup += markup
        total_addl += addl
        total_gst += gst
        grand += line_total
        new_items.append({
            **it,
            "additional_markup": round(addl, 2),
            "discount": round(disc, 2),
            "gst_amount": round(gst, 2),
            "total": round(line_total, 2),
        })

    billing.line_items = new_items
    billing.total_base = round(total_base, 2)
    billing.total_markup = round(total_markup, 2)
    billing.total_additional_markup = round(total_addl, 2)
    billing.total_gst = round(total_gst, 2)
    billing.grand_total = round(grand, 2)
    await db.commit()
    await db.refresh(billing)
    return billing


@router.delete("/{agency_id}/billings/{billing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agency_billing(
    agency_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_agency(agency_id, db, current_user)
    billing = await _get_owned_agency_billing(billing_id, agency_id, db, current_user)
    # Free the tickets locked to this billing so they can be billed again.
    await db.execute(
        update(UploadedTicket)
        .where(UploadedTicket.billing_id == billing.id)
        .values(is_billed=False, billing_id=None)
    )

    # Back the invoice out of the ledger by posting its opposite. The entry rows
    # stay — a deleted billing is still something that happened to the account.
    posted = (await db.execute(
        select(AgencyLedger).where(
            AgencyLedger.billing_id == billing.id,
            AgencyLedger.entry_type == "invoice",
            AgencyLedger.agency_id == agency_id,
        )
    )).scalars().all()
    for src in posted:
        already = (await db.execute(
            select(func.count()).select_from(AgencyLedger).where(AgencyLedger.reversal_of_id == src.id)
        )).scalar() or 0
        if already:
            continue
        db.add(AgencyLedger(
            agency_id=agency_id, user_id=current_user.id, tenant_id=current_user.tenant_id,
            terms_id=src.terms_id, channel=src.channel, entry_date=date.today(), entry_type="reversal",
            amount=-Decimal(str(src.amount)), note=f"Billing #{billing.id} deleted",
            reversal_of_id=src.id, created_by_id=current_user.id,
        ))

    # billing_id is ON DELETE SET NULL, so the entries survive the row going away.
    await db.delete(billing)
    await db.commit()


@router.get("/{agency_id}/billings/{billing_id}/pdf")
async def download_agency_billing_pdf(
    agency_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agency = await _get_owned_agency(agency_id, db, current_user)
    billing = await _get_owned_agency_billing(billing_id, agency_id, db, current_user)

    tenant = None
    if current_user.tenant_id:
        tres = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        tenant = tres.scalar_one_or_none()
    agency_from = {
        "name": (tenant.name if tenant and tenant.name else (tenant.domain if tenant else "")) or current_user.full_name,
        "domain": tenant.domain if tenant else "",
        "email": current_user.email,
    }
    # The PDF builder reads customer.<attr>; pass an agency-shaped shim as the BILL TO party.
    bill_to = SimpleNamespace(
        company=agency.name,
        first_name=None,
        last_name=None,
        title=agency.city,
        email=agency.contact_email,
        phone=agency.contact_phone,
        gst_no=agency.gst_number,
        pan_no=agency.pan_number,
    )
    buf = build_billing_pdf(billing, bill_to, agency_from)
    safe = "".join(c for c in (billing.billing_name or "") if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_") or "billing"
    filename = f"agency-billing-{billing.id}-{safe}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
