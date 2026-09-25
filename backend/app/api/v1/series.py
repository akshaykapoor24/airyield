"""Series / SIT / MICE / Group contracts — the commercial agreement and everything under it.

CRUD over the contract graph, plus the matching run that reconciles each contract against
the tickets actually issued on its PNRs (`services/series/matching.py`) and the deadline
regeneration that keeps its timeline honest (`services/series/deadlines.py`).

SCOPE IS THE TENANT, NOT THE CREATOR. Every other resource in this API filters
`tenant_id AND created_by_id`; `_scope` here filters on the tenant alone. A sixty-seat
group with a deposit due and a D-8 ticketing cut-off is an agency asset, and if the person
who keyed it in is on leave the deadline must not be invisible to their colleagues.
`created_by_id` is still written, as provenance.

WHAT IS DERIVED ON READ AND WHY. Overdue-ness and urgency are computed against today's
date on the way out, never stored. There is no scheduler in this stack — no Celery beat,
no cron — so a stored `overdue` flag would need something to flip it on the morning it
became true, and nothing would. Same posture as `Tenant.has_active_plan`, which is
evaluated live "so a lapsed plan freezes on the next request without a cron job flipping
the status".
"""
import hashlib
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.series import (
    ALLOCATION_STATUSES, BOOKING_STATUSES, COMPONENT_CODES, CONTRACT_STATUSES,
    CONTRACT_TYPES, DEADLINE_ANCHORS, DEADLINE_STATUSES, DEADLINE_TYPES, DIRECTIONS,
    DOCUMENT_KINDS, NAME_STATUSES, PAX_TYPES, PAYMENT_KINDS, SCHEDULE_STATUSES,
    SOURCE_TYPES, TERM_CHARGE_TYPES, TERM_PHASES, TERM_RULE_TYPES, TERM_SCOPES,
    SeriesAllocation, SeriesBooking, SeriesContract, SeriesDeadline, SeriesDocument,
    SeriesEvent, SeriesFareComponent, SeriesPassenger, SeriesPayment,
    SeriesPaymentSchedule, SeriesSector, SeriesTerm,
)
from app.models.user import User
from app.schemas.series import (
    ActionCenter, ActionItem, AllocationIn, AllocationRead, BookingIn, BookingRead,
    ContractCreate, ContractDetail, ContractRead, ContractUpdate, DeadlineIn,
    DeadlineRead, DocumentRead, ExposureRead, ExtractionResponse, FareComponentIn,
    FareComponentRead, FareSummary, MatchResult, PassengerIn, PassengerRead, PaymentIn,
    PaymentRead, ScheduleIn, ScheduleRead, TermIn, TermRead,
)
from app.services import file_store
from app.services.notifications import notify
from app.services.series import bases, deadlines as dl, penalties, reminders, rollups
from app.services.series import documents as doc_store
from app.services.series.matching import SeriesMatchingService, norm_pnr

logger = logging.getLogger(__name__)

router = APIRouter()

# Materialization floor used for the action centre until the rule engine lands and each
# contract carries its own. 80% is Air India's figure and the common market default.
DEFAULT_MATERIALIZATION_FLOOR = Decimal("80")


def _floor(contract: SeriesContract) -> Decimal:
    """The contract's own materialisation floor, or the market default."""
    if contract.materialization_floor_pct is not None:
        return Decimal(str(contract.materialization_floor_pct))
    return DEFAULT_MATERIALIZATION_FLOOR


def _scope(current_user: User):
    """Ownership filter: the contract belongs to the workspace, not to one person."""
    return SeriesContract.tenant_id == current_user.tenant_id


def _today() -> date:
    return datetime.utcnow().date()


def _choice(value: Optional[str], allowed: tuple[str, ...], *, upper: bool = True) -> Optional[str]:
    """Keep a free-text choice inside its vocabulary, or drop it.

    Returns the CANONICAL spelling, not the caller's. The first version of this endpoint
    returned the original casing while the list filter compared with `==`, so a contract
    saved as "series" was invisible to a filter for "Series". Normalising on the way in is
    what stops that being possible.
    """
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    normalised = candidate.upper() if upper else candidate.lower()
    return normalised if normalised in allowed else None


def _clean(value):
    return value.strip() or None if isinstance(value, str) else value


def _f(value) -> float:
    return float(value) if value is not None else 0.0


# ── Loading ───────────────────────────────────────────────────────────────────

_DETAIL_LOAD = (
    selectinload(SeriesContract.terms),
    selectinload(SeriesContract.allocations).selectinload(SeriesAllocation.sectors),
    selectinload(SeriesContract.allocations)
    .selectinload(SeriesAllocation.bookings)
    .selectinload(SeriesBooking.passengers),
    selectinload(SeriesContract.fare_components),
    selectinload(SeriesContract.payment_schedule).selectinload(SeriesPaymentSchedule.payments),
    selectinload(SeriesContract.deadlines),
)


async def _get_contract(contract_id: int, db: AsyncSession, current_user: User,
                        *, detail: bool = False, refresh: bool = False) -> SeriesContract:
    """`refresh` re-populates objects already in the session. Needed after a flush of new
    children: their own collections (payments, bookings, deadlines) are unloaded, and a
    lazy load under asyncpg raises MissingGreenlet."""
    query = select(SeriesContract).where(SeriesContract.id == contract_id, _scope(current_user))
    if detail:
        query = query.options(*_DETAIL_LOAD)
    if refresh:
        query = query.execution_options(populate_existing=True)
    obj = (await db.execute(query)).unique().scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Contract not found")
    return obj


def _log(db: AsyncSession, contract: SeriesContract, current_user: User,
         event_type: str, payload: dict | None = None, **ids) -> None:
    """Append to the audit trail. Never raises — losing an event must not lose the action
    that caused it."""
    db.add(SeriesEvent(
        tenant_id=contract.tenant_id,
        contract_id=contract.id,
        allocation_id=ids.get("allocation_id"),
        booking_id=ids.get("booking_id"),
        event_type=event_type,
        payload=payload,
        actor_user_id=current_user.id,
        occurred_at=datetime.utcnow(),
    ))


# ── Child writers ─────────────────────────────────────────────────────────────

def _write_sectors(contract: SeriesContract, allocation: SeriesAllocation, rows) -> None:
    """Replace an allocation's legs. Wholesale, because a re-timed itinerary is a new set,
    not a diff."""
    allocation.sectors.clear()
    for index, row in enumerate(rows or [], start=1):
        allocation.sectors.append(SeriesSector(
            tenant_id=contract.tenant_id,
            segment_no=row.segment_no or index,
            direction=_choice(row.direction, DIRECTIONS),
            origin=(_clean(row.origin) or "").upper() or None,
            destination=(_clean(row.destination) or "").upper() or None,
            airline_code=(_clean(row.airline_code) or "").upper() or None,
            flight_number=(_clean(row.flight_number) or "").upper() or None,
            departure_at=row.departure_at,
            arrival_at=row.arrival_at,
            cabin=_clean(row.cabin),
            rbd=(_clean(row.rbd) or "").upper() or None,
            allocated_pax=row.allocated_pax,
        ))


def _write_allocations(contract: SeriesContract, rows) -> None:
    """Replace the contract's departures.

    Wholesale replace rather than merge: allocations have no stable client-side identity
    on a create, and a series regenerated for a new season is a different set of dates.
    Bookings hang off an allocation with ON DELETE CASCADE, so this is refused by the API
    once any booking exists — see `replace_allocations`.
    """
    contract.allocations.clear()
    for index, row in enumerate(rows or [], start=1):
        allocation = SeriesAllocation(
            tenant_id=contract.tenant_id,
            allocation_ref=_clean(row.allocation_ref) or f"A{index}",
            departure_date=row.departure_date,
            status=_choice(row.status, ALLOCATION_STATUSES, upper=False) or "planned",
            requested_pax=row.requested_pax,
            firmed_pax=row.firmed_pax,
            minimum_pax=row.minimum_pax,
            maximum_pax=row.maximum_pax,
        )
        contract.allocations.append(allocation)
        _write_sectors(contract, allocation, row.sectors)


def _write_fare_components(contract: SeriesContract, rows) -> None:
    contract.fare_components.clear()
    for index, row in enumerate(rows or [], start=0):
        code = _choice(row.component_code, COMPONENT_CODES)
        if not code:
            continue
        contract.fare_components.append(SeriesFareComponent(
            tenant_id=contract.tenant_id,
            allocation_id=row.allocation_id,
            component_code=code,
            label=_clean(row.label),
            amount_per_pax=row.amount_per_pax or 0,
            is_guaranteed_until_ticketing=bool(row.is_guaranteed_until_ticketing),
            is_refundable_on_noshow=bool(row.is_refundable_on_noshow),
            sort_order=row.sort_order if row.sort_order is not None else index,
        ))


def _first_departure(contract: SeriesContract) -> date | None:
    """The date a "days before departure" instalment counts back from."""
    dates = [a.departure_date for a in contract.allocations if a.departure_date]
    return min(dates) if dates else contract.travel_from


def _write_schedule(contract: SeriesContract, rows) -> None:
    contract.payment_schedule.clear()
    anchor = _first_departure(contract)
    for index, row in enumerate(rows or [], start=1):
        due = row.due_date
        offset = getattr(row, "due_offset_days", None)
        # "Final payment 8 days before departure" with no date printed: resolve it now so
        # the instalment raises a deadline like any other.
        if due is None and offset is not None and anchor is not None:
            due = dl.resolve_offset(anchor, offset, None)
        contract.payment_schedule.append(SeriesPaymentSchedule(
            tenant_id=contract.tenant_id,
            allocation_id=row.allocation_id,
            kind=_choice(row.kind, PAYMENT_KINDS),
            seq=row.seq if row.seq is not None else index,
            due_date=due,
            amount=row.amount,
            pct=row.pct,
            pct_basis=_choice(row.pct_basis, bases.BASES),
            status=_choice(row.status, SCHEDULE_STATUSES, upper=False) or "pending",
            notes=_clean(row.notes),
            is_refundable=getattr(row, "is_refundable", None),
            due_offset_days=offset,
        ))


_CABINS = ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST")


def _write_terms(contract: SeriesContract, rows) -> None:
    """Replace the contract's priced clauses. Rows without a rule or a charge are dropped:
    a clause that says neither what it covers nor what it costs is not a term."""
    contract.terms.clear()
    for index, row in enumerate(rows or []):
        rule = _choice(row.rule_type, TERM_RULE_TYPES)
        charge = _choice(row.charge_type, TERM_CHARGE_TYPES)
        if not rule or not charge:
            continue
        low, high = row.days_before_min, row.days_before_max
        if low is not None and high is not None and low > high:
            low, high = high, low
        contract.terms.append(SeriesTerm(
            tenant_id=contract.tenant_id,
            allocation_id=row.allocation_id,
            rule_type=rule,
            scope=_choice(row.scope, TERM_SCOPES),
            phase=_choice(row.phase, TERM_PHASES) or "ANY",
            days_before_max=high,
            days_before_min=low,
            share_min_pct=row.share_min_pct,
            share_max_pct=row.share_max_pct,
            charge_type=charge,
            charge_value=row.charge_value,
            charge_basis=_choice(row.charge_basis, bases.BASES),
            cabin=_choice(row.cabin, _CABINS),
            plus_gst=bool(row.plus_gst),
            description=(_clean(row.description) or "")[:300] or None,
            source_text=(_clean(row.source_text) or "")[:1000] or None,
            source_page=row.source_page,
            sort_order=index,
        ))


# ── Money ─────────────────────────────────────────────────────────────────────

def _components_for(contract: SeriesContract, allocation_id: int | None = None):
    """The fare that applies — a departure's override when it has one, else the contract's."""
    override = [c for c in contract.fare_components if c.allocation_id == allocation_id]
    return override or [c for c in contract.fare_components if c.allocation_id is None]


def _seats(contract: SeriesContract) -> int:
    """How many seats the contract is priced over.

    Sums the per-departure denominators rather than reading `contracted_pax`, so a series
    of five weekly departures costs five departures' worth. Falls back to the header figure
    when nothing has been allocated yet, so a draft still shows a total.
    """
    total = sum(
        rollups.materialization_denominator(a.firmed_pax, a.requested_pax) or 0
        for a in contract.allocations
    )
    return total or (contract.contracted_pax or 0)


def _fare_summary(contract: SeriesContract) -> FareSummary:
    components = _components_for(contract)
    seats = _seats(contract)
    per_pax = bases.fare_per_pax(components)
    guaranteed = bases.guaranteed_total(components)
    return FareSummary(
        per_pax=_f(per_pax),
        total=_f(rollups.contract_cost(per_pax, seats)),
        seats=seats,
        guaranteed_per_pax=_f(guaranteed),
        exposed_per_pax=_f(per_pax - guaranteed),
        refundable_on_noshow_per_pax=_f(bases.refundable_on_noshow(components)),
        by_component={k: _f(v) for k, v in bases.split_by_code(components).items()},
        bases={name: _f(bases.basis_amount(components, name)) for name in bases.BASES},
    )


def _resolve_schedule_amount(row: SeriesPaymentSchedule, contract: SeriesContract) -> None:
    """Fill an instalment's amount from its percentage when only the percentage was given.

    Air France states both — "38 760.00 INR" against a 5% share — so a stated amount always
    wins. But an agency keying in "25% of net fare" must get a number out, and the base is
    what makes that possible: 25% of the net-fare total, not of the grand total.
    """
    if row.amount is not None or row.pct is None or not row.pct_basis:
        return
    components = _components_for(contract, row.allocation_id)
    per_pax = bases.basis_amount(components, row.pct_basis)
    total = rollups.contract_cost(per_pax, _seats(contract))
    row.amount = rollups.money(total * Decimal(str(row.pct)) / Decimal(100))


def _recompute_schedule(contract: SeriesContract) -> None:
    """Refresh every instalment's paid figure and status from its payments."""
    for row in contract.payment_schedule:
        _resolve_schedule_amount(row, contract)
        row.paid_amount = rollups.schedule_paid_amount(row.payments)
        row.status = rollups.schedule_status(row.amount, row.paid_amount, row.status)
        if row.status == "paid" and row.paid_on is None:
            dates = [p.paid_on for p in row.payments if p.paid_on]
            row.paid_on = max(dates) if dates else None


# ── Deadlines ─────────────────────────────────────────────────────────────────

# Types this endpoint generates from the payment schedule. Anything else on a contract was
# put there by a person and is re-resolved from its own anchor rather than regenerated.
_PAYMENT_DERIVED = {dl.TYPE_ADVANCE_DEPOSIT, dl.TYPE_DEPOSIT, dl.TYPE_FINAL_PAYMENT}
# Everything regenerated from contract data rather than kept as a person's entry:
# payments, departure, the offer's expiry (a header field) and the penalty steps (terms).
_GENERATED = _PAYMENT_DERIVED | {dl.TYPE_DEPARTURE, dl.TYPE_OPTION_EXPIRY, dl.TYPE_PENALTY_STEP}


def _advance_deposit_date(contract: SeriesContract) -> date | None:
    """When the advance deposit was actually paid — the anchor Air India firms a group on."""
    for row in contract.payment_schedule:
        if (row.kind or "") == "ADVANCE_DEPOSIT" and row.status == "paid":
            return row.paid_on or row.due_date
    return None


def _regenerate_deadlines(contract: SeriesContract) -> None:
    """Rebuild the contract's timeline, wholesale and idempotently.

    Preserves two things a person may have done by hand: a `stated_date` they typed (the
    airline's own date outranks any offset we compute) and a `met`/`waived` status (asking
    somebody to redo settled work is worse than a stale row).
    """
    deposit_on = _advance_deposit_date(contract)
    existing = list(contract.deadlines)

    # Specs a person entered — re-resolved, not regenerated, so editing a departure date
    # moves the D-30 name list with it.
    manual = [
        dl.DeadlineSpec(
            deadline_type=row.deadline_type,
            anchor=row.anchor,
            offset_days=row.offset_days,
            offset_hours=row.offset_hours,
            stated_date=row.stated_date,
            action_required=row.action_required,
            allocation_id=row.allocation_id,
        )
        for row in existing
        if (row.deadline_type or "") not in _GENERATED
    ]

    built: list[dl.BuiltDeadline] = []

    if contract.option_expires_on:
        built += dl.build_all(
            [dl.DeadlineSpec(deadline_type=dl.TYPE_OPTION_EXPIRY, anchor=dl.ANCHOR_CONTRACT_DATE,
                             stated_date=contract.option_expires_on)],
            contract_date=contract.contract_date,
        )

    # Contract-level instalments carry their own stated dates and need no departure.
    built += dl.build_all(
        [s for s in dl.specs_from_payment_schedule(contract.payment_schedule) if s.allocation_id is None],
        contract_date=contract.contract_date,
        advance_deposit_date=deposit_on,
    )

    for allocation in contract.allocations:
        departure_at = min(
            (s.departure_at for s in allocation.sectors if s.departure_at),
            default=None,
        )
        specs = [s for s in manual if s.allocation_id == allocation.id]
        specs += [
            s for s in dl.specs_from_payment_schedule(contract.payment_schedule)
            if s.allocation_id == allocation.id
        ]
        specs.append(dl.departure_spec(allocation.id))
        # The last day each cancellation band still applies. Contract-wide terms apply to
        # every departure, so each departure gets its own steps against its own date.
        applicable = [t for t in contract.terms if t.allocation_id in (None, allocation.id)]
        for step in penalties.penalty_step_specs(applicable, cabin=contract.cabin):
            specs.append(dl.DeadlineSpec(
                deadline_type=dl.TYPE_PENALTY_STEP,
                anchor=dl.ANCHOR_DEPARTURE,
                offset_days=step.offset_days,
                action_required=step.action_required,
                allocation_id=allocation.id,
            ))
        built += dl.build_all(
            specs,
            departure_date=allocation.departure_date,
            departure_at=departure_at,
            contract_date=contract.contract_date,
            advance_deposit_date=deposit_on,
        )

    # Contract-level manual deadlines (no allocation) resolve against the travel window.
    built += dl.build_all(
        [s for s in manual if s.allocation_id is None],
        departure_date=contract.travel_from,
        contract_date=contract.contract_date,
        advance_deposit_date=deposit_on,
    )

    fresh, stale = dl.merge_preserving_overrides(built, existing)
    by_identity = {dl.row_identity(r): r for r in existing}

    for row in stale:
        contract.deadlines.remove(row)

    for item in fresh:
        key = dl.row_identity(item)
        current = by_identity.get(key)
        if current is None:
            contract.deadlines.append(SeriesDeadline(
                tenant_id=contract.tenant_id, **item.as_columns()
            ))
            continue
        for field, value in item.as_columns().items():
            setattr(current, field, value)


# ── Read decoration ───────────────────────────────────────────────────────────

def _read_schedule(row: SeriesPaymentSchedule, today: date) -> ScheduleRead:
    out = ScheduleRead.model_validate(row)
    out.outstanding = round(_f(row.amount) - _f(row.paid_amount), 2)
    out.is_overdue = rollups.is_overdue(row.due_date, today, row.status)
    out.days_remaining = rollups.days_until(row.due_date, today)
    return out


def _read_deadline(row: SeriesDeadline, today: date) -> DeadlineRead:
    out = DeadlineRead.model_validate(row)
    out.urgency = rollups.deadline_urgency(row.effective_date, today, row.status)
    out.days_remaining = rollups.days_until(row.effective_date, today)
    return out


def _read_contract(contract: SeriesContract, today: date,
                   *, deadlines=None, schedule=None) -> ContractRead:
    """List shape, with the two figures the list screen exists to show: what is due next
    and how much money is late."""
    out = ContractRead.model_validate(contract)
    open_deadlines = [
        _read_deadline(d, today) for d in (deadlines or [])
        if (d.status or "open") == "open" and d.effective_date
    ]
    open_deadlines.sort(key=lambda d: d.effective_date)
    out.next_deadline = open_deadlines[0] if open_deadlines else None

    rows = [_read_schedule(s, today) for s in (schedule or [])]
    out.amount_due = round(sum(r.outstanding for r in rows if r.status not in ("paid", "waived")), 2)
    out.overdue_count = sum(1 for r in rows if r.is_overdue)
    return out


# ── Contract CRUD ─────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ContractRead])
async def list_contracts(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    contract_type: Optional[str] = None,
    contract_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(SeriesContract)
        .where(_scope(current_user))
        .options(
            selectinload(SeriesContract.deadlines),
            selectinload(SeriesContract.payment_schedule).selectinload(SeriesPaymentSchedule.payments),
        )
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(
            SeriesContract.contract_number.ilike(term),
            SeriesContract.group_reference.ilike(term),
            SeriesContract.group_name.ilike(term),
            SeriesContract.agent_name.ilike(term),
            SeriesContract.airline_name.ilike(term),
            SeriesContract.airline_code.ilike(term),
        ))
    # Compared against the canonical spelling the writer stored, so a filter for "Series"
    # and a contract saved as "series" cannot miss each other.
    kind = _choice(contract_type, CONTRACT_TYPES)
    if kind:
        query = query.where(SeriesContract.contract_type == kind)
    state = _choice(contract_status, CONTRACT_STATUSES, upper=False)
    if state:
        query = query.where(SeriesContract.status == state)

    query = query.order_by(SeriesContract.id.desc()).offset(skip).limit(limit)
    rows = (await db.execute(query)).unique().scalars().all()

    today = _today()
    return [
        _read_contract(c, today, deadlines=c.deadlines, schedule=c.payment_schedule)
        for c in rows
    ]


@router.post("/", response_model=ContractDetail, status_code=status.HTTP_201_CREATED)
async def create_contract(
    payload: ContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a contract, optionally with its whole graph in one call.

    The stepped form submits everything at once, but every child is optional so step one
    alone saves a draft.
    """
    contract = SeriesContract(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        contract_type=_choice(payload.contract_type, CONTRACT_TYPES),
        contract_number=_clean(payload.contract_number),
        group_reference=_clean(payload.group_reference),
        group_name=_clean(payload.group_name),
        source_type=_choice(payload.source_type, SOURCE_TYPES),
        agent_name=_clean(payload.agent_name),
        airline_code=(_clean(payload.airline_code) or "").upper() or None,
        airline_name=_clean(payload.airline_name),
        currency=(_clean(payload.currency) or "INR").upper(),
        contracted_pax=payload.contracted_pax,
        minimum_pax=payload.minimum_pax,
        cabin=_clean(payload.cabin),
        contract_date=payload.contract_date,
        travel_from=payload.travel_from,
        travel_to=payload.travel_to,
        status=_choice(payload.status, CONTRACT_STATUSES, upper=False) or "draft",
        notes=_clean(payload.notes),
        **_extra_header(payload.model_dump(exclude_unset=True)),
    )
    _sync_agent_name(contract)

    # Refuse before anything is written: a PNR already filed elsewhere would fail the
    # unique constraint halfway through the save and lose the whole contract.
    pnrs = [norm_pnr(b.pnr) for b in (payload.bookings or []) if norm_pnr(b.pnr)]
    if len(set(pnrs)) != len(pnrs):
        raise HTTPException(status_code=400, detail="The same PNR is entered twice.")
    if pnrs:
        clash = (await db.execute(
            select(SeriesBooking.pnr).where(
                SeriesBooking.tenant_id == current_user.tenant_id, SeriesBooking.pnr.in_(pnrs),
            )
        )).scalars().first()
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"PNR {clash} is already attached to another contract.",
            )

    document = None
    if payload.document_id:
        document = await _get_document(payload.document_id, db, current_user)
        if document.contract_id is not None:
            raise HTTPException(
                status_code=409,
                detail="This document has already been saved as a contract. Open that contract instead.",
            )

    db.add(contract)

    # Children are written while the contract is still pending: its collections start
    # empty in memory. Flushing first would make them unloaded, and touching them would
    # attempt a lazy load, which async sessions cannot do. The FKs are filled on flush.
    _write_allocations(contract, payload.allocations)
    _write_fare_components(contract, payload.fare_components)
    _write_schedule(contract, payload.payment_schedule)
    _write_terms(contract, payload.terms)
    await db.flush()  # allocations need ids before deadlines can point at them
    contract = await _get_contract(contract.id, db, current_user, detail=True, refresh=True)

    _add_created_deadlines(contract, payload.deadlines)
    _add_created_bookings(contract, payload.bookings)
    if document is not None:
        document.contract_id = contract.id
    await db.flush()
    contract = await _get_contract(contract.id, db, current_user, detail=True, refresh=True)

    _recompute_schedule(contract)
    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "CONTRACT_CREATED", {
        "contract_type": contract.contract_type, "contract_number": contract.contract_number,
        "document_id": payload.document_id,
    })

    # A contract is very often written after its tickets already exist, so match
    # immediately rather than showing a zeroed rollup until someone presses the button.
    # Best-effort: a matching failure must not lose the contract.
    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass

    await db.flush()
    try:
        await reminders.sync_tenant(db, current_user.tenant_id, today=_today(), contract_id=contract.id)
    except Exception:  # noqa: BLE001 — a reminder must never cost the contract
        logger.exception("series reminders failed after create contract=%s", contract.id)

    await db.commit()
    return await _detail(contract.id, db, current_user)


_EXTRA_TEXT = ("supplier_ref", "baggage_allowance", "event_name")
_EXTRA_OTHER = ("option_expires_on", "materialization_floor_pct", "foc_per_paid")


def _extra_header(data: dict) -> dict:
    """The header fields added with document reading, cleaned the way the rest are."""
    out = {}
    for key in _EXTRA_TEXT:
        if key in data:
            out[key] = _clean(data[key])
    for key in _EXTRA_OTHER:
        if key in data:
            out[key] = data[key]
    return out


def _add_created_deadlines(contract: SeriesContract, rows) -> None:
    """Deadlines sent with a new contract.

    An offset with no printed date is a rule — "names 30 days before departure" — and is
    repeated on every departure so a series gets one per date. A printed date is a fact
    about one date, so it goes on the contract (or on the only departure there is).
    """
    single = contract.allocations[0].id if len(contract.allocations) == 1 else None
    for row in rows or []:
        kind = _choice(row.deadline_type, DEADLINE_TYPES)
        if not kind or kind in _GENERATED:
            continue
        if row.offset_days is None and row.offset_hours is None and row.stated_date is None:
            continue
        anchor = _choice(row.anchor, DEADLINE_ANCHORS) or dl.ANCHOR_DEPARTURE
        if row.stated_date is None and anchor == dl.ANCHOR_DEPARTURE and contract.allocations:
            targets = [a.id for a in contract.allocations]
        else:
            targets = [row.allocation_id or single]
        for allocation_id in targets:
            contract.deadlines.append(SeriesDeadline(
                tenant_id=contract.tenant_id,
                allocation_id=allocation_id,
                deadline_type=kind,
                anchor=anchor,
                offset_days=row.offset_days,
                offset_hours=row.offset_hours,
                stated_date=row.stated_date,
                action_required=_clean(row.action_required),
            ))


def _add_created_bookings(contract: SeriesContract, rows) -> None:
    """PNRs and name lists sent with a new contract, placed on their departure by position."""
    if not rows or not contract.allocations:
        return
    for row in rows:
        pnr = norm_pnr(row.pnr)
        if not pnr:
            continue
        index = row.allocation_index if 0 <= (row.allocation_index or 0) < len(contract.allocations) else 0
        allocation = contract.allocations[index]
        booking = SeriesBooking(
            tenant_id=contract.tenant_id,
            contract_id=contract.id,
            allocation_id=allocation.id,
            pnr=pnr,
            airline_pnr=(_clean(row.airline_pnr) or "").upper() or None,
            tour_code=(_clean(row.tour_code) or "").upper() or None,
            booking_status="held",
            seats=row.seats,
        )
        for pax in row.passengers or []:
            if not (_clean(pax.first_name) or _clean(pax.last_name)):
                continue
            pax_type = _choice(pax.pax_type, PAX_TYPES) or "ADT"
            occupies, counts = rollups.seat_flags(pax_type)
            booking.passengers.append(SeriesPassenger(
                tenant_id=contract.tenant_id,
                contract_id=contract.id,
                allocation_id=allocation.id,
                title=_clean(pax.title),
                first_name=_clean(pax.first_name),
                middle_name=_clean(pax.middle_name),
                last_name=_clean(pax.last_name),
                pax_type=pax_type,
                occupies_seat=occupies,
                counts_for_materialization=counts,
                date_of_birth=pax.date_of_birth,
                gender=_clean(pax.gender),
                nationality=_clean(pax.nationality),
                passport_number=(_clean(pax.passport_number) or "").upper() or None,
                passport_expiry=pax.passport_expiry,
                name_status="named",
            ))
        allocation.bookings.append(booking)


def _sync_agent_name(contract: SeriesContract) -> None:
    """On an AIRLINE contract the airline IS the counterparty.

    The form drops the agent field entirely in that case, so mirror the airline into
    `agent_name` — that keeps the counterparty column populated and lets reporting group by
    agent uniformly across both kinds of contract.
    """
    if (contract.source_type or "") == "AIRLINE":
        contract.agent_name = contract.airline_name


# Literal routes must stay above /{contract_id}; declared after it, "match" would be
# captured as a contract_id and fail int validation.
@router.post("/match", response_model=MatchResult)
async def match_contracts(
    contract_id: Optional[int] = Query(None, description="Limit to one contract; omit for all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recompute issuance and margin from the tickets issued on each contract's PNRs."""
    summary = await SeriesMatchingService.run(
        db, tenant_id=current_user.tenant_id, contract_id=contract_id,
    )
    await db.commit()
    return MatchResult(
        contracts=summary.contracts, allocations=summary.allocations,
        bookings=summary.bookings, pending=summary.pending, partial=summary.partial,
        complete=summary.complete, over_issued=summary.over_issued,
        tickets_matched=summary.tickets_matched, amount_matched=summary.amount_matched,
        margin_total=summary.margin_total,
    )


@router.get("/action-center", response_model=ActionCenter)
async def action_center(
    horizon_days: int = Query(14, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What needs attention, computed live.

    Nothing here is stored. With no scheduler in the stack a materialised action list would
    be as stale as the last time somebody happened to trigger it; a query against today's
    date cannot be.
    """
    today = _today()
    try:
        if await reminders.sync_tenant(db, current_user.tenant_id, today=today):
            await db.commit()
    except Exception:  # noqa: BLE001 — reminders are a courtesy; the action centre is not
        await db.rollback()
        logger.exception("series reminders scan failed tenant=%s", current_user.tenant_id)
    contracts = (await db.execute(
        select(SeriesContract)
        .where(_scope(current_user), SeriesContract.status.notin_(("cancelled", "closed")))
        .options(
            selectinload(SeriesContract.deadlines),
            selectinload(SeriesContract.payment_schedule).selectinload(SeriesPaymentSchedule.payments),
            selectinload(SeriesContract.allocations),
        )
    )).unique().scalars().all()

    out = ActionCenter(as_of=today)
    overdue_total = 0.0

    def place(item: ActionItem) -> None:
        nonlocal overdue_total
        if item.urgency == "overdue":
            out.overdue.append(item)
            overdue_total += item.amount or 0.0
        elif item.urgency == "today":
            out.today.append(item)
        elif item.urgency == "critical":
            out.critical.append(item)
        elif item.urgency == "soon" and (item.days_remaining or 0) <= horizon_days:
            out.soon.append(item)

    for contract in contracts:
        header = {
            "contract_id": contract.id,
            "contract_number": contract.contract_number,
            "group_name": contract.group_name,
            "airline_code": contract.airline_code,
        }

        for row in contract.deadlines:
            if (row.status or "open") != "open" or not row.effective_date:
                continue
            # Departure is a milestone, not a task. Listing it would put an item nobody can
            # action at the top of the list on the busiest week.
            if (row.deadline_type or "") == dl.TYPE_DEPARTURE:
                continue
            place(ActionItem(
                **header, kind="deadline",
                label=row.action_required or (row.deadline_type or "Deadline"),
                due_date=row.effective_date,
                urgency=rollups.deadline_urgency(row.effective_date, today, row.status),
                days_remaining=rollups.days_until(row.effective_date, today),
            ))

        for row in contract.payment_schedule:
            if (row.status or "") in ("paid", "waived") or not row.due_date:
                continue
            outstanding = _f(row.amount) - _f(row.paid_amount)
            place(ActionItem(
                **header, kind="payment",
                label=f"{(row.kind or 'Payment').replace('_', ' ').title()} due",
                due_date=row.due_date,
                urgency=(
                    "overdue" if rollups.is_overdue(row.due_date, today, row.status)
                    else rollups.deadline_urgency(row.due_date, today, None)
                ),
                days_remaining=rollups.days_until(row.due_date, today),
                amount=round(outstanding, 2),
            ))

        floor = _floor(contract)
        for allocation in contract.allocations:
            if allocation.materialization_pct is None:
                continue
            meets = rollups.meets_materialization(
                Decimal(str(allocation.materialization_pct)), floor
            )
            if meets is False:
                out.below_materialization.append(ActionItem(
                    **header, kind="materialization",
                    label=(
                        f"{allocation.materialization_pct}% materialised, "
                        f"below {floor.normalize()}%"
                    ),
                    due_date=allocation.departure_date,
                    urgency=rollups.deadline_urgency(allocation.departure_date, today, None),
                    days_remaining=rollups.days_until(allocation.departure_date, today),
                ))

    for bucket in (out.overdue, out.today, out.critical, out.soon, out.below_materialization):
        bucket.sort(key=lambda i: (i.due_date or date.max))
    out.total_overdue_amount = round(overdue_total, 2)
    return out


# ── Documents: upload, AI reading, download ───────────────────────────────────
#
# Declared above /{contract_id} for the same reason as /match: a literal first segment must
# never be offered to the int-typed contract route.

async def _get_document(document_id: int, db: AsyncSession, current_user: User) -> SeriesDocument:
    document = (await db.execute(
        select(SeriesDocument).where(
            SeriesDocument.id == document_id,
            SeriesDocument.tenant_id == current_user.tenant_id,
        )
    )).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


async def _read_upload(file: UploadFile) -> bytes:
    """The uploaded bytes, refused unless they are a PDF of a sane size."""
    name = (file.filename or "").lower()
    if not name.endswith(".pdf") and (file.content_type or "") != "application/pdf":
        raise HTTPException(status_code=415, detail="Upload the contract as a PDF.")
    limit = settings.SERIES_DOC_MAX_MB * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"The PDF is larger than {settings.SERIES_DOC_MAX_MB} MB.")
    if not content:
        raise HTTPException(status_code=400, detail="The file is empty.")
    # Checked on the bytes, not the name: a renamed .docx fails here with a clear message
    # instead of deep inside the PDF reader.
    if b"%PDF" not in content[:1024]:
        raise HTTPException(status_code=415, detail="This file is not a PDF, whatever its name says.")
    return content


async def _store_document(content: bytes, file: UploadFile, doc_kind: str | None,
                          db: AsyncSession, current_user: User,
                          contract_id: int | None = None) -> tuple[SeriesDocument, Optional[SeriesDocument]]:
    """Write the row, then the file, then point the row at the file. The id comes first
    because it is part of the storage path."""
    digest = hashlib.sha256(content).hexdigest()
    duplicate = (await db.execute(
        select(SeriesDocument)
        .where(SeriesDocument.tenant_id == current_user.tenant_id, SeriesDocument.sha256 == digest)
        .order_by(SeriesDocument.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    file_name = (file.filename or "contract.pdf").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:255]
    document = SeriesDocument(
        tenant_id=current_user.tenant_id,
        contract_id=contract_id,
        created_by_id=current_user.id,
        doc_kind=_choice(doc_kind, DOCUMENT_KINDS) or "CONTRACT",
        file_name=file_name,
        content_type="application/pdf",
        file_size=len(content),
        sha256=digest,
        extraction_status="stored",
    )
    db.add(document)
    await db.flush()
    locator, _remote = await doc_store.store(
        content, tenant_id=current_user.tenant_id, document_id=document.id,
        file_name=file_name, content_type="application/pdf",
    )
    document.file_url = locator
    return document, duplicate


async def _run_extraction(document: SeriesDocument, content: bytes, db: AsyncSession,
                          current_user: User) -> Optional[dict]:
    """Read the document with the AI and keep the draft on the row.

    A failure is recorded on the row and returned as a draftless response rather than a
    500: the PDF is stored either way, and the person can still fill the form by hand.
    """
    from app.services import ai_client
    from app.services.series import extraction

    if not settings.OPENAI_API_KEY:
        document.extraction_status = "skipped"
        document.extraction_error = (
            "AI reading is not configured on this server (OPENAI_API_KEY is unset). The PDF is "
            "saved — fill the contract in by hand."
        )
        return None

    document.extraction_status = "processing"
    try:
        result = await extraction.extract(content, file_name=document.file_name, today=_today())
    except extraction.ExtractionError as exc:
        document.extraction_status = "failed"
        document.extraction_error = str(exc)[:1000]
        return None
    except ai_client.FatalAIError as exc:
        logger.error("series-extract auth failure document=%s: %s", document.id, exc)
        document.extraction_status = "failed"
        document.extraction_error = "The AI service rejected this server's credentials. Ask an administrator to check the OpenAI key."
        return None
    except Exception as exc:  # noqa: BLE001 — provider outages, timeouts, rate limits
        logger.exception("series-extract failed document=%s", document.id)
        document.extraction_status = "failed"
        document.extraction_error = (
            f"The AI service did not answer ({type(exc).__name__}). Try again in a minute, or "
            f"fill the form by hand — the PDF is saved."
        )
        return None

    draft = result.draft.as_dict()
    document.extraction_status = "done"
    document.extraction_error = None
    document.extraction_json = draft
    document.extraction_model = result.model
    document.extraction_ms = result.duration_ms
    document.page_count = result.page_count
    document.scanned_pages = result.scanned_pages
    document.extracted_at = datetime.utcnow()
    if result.draft.doc_kind and document.doc_kind == "CONTRACT":
        document.doc_kind = result.draft.doc_kind

    # The read can take a minute; someone who navigated away finds it in the bell.
    header = draft.get("header") or {}
    label = header.get("contract_number") or header.get("group_name") or document.file_name
    await notify(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        category="series",
        kind="document_read",
        severity="success",
        title=f"Contract read — review and save {label}"[:200],
        body=(draft.get("summary") or f"{document.file_name} has been read. Check the fields and save the contract."),
        link=f"/vendors/series-sit-mice/new?document={document.id}",
        source_type="series_document",
        source_id=document.id,
        dedupe_key=f"series:document:{document.id}:read:{document.extracted_at.isoformat()}",
    )
    return draft


@router.post("/documents", response_model=ExtractionResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    doc_kind: Optional[str] = Form(None),
    extract: bool = Form(True),
    contract_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store a contract PDF and, by default, read it into a draft for the review form.

    The file is stored before it is read, and committed whatever the reading does, so an AI
    failure never costs the upload. Reading is synchronous — a few pages take well under a
    minute — and its outcome is also posted to the uploader's notifications.
    """
    content = await _read_upload(file)
    if contract_id is not None:
        await _get_contract(contract_id, db, current_user)
    document, duplicate = await _store_document(content, file, doc_kind, db, current_user, contract_id)
    await db.commit()

    draft = await _run_extraction(document, content, db, current_user) if extract else None
    await db.commit()
    await db.refresh(document)
    return ExtractionResponse(
        document=_read_document(document),
        draft=draft,
        duplicate_of=_read_document(duplicate) if duplicate is not None else None,
    )


@router.get("/documents/{document_id}", response_model=ExtractionResponse)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A stored document and the draft it was read into — how the review is resumed."""
    document = await _get_document(document_id, db, current_user)
    return ExtractionResponse(document=_read_document(document), draft=document.extraction_json)


@router.post("/documents/{document_id}/extract", response_model=ExtractionResponse)
async def reextract_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read a stored document again — after a failure, or to discard a bad draft."""
    document = await _get_document(document_id, db, current_user)
    if not document.file_url:
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    try:
        content = await doc_store.load(document.file_url)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    draft = await _run_extraction(document, content, db, current_user)
    await db.commit()
    await db.refresh(document)
    return ExtractionResponse(document=_read_document(document), draft=draft)


@router.get("/documents/{document_id}/file")
async def download_document(
    document_id: int,
    download: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The PDF itself, streamed through the API so a locally-stored fallback file and a GCS
    blob look the same to the browser, and neither is ever publicly addressable."""
    document = await _get_document(document_id, db, current_user)
    if not document.file_url:
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    try:
        content = await doc_store.load(document.file_url)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    disposition = "attachment" if download else "inline"
    safe_name = document.file_name.replace('"', "")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = await _get_document(document_id, db, current_user)
    locator = document.file_url
    await db.delete(document)
    await db.commit()
    try:
        await doc_store.delete(locator)
    except Exception:  # noqa: BLE001 — an orphaned blob is cheaper than a failed delete
        logger.warning("series document blob delete failed locator=%s", locator)


async def _detail(contract_id: int, db: AsyncSession, current_user: User) -> ContractDetail:
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    today = _today()
    out = ContractDetail.model_validate(contract)
    out.allocations = [AllocationRead.model_validate(a) for a in contract.allocations]
    out.fare_components = [FareComponentRead.model_validate(c) for c in contract.fare_components]
    out.payment_schedule = [_read_schedule(s, today) for s in contract.payment_schedule]
    out.deadlines = [_read_deadline(d, today) for d in contract.deadlines]
    out.fare_summary = _fare_summary(contract)

    base = _read_contract(contract, today, deadlines=contract.deadlines,
                          schedule=contract.payment_schedule)
    out.next_deadline = base.next_deadline
    out.amount_due = base.amount_due
    out.overdue_count = base.overdue_count

    out.terms = [_read_term(t) for t in contract.terms]
    out.exposure = _exposure(contract, today)
    documents = (await db.execute(
        select(SeriesDocument)
        .where(SeriesDocument.contract_id == contract.id,
               SeriesDocument.tenant_id == current_user.tenant_id)
        .order_by(SeriesDocument.created_at.desc())
    )).scalars().all()
    out.documents = [_read_document(d) for d in documents]
    return out


def _read_term(term: SeriesTerm) -> TermRead:
    out = TermRead.model_validate(term)
    out.summary = penalties.describe(term)
    return out


def _read_document(document: SeriesDocument) -> DocumentRead:
    out = DocumentRead.model_validate(document)
    out.stored_remotely = not file_store.is_local(document.file_url)
    return out


def _exposure(contract: SeriesContract, today: date) -> list[ExposureRead]:
    """Whole-departure cancellation cost, today, for every departure still to fly.

    A contract-level deposit is shared across departures in proportion to their seats — a
    forfeited deposit is money already paid, and each departure only loses its share.
    """
    if not contract.terms:
        return []
    deposit_paid = sum(
        (Decimal(str(r.paid_amount or 0)) for r in contract.payment_schedule
         if (r.kind or "") in ("ADVANCE_DEPOSIT", "DEPOSIT") and r.allocation_id is None),
        Decimal("0"),
    )
    seats_of = {
        a.id: rollups.materialization_denominator(a.firmed_pax, a.requested_pax)
        or contract.contracted_pax or 0
        for a in contract.allocations
    }
    total_seats = sum(seats_of.values()) or 1

    out: list[ExposureRead] = []
    for allocation in contract.allocations:
        if allocation.departure_date and allocation.departure_date < today:
            continue
        seats = seats_of.get(allocation.id, 0)
        own_deposit = sum(
            (Decimal(str(r.paid_amount or 0)) for r in contract.payment_schedule
             if (r.kind or "") in ("ADVANCE_DEPOSIT", "DEPOSIT") and r.allocation_id == allocation.id),
            Decimal("0"),
        )
        share = deposit_paid * Decimal(seats) / Decimal(total_seats) + own_deposit
        ticketed = bool(seats) and allocation.ticketed_pax >= seats
        result = penalties.cancellation_exposure(
            [t for t in contract.terms if t.allocation_id in (None, allocation.id)],
            _components_for(contract, allocation.id),
            departure_date=allocation.departure_date,
            today=today,
            seats=seats,
            cabin=contract.cabin,
            ticketed=ticketed,
            deposit_paid=share,
        )
        if result is None:
            continue
        out.append(ExposureRead(
            allocation_id=allocation.id,
            departure_date=allocation.departure_date,
            days_before=result.days_before,
            description=result.description,
            per_pax=_f(result.per_pax) if result.per_pax is not None else None,
            seats=result.seats,
            amount=_f(result.amount) if result.amount is not None else None,
            plus_gst=result.plus_gst,
            holds_until=result.holds_until,
            next_description=result.next_description,
            next_per_pax=_f(result.next_per_pax) if result.next_per_pax is not None else None,
        ))
    return out


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _detail(contract_id, db, current_user)


@router.patch("/{contract_id}", response_model=ContractDetail)
async def update_contract(
    contract_id: int,
    payload: ContractUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    data = payload.model_dump(exclude_unset=True)

    if "contract_type" in data:
        data["contract_type"] = _choice(data["contract_type"], CONTRACT_TYPES)
    if "source_type" in data:
        data["source_type"] = _choice(data["source_type"], SOURCE_TYPES)
    if "status" in data:
        data["status"] = _choice(data["status"], CONTRACT_STATUSES, upper=False) or contract.status
    for key in ("contract_number", "group_reference", "group_name", "agent_name",
                "airline_name", "cabin", "notes", *_EXTRA_TEXT):
        if key in data:
            data[key] = _clean(data[key])
    for key in ("airline_code", "currency"):
        if key in data and data[key]:
            data[key] = str(data[key]).strip().upper()

    for field, value in data.items():
        setattr(contract, field, value)
    _sync_agent_name(contract)

    # Travel dates and the contract date anchor every offset-based deadline, so re-resolve
    # rather than leaving a timeline that describes the old dates.
    _recompute_schedule(contract)
    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "CONTRACT_UPDATED", {"fields": sorted(data)})

    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass

    await db.commit()
    return await _detail(contract_id, db, current_user)


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await _get_contract(contract_id, db, current_user)
    # The document rows go with the contract by cascade; their files do not, so collect
    # them first and remove them once the delete has committed.
    locators = list((await db.execute(
        select(SeriesDocument.file_url).where(
            SeriesDocument.contract_id == contract.id, SeriesDocument.file_url.isnot(None),
        )
    )).scalars())
    await db.delete(contract)
    await db.commit()
    for locator in locators:
        try:
            await doc_store.delete(locator)
        except Exception:  # noqa: BLE001 — an orphaned file must not fail a finished delete
            logger.warning("series document blob delete failed locator=%s", locator)


# ── Allocations ───────────────────────────────────────────────────────────────

@router.put("/{contract_id}/allocations", response_model=ContractDetail)
async def replace_allocations(
    contract_id: int,
    payload: list[AllocationIn],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace every departure on the contract.

    Refused once any booking exists. Allocations cascade to bookings, passengers and their
    ticket rollups, so a wholesale replace after a PNR has been attached would delete real
    issuance data to apply an edit to a date — destructive in a way the caller almost
    certainly did not intend.
    """
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    if any(a.bookings for a in contract.allocations):
        raise HTTPException(
            status_code=409,
            detail=(
                "This contract already has PNRs attached. Edit the departure you mean "
                "instead — replacing all of them would delete those bookings and their "
                "issued tickets."
            ),
        )
    _write_allocations(contract, payload)
    await db.flush()
    contract = await _get_contract(contract_id, db, current_user, detail=True, refresh=True)
    _recompute_schedule(contract)
    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "ALLOCATIONS_REPLACED", {"count": len(payload)})
    await db.commit()
    return await _detail(contract_id, db, current_user)


async def _get_allocation(contract: SeriesContract, allocation_id: int) -> SeriesAllocation:
    for allocation in contract.allocations:
        if allocation.id == allocation_id:
            return allocation
    raise HTTPException(status_code=404, detail="Departure not found on this contract")


@router.patch("/{contract_id}/allocations/{allocation_id}", response_model=AllocationRead)
async def update_allocation(
    contract_id: int,
    allocation_id: int,
    payload: AllocationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    allocation = await _get_allocation(contract, allocation_id)
    data = payload.model_dump(exclude_unset=True)
    sectors = data.pop("sectors", None)

    if "status" in data:
        data["status"] = _choice(data["status"], ALLOCATION_STATUSES, upper=False) or allocation.status
    if "allocation_ref" in data:
        data["allocation_ref"] = _clean(data["allocation_ref"])
    for field, value in data.items():
        setattr(allocation, field, value)

    if payload.sectors is not None:
        _write_sectors(contract, allocation, payload.sectors)

    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "ALLOCATION_UPDATED",
         {"fields": sorted(data)}, allocation_id=allocation.id)

    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass

    await db.commit()
    await db.refresh(allocation)
    return AllocationRead.model_validate(allocation)


# ── Bookings ──────────────────────────────────────────────────────────────────

@router.post("/{contract_id}/bookings", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
async def create_booking(
    contract_id: int,
    payload: BookingIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    pnr = norm_pnr(payload.pnr)
    if not pnr:
        raise HTTPException(
            status_code=400,
            detail="PNR is required — it is how tickets are matched to this booking.",
        )
    if not payload.allocation_id:
        if len(contract.allocations) != 1:
            raise HTTPException(
                status_code=400,
                detail="Say which departure this PNR belongs to.",
            )
        allocation = contract.allocations[0]
    else:
        allocation = await _get_allocation(contract, payload.allocation_id)

    clash = (await db.execute(
        select(SeriesBooking).where(
            SeriesBooking.tenant_id == current_user.tenant_id,
            SeriesBooking.pnr == pnr,
        )
    )).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"PNR {pnr} is already attached to another contract. One PNR belongs to "
                "one contract — filing it twice would count its tickets twice."
            ),
        )

    booking = SeriesBooking(
        tenant_id=contract.tenant_id,
        contract_id=contract.id,
        allocation_id=allocation.id,
        pnr=pnr,
        airline_pnr=(_clean(payload.airline_pnr) or "").upper() or None,
        tour_code=(_clean(payload.tour_code) or "").upper() or None,
        booking_status=_choice(payload.booking_status, BOOKING_STATUSES, upper=False) or "held",
        seats=payload.seats,
    )
    db.add(booking)
    await db.flush()
    _log(db, contract, current_user, "BOOKING_ADDED", {"pnr": pnr},
         allocation_id=allocation.id, booking_id=booking.id)

    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass

    await db.commit()
    loaded = (await db.execute(
        select(SeriesBooking)
        .where(SeriesBooking.id == booking.id)
        .options(selectinload(SeriesBooking.passengers))
    )).scalar_one()
    return BookingRead.model_validate(loaded)


@router.delete("/{contract_id}/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_booking(
    contract_id: int,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await _get_contract(contract_id, db, current_user)
    booking = (await db.execute(
        select(SeriesBooking).where(
            SeriesBooking.id == booking_id,
            SeriesBooking.contract_id == contract.id,
            SeriesBooking.tenant_id == current_user.tenant_id,
        )
    )).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found on this contract")
    _log(db, contract, current_user, "BOOKING_REMOVED", {"pnr": booking.pnr},
         allocation_id=booking.allocation_id, booking_id=booking.id)
    await db.delete(booking)
    await db.flush()
    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass
    await db.commit()


@router.put("/{contract_id}/bookings/{booking_id}/passengers", response_model=BookingRead)
async def replace_passengers(
    contract_id: int,
    booking_id: int,
    payload: list[PassengerIn],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace a booking's name list.

    `occupies_seat` and `counts_for_materialization` are derived here from `pax_type` and
    never accepted from the client — they are the whole of Air India's "one child would be
    counted as one adult" rule, and a caller that got them wrong would quietly move the
    80% floor.
    """
    contract = await _get_contract(contract_id, db, current_user)
    booking = (await db.execute(
        select(SeriesBooking)
        .where(
            SeriesBooking.id == booking_id,
            SeriesBooking.contract_id == contract.id,
            SeriesBooking.tenant_id == current_user.tenant_id,
        )
        .options(selectinload(SeriesBooking.passengers))
    )).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found on this contract")

    booking.passengers.clear()
    for row in payload:
        pax_type = _choice(row.pax_type, PAX_TYPES) or "ADT"
        occupies, counts = rollups.seat_flags(pax_type)
        booking.passengers.append(SeriesPassenger(
            tenant_id=contract.tenant_id,
            contract_id=contract.id,
            allocation_id=booking.allocation_id,
            title=_clean(row.title),
            first_name=_clean(row.first_name),
            middle_name=_clean(row.middle_name),
            last_name=_clean(row.last_name),
            pax_type=pax_type,
            occupies_seat=occupies,
            counts_for_materialization=counts,
            date_of_birth=row.date_of_birth,
            gender=_clean(row.gender),
            nationality=_clean(row.nationality),
            passport_number=(_clean(row.passport_number) or "").upper() or None,
            passport_expiry=row.passport_expiry,
            name_status=_choice(row.name_status, NAME_STATUSES, upper=False) or "named",
            ticket_number=_clean(row.ticket_number),
        ))

    _log(db, contract, current_user, "PASSENGERS_REPLACED", {"count": len(payload)},
         allocation_id=booking.allocation_id, booking_id=booking.id)
    await db.flush()
    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass
    await db.commit()

    loaded = (await db.execute(
        select(SeriesBooking)
        .where(SeriesBooking.id == booking.id)
        .options(selectinload(SeriesBooking.passengers))
    )).scalar_one()
    return BookingRead.model_validate(loaded)


# ── Fare and money ────────────────────────────────────────────────────────────

@router.put("/{contract_id}/fare-components", response_model=ContractDetail)
async def replace_fare_components(
    contract_id: int,
    payload: list[FareComponentIn],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    _write_fare_components(contract, payload)
    await db.flush()
    # Instalments quoted as a percentage price off the fare, so re-resolve their amounts.
    _recompute_schedule(contract)
    _log(db, contract, current_user, "FARE_UPDATED", {"components": len(payload)})
    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass
    await db.commit()
    return await _detail(contract_id, db, current_user)


@router.put("/{contract_id}/payment-schedule", response_model=ContractDetail)
async def replace_payment_schedule(
    contract_id: int,
    payload: list[ScheduleIn],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the instalment plan.

    Refused once any payment has been recorded — payments hang off a schedule row and
    replacing the plan would delete the record of money that actually left the bank.
    """
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    if any(row.payments for row in contract.payment_schedule):
        raise HTTPException(
            status_code=409,
            detail=(
                "Payments have already been recorded against this schedule. Edit the "
                "instalment you mean instead — replacing the plan would delete them."
            ),
        )
    _write_schedule(contract, payload)
    await db.flush()
    contract = await _get_contract(contract_id, db, current_user, detail=True, refresh=True)
    _recompute_schedule(contract)
    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "SCHEDULE_REPLACED", {"instalments": len(payload)})
    await db.commit()
    return await _detail(contract_id, db, current_user)


@router.put("/{contract_id}/terms", response_model=ContractDetail)
async def replace_terms(
    contract_id: int,
    payload: list[TermIn],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the priced clauses. Penalty-step deadlines follow them."""
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    _write_terms(contract, payload)
    await db.flush()
    contract = await _get_contract(contract_id, db, current_user, detail=True, refresh=True)
    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "TERMS_REPLACED", {"terms": len(payload)})
    await db.commit()
    return await _detail(contract_id, db, current_user)


@router.post("/{contract_id}/payment-schedule/{schedule_id}/payments",
             response_model=ContractDetail, status_code=status.HTTP_201_CREATED)
async def record_payment(
    contract_id: int,
    schedule_id: int,
    payload: PaymentIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record money sent against one instalment.

    Paying the advance deposit is the moment Air India firms the group size, so a departure
    still carrying no firmed figure takes one here. That is the number the 80% floor is
    measured against, and capturing it later means measuring against the wrong denominator
    in the meantime.
    """
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    row = next((s for s in contract.payment_schedule if s.id == schedule_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Instalment not found on this contract")
    if not payload.amount or float(payload.amount) <= 0:
        raise HTTPException(status_code=400, detail="A payment needs an amount above zero.")

    db.add(SeriesPayment(
        tenant_id=contract.tenant_id,
        contract_id=contract.id,
        schedule_id=row.id,
        amount=payload.amount,
        paid_on=payload.paid_on or _today(),
        method=_clean(payload.method),
        reference=_clean(payload.reference),
        notes=_clean(payload.notes),
        created_by_id=current_user.id,
    ))
    await db.flush()
    await db.refresh(row, ["payments"])
    _recompute_schedule(contract)

    if (row.kind or "") == "ADVANCE_DEPOSIT" and row.status == "paid":
        for allocation in contract.allocations:
            if allocation.firmed_pax is None:
                allocation.firmed_pax = allocation.requested_pax
            if allocation.status == "planned":
                allocation.status = "deposit_paid"

    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "PAYMENT_RECEIVED",
         {"schedule_id": row.id, "amount": float(payload.amount), "kind": row.kind})

    try:
        await SeriesMatchingService.run(db, tenant_id=current_user.tenant_id, contract_id=contract.id)
    except Exception:  # noqa: BLE001
        pass

    await db.commit()
    return await _detail(contract_id, db, current_user)


# ── Deadlines ─────────────────────────────────────────────────────────────────

@router.post("/{contract_id}/deadlines", response_model=ContractDetail,
             status_code=status.HTTP_201_CREATED)
async def add_deadline(
    contract_id: int,
    payload: DeadlineIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a deadline the contract imposes — a name-list date, a ticketing cut-off.

    Give it an offset and an anchor and it follows the departure date wherever that moves.
    Give it the date the contract printed as well and that one wins, with the disagreement
    flagged rather than hidden.
    """
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    kind = _choice(payload.deadline_type, DEADLINE_TYPES)
    if not kind:
        raise HTTPException(
            status_code=400,
            detail=f"Deadline type must be one of: {', '.join(DEADLINE_TYPES)}",
        )
    if payload.offset_days is None and payload.offset_hours is None and payload.stated_date is None:
        raise HTTPException(
            status_code=400,
            detail="A deadline needs either an offset from an anchor or a stated date.",
        )

    contract.deadlines.append(SeriesDeadline(
        tenant_id=contract.tenant_id,
        allocation_id=payload.allocation_id,
        deadline_type=kind,
        anchor=_choice(payload.anchor, DEADLINE_ANCHORS) or dl.ANCHOR_DEPARTURE,
        offset_days=payload.offset_days,
        offset_hours=payload.offset_hours,
        stated_date=payload.stated_date,
        action_required=_clean(payload.action_required),
    ))
    await db.flush()
    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "DEADLINE_ADDED", {"deadline_type": kind})
    await db.commit()
    return await _detail(contract_id, db, current_user)


@router.patch("/{contract_id}/deadlines/{deadline_id}", response_model=ContractDetail)
async def update_deadline(
    contract_id: int,
    deadline_id: int,
    payload: DeadlineIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit one deadline — typically to mark it met, waive it, or correct the stated date."""
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    row = next((d for d in contract.deadlines if d.id == deadline_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Deadline not found on this contract")

    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        new_status = _choice(data["status"], DEADLINE_STATUSES, upper=False)
        if new_status:
            row.status = new_status
            if new_status == "met" and row.met_on is None:
                row.met_on = data.get("met_on") or _today()
    if "stated_date" in data:
        row.stated_date = data["stated_date"]
    if "offset_days" in data:
        row.offset_days = data["offset_days"]
    if "offset_hours" in data:
        row.offset_hours = data["offset_hours"]
    if "anchor" in data:
        row.anchor = _choice(data["anchor"], DEADLINE_ANCHORS) or row.anchor
    if "action_required" in data:
        row.action_required = _clean(data["action_required"])

    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "DEADLINE_UPDATED",
         {"deadline_id": deadline_id, "fields": sorted(data)})
    await db.commit()
    return await _detail(contract_id, db, current_user)


@router.post("/{contract_id}/deadlines/regenerate", response_model=ContractDetail)
async def regenerate_deadlines(
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild the timeline from the contract's current dates and schedule."""
    contract = await _get_contract(contract_id, db, current_user, detail=True)
    _regenerate_deadlines(contract)
    _log(db, contract, current_user, "DEADLINES_REGENERATED")
    await db.commit()
    return await _detail(contract_id, db, current_user)
