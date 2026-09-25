"""Wire shapes for Series / SIT / MICE / Group contracts.

Three conventions worth knowing before reading:

  * Create and Update are separate, and Update is all-Optional, so a PATCH that mentions
    one field leaves the rest alone.
  * Anything the rollup owns — ticket counts, amounts, margin, match status — appears on
    Read only. It is never accepted on input; a client that sends it is ignored rather
    than trusted.
  * The lateness fields (`is_overdue`, `urgency`, `days_remaining`) are computed in the
    router against today's date and are not columns. There is no scheduler in this stack
    to maintain a stored one, so they are derived every time they are read. See
    `services/series/rollups.py`.
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

_READ = {"from_attributes": True}


# ── Sectors ───────────────────────────────────────────────────────────────────

class SectorIn(BaseModel):
    segment_no: Optional[int] = None
    direction: Optional[str] = None          # OUTBOUND | INBOUND
    origin: Optional[str] = None
    destination: Optional[str] = None
    airline_code: Optional[str] = None
    flight_number: Optional[str] = None
    departure_at: Optional[datetime] = None
    arrival_at: Optional[datetime] = None
    cabin: Optional[str] = None
    rbd: Optional[str] = None
    allocated_pax: Optional[int] = None


class SectorRead(SectorIn):
    id: int
    allocation_id: int
    model_config = _READ


# ── Passengers ────────────────────────────────────────────────────────────────

class PassengerIn(BaseModel):
    title: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    pax_type: Optional[str] = None           # ADT | CHD | INF_SEAT | INF_LAP
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    passport_number: Optional[str] = None
    passport_expiry: Optional[date] = None
    name_status: Optional[str] = None
    ticket_number: Optional[str] = None


class PassengerRead(PassengerIn):
    id: int
    booking_id: int
    allocation_id: int
    # Derived from pax_type by the server. Sent back so the UI can show why a lap infant
    # does not move the materialization figure, rather than leaving it to look like a bug.
    occupies_seat: bool = True
    counts_for_materialization: bool = True
    ticket_status: Optional[str] = None
    model_config = _READ


# ── Bookings ──────────────────────────────────────────────────────────────────

class BookingIn(BaseModel):
    allocation_id: Optional[int] = None
    pnr: Optional[str] = None
    airline_pnr: Optional[str] = None
    tour_code: Optional[str] = None
    booking_status: Optional[str] = None
    seats: Optional[int] = None


class BookingRead(BaseModel):
    id: int
    allocation_id: int
    pnr: str
    airline_pnr: Optional[str] = None
    tour_code: Optional[str] = None
    booking_status: Optional[str] = None
    seats: Optional[int] = None

    tickets_issued: int = 0
    ticket_numbers: Optional[list[str]] = None
    amount_issued: float = 0
    last_matched_at: Optional[datetime] = None

    passengers: list[PassengerRead] = []
    model_config = _READ


# ── Allocations ───────────────────────────────────────────────────────────────

class AllocationIn(BaseModel):
    allocation_ref: Optional[str] = None
    departure_date: Optional[date] = None
    status: Optional[str] = None
    requested_pax: Optional[int] = None
    # Set when the advance deposit is paid. Air India treats the size firmed that day as
    # "sacrosanct viz 100% of the group size", and it is the materialization denominator.
    firmed_pax: Optional[int] = None
    minimum_pax: Optional[int] = None
    maximum_pax: Optional[int] = None
    sectors: Optional[list[SectorIn]] = None


class AllocationRead(BaseModel):
    id: int
    contract_id: int
    allocation_ref: Optional[str] = None
    departure_date: Optional[date] = None
    status: Optional[str] = None
    requested_pax: Optional[int] = None
    firmed_pax: Optional[int] = None
    minimum_pax: Optional[int] = None
    maximum_pax: Optional[int] = None

    booked_pax: int = 0
    named_pax: int = 0
    ticketed_pax: int = 0
    released_pax: int = 0
    cancelled_pax: int = 0
    materialization_pct: Optional[float] = None
    amount_issued: float = 0

    sectors: list[SectorRead] = []
    bookings: list[BookingRead] = []
    model_config = _READ


# ── Fare components ───────────────────────────────────────────────────────────

class FareComponentIn(BaseModel):
    """One priced element of the contracted fare, per passenger.

    Air France's contract is four of these: net 64,600 + YR-F 249 + YR-I/YQ 19,050 +
    taxes 7,357. They are stored separately so a penalty can name the base it applies to.
    """
    allocation_id: Optional[int] = None      # None = the contract default
    component_code: Optional[str] = None     # BASE | YQ | YR_I | YR_F | TAX_STATUTORY | OT | FEE
    label: Optional[str] = None
    amount_per_pax: Optional[float] = None
    is_guaranteed_until_ticketing: Optional[bool] = None
    is_refundable_on_noshow: Optional[bool] = None
    sort_order: Optional[int] = None


class FareComponentRead(FareComponentIn):
    id: int
    contract_id: int
    model_config = _READ


class FareSummary(BaseModel):
    """The contracted fare, totalled the ways the contracts talk about it."""
    per_pax: float = 0
    total: float = 0
    seats: int = 0
    guaranteed_per_pax: float = 0
    # per_pax minus guaranteed — what a tax movement between now and ticketing can still
    # cost the agency.
    exposed_per_pax: float = 0
    refundable_on_noshow_per_pax: float = 0
    by_component: dict[str, float] = {}
    # Every named basis, priced. This is what the penalty engine will read.
    bases: dict[str, float] = {}


# ── Payment schedule ──────────────────────────────────────────────────────────

class ScheduleIn(BaseModel):
    allocation_id: Optional[int] = None
    kind: Optional[str] = None               # ADVANCE_DEPOSIT | DEPOSIT | BALANCE | FINAL_PAYMENT
    seq: Optional[int] = None
    due_date: Optional[date] = None
    amount: Optional[float] = None
    pct: Optional[float] = None
    # The base the percentage applies to. Air France's deposits are 5% and 25% of the NET
    # FARE total, not of the grand total; without this the two numbers are unexplainable.
    pct_basis: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    # False when the contract says the deposit is forfeited; None when it does not say.
    is_refundable: Optional[bool] = None
    # "N days before departure" when no date was printed. Resolved to due_date on write.
    due_offset_days: Optional[int] = None


class PaymentIn(BaseModel):
    amount: Optional[float] = None
    paid_on: Optional[date] = None
    method: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


class PaymentRead(PaymentIn):
    id: int
    schedule_id: int
    created_at: Optional[datetime] = None
    model_config = _READ


class ScheduleRead(BaseModel):
    id: int
    contract_id: int
    allocation_id: Optional[int] = None
    kind: Optional[str] = None
    seq: int = 0
    due_date: Optional[date] = None
    amount: Optional[float] = None
    pct: Optional[float] = None
    pct_basis: Optional[str] = None
    status: Optional[str] = None
    paid_amount: float = 0
    paid_on: Optional[date] = None
    notes: Optional[str] = None
    is_refundable: Optional[bool] = None
    due_offset_days: Optional[int] = None

    payments: list[PaymentRead] = []

    # Derived on read — not columns.
    outstanding: float = 0
    is_overdue: bool = False
    days_remaining: Optional[int] = None
    model_config = _READ


# ── Deadlines ─────────────────────────────────────────────────────────────────

class DeadlineIn(BaseModel):
    allocation_id: Optional[int] = None
    deadline_type: Optional[str] = None
    anchor: Optional[str] = None
    offset_days: Optional[int] = None
    # Air India's no-show cut-off is D-24 HOURS, not one day.
    offset_hours: Optional[int] = None
    # What the contract literally printed. Wins over anything computed, because that is
    # the date the airline will enforce.
    stated_date: Optional[date] = None
    status: Optional[str] = None
    met_on: Optional[date] = None
    action_required: Optional[str] = None


class DeadlineRead(BaseModel):
    id: int
    contract_id: int
    allocation_id: Optional[int] = None
    deadline_type: Optional[str] = None
    anchor: Optional[str] = None
    offset_days: Optional[int] = None
    offset_hours: Optional[int] = None
    computed_date: Optional[date] = None
    stated_date: Optional[date] = None
    effective_date: Optional[date] = None
    # True when the contract's own stated date disagrees with the offset it also printed.
    # Real contracts contain arithmetic errors and the agency has to know which one the
    # airline will act on.
    has_divergence: bool = False
    status: Optional[str] = None
    met_on: Optional[date] = None
    action_required: Optional[str] = None

    # Derived on read.
    urgency: Optional[str] = None
    days_remaining: Optional[int] = None
    model_config = _READ


# ── Terms ─────────────────────────────────────────────────────────────────────

class TermIn(BaseModel):
    """One priced clause — see models/series.py::SeriesTerm for how the window and the
    share quota read."""
    allocation_id: Optional[int] = None
    rule_type: Optional[str] = None
    scope: Optional[str] = None
    phase: Optional[str] = None
    days_before_max: Optional[int] = None
    days_before_min: Optional[int] = None
    share_min_pct: Optional[float] = None
    share_max_pct: Optional[float] = None
    charge_type: Optional[str] = None
    charge_value: Optional[float] = None
    charge_basis: Optional[str] = None
    cabin: Optional[str] = None
    plus_gst: Optional[bool] = None
    description: Optional[str] = None
    source_text: Optional[str] = None
    source_page: Optional[int] = None


class TermRead(TermIn):
    id: int
    contract_id: int
    sort_order: int = 0
    # Plain-English line, generated when the contract's own description is missing.
    summary: Optional[str] = None
    model_config = _READ


class ExposureRead(BaseModel):
    """What cancelling one whole departure would cost today — and until when."""
    allocation_id: int
    departure_date: Optional[date] = None
    days_before: Optional[int] = None
    description: Optional[str] = None
    per_pax: Optional[float] = None
    seats: int = 0
    amount: Optional[float] = None
    plus_gst: bool = False
    holds_until: Optional[date] = None
    next_description: Optional[str] = None
    next_per_pax: Optional[float] = None


# ── Documents ─────────────────────────────────────────────────────────────────

class DocumentRead(BaseModel):
    id: int
    contract_id: Optional[int] = None
    doc_kind: str = "CONTRACT"
    file_name: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    scanned_pages: Optional[int] = None
    extraction_status: str = "stored"
    extraction_error: Optional[str] = None
    extraction_model: Optional[str] = None
    extraction_ms: Optional[int] = None
    extracted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    # False when GCS was unreachable and the file fell back to this server's disk.
    stored_remotely: bool = True
    model_config = _READ


class ExtractionResponse(BaseModel):
    """The stored document plus the draft its reading produced (None when not read)."""
    document: DocumentRead
    draft: Optional[dict] = None
    # An earlier upload of the same bytes, so the reviewer can go to it instead.
    duplicate_of: Optional[DocumentRead] = None


# ── Contract ──────────────────────────────────────────────────────────────────

class BookingCreateIn(BaseModel):
    """A PNR and its name list, sent with a new contract. Departures have no ids yet on a
    create, so the booking names its departure by position."""
    allocation_index: int = 0
    pnr: Optional[str] = None
    airline_pnr: Optional[str] = None
    tour_code: Optional[str] = None
    seats: Optional[int] = None
    passengers: Optional[list[PassengerIn]] = None


class ContractCreate(BaseModel):
    contract_type: Optional[str] = None      # SERIES | SIT | MICE | GROUP
    contract_number: Optional[str] = None
    group_reference: Optional[str] = None
    group_name: Optional[str] = None
    source_type: Optional[str] = None        # AIRLINE | B2B
    agent_name: Optional[str] = None
    airline_code: Optional[str] = None
    airline_name: Optional[str] = None
    currency: Optional[str] = None
    contracted_pax: Optional[int] = None
    minimum_pax: Optional[int] = None
    cabin: Optional[str] = None
    contract_date: Optional[date] = None
    travel_from: Optional[date] = None
    travel_to: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    option_expires_on: Optional[date] = None
    supplier_ref: Optional[str] = None
    materialization_floor_pct: Optional[float] = None
    foc_per_paid: Optional[int] = None
    baggage_allowance: Optional[str] = None
    event_name: Optional[str] = None

    # The stepped form submits the whole contract at once. Children are optional so a
    # draft can be saved from step one.
    allocations: Optional[list[AllocationIn]] = None
    fare_components: Optional[list[FareComponentIn]] = None
    payment_schedule: Optional[list[ScheduleIn]] = None
    terms: Optional[list[TermIn]] = None
    # Name list, ticketing, no-show... An offset with no stated date is repeated on every
    # departure; anything with a stated date belongs to the contract as a whole.
    deadlines: Optional[list[DeadlineIn]] = None
    bookings: Optional[list[BookingCreateIn]] = None
    # The uploaded PDF this contract was read from; linked to the contract on save.
    document_id: Optional[int] = None


class ContractUpdate(BaseModel):
    contract_type: Optional[str] = None
    contract_number: Optional[str] = None
    group_reference: Optional[str] = None
    group_name: Optional[str] = None
    source_type: Optional[str] = None
    agent_name: Optional[str] = None
    airline_code: Optional[str] = None
    airline_name: Optional[str] = None
    currency: Optional[str] = None
    contracted_pax: Optional[int] = None
    minimum_pax: Optional[int] = None
    cabin: Optional[str] = None
    contract_date: Optional[date] = None
    travel_from: Optional[date] = None
    travel_to: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    option_expires_on: Optional[date] = None
    supplier_ref: Optional[str] = None
    materialization_floor_pct: Optional[float] = None
    foc_per_paid: Optional[int] = None
    baggage_allowance: Optional[str] = None
    event_name: Optional[str] = None


class ContractRead(BaseModel):
    """List shape. Deliberately excludes the children — a list of 500 contracts must not
    drag their whole graph with it."""
    id: int
    contract_type: Optional[str] = None
    contract_number: Optional[str] = None
    group_reference: Optional[str] = None
    group_name: Optional[str] = None
    source_type: Optional[str] = None
    agent_name: Optional[str] = None
    airline_code: Optional[str] = None
    airline_name: Optional[str] = None
    currency: str = "INR"
    contracted_pax: Optional[int] = None
    minimum_pax: Optional[int] = None
    cabin: Optional[str] = None
    contract_date: Optional[date] = None
    travel_from: Optional[date] = None
    travel_to: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    option_expires_on: Optional[date] = None
    supplier_ref: Optional[str] = None
    materialization_floor_pct: Optional[float] = None
    foc_per_paid: Optional[int] = None
    baggage_allowance: Optional[str] = None
    event_name: Optional[str] = None

    # Server-owned. Written by services/series/matching.py, never accepted on input.
    allocations_count: int = 0
    seats_allocated: int = 0
    seats_ticketed: int = 0
    contract_cost: float = 0
    amount_issued: float = 0
    penalty_amount: float = 0
    # sell − cost − penalties. Positive means the contract earned money, matching
    # sell_reconciliation and NOT bsp_reconciliation's inverted convention.
    margin: float = 0
    match_status: Optional[str] = None
    last_matched_at: Optional[datetime] = None

    created_at: Optional[datetime] = None

    # Derived on read, for the list screen.
    next_deadline: Optional[DeadlineRead] = None
    amount_due: float = 0
    overdue_count: int = 0
    model_config = _READ


class ContractDetail(ContractRead):
    """Everything under one contract, for the detail screen."""
    allocations: list[AllocationRead] = []
    fare_components: list[FareComponentRead] = []
    payment_schedule: list[ScheduleRead] = []
    deadlines: list[DeadlineRead] = []
    fare_summary: FareSummary = FareSummary()
    terms: list[TermRead] = []
    documents: list[DocumentRead] = []
    # Per departure: what cancelling it whole would cost today. Empty when the contract
    # carries no priceable cancellation term.
    exposure: list[ExposureRead] = []


# ── Operations ────────────────────────────────────────────────────────────────

class MatchResult(BaseModel):
    """What a matching run did — counters, not rows."""
    contracts: int = 0
    allocations: int = 0
    bookings: int = 0
    pending: int = 0
    partial: int = 0
    complete: int = 0
    over_issued: int = 0
    tickets_matched: int = 0
    amount_matched: float = 0.0
    margin_total: float = 0.0


class ActionItem(BaseModel):
    """One thing that wants attention, flattened for the action centre."""
    contract_id: int
    contract_number: Optional[str] = None
    group_name: Optional[str] = None
    airline_code: Optional[str] = None
    kind: str                                # deadline | payment
    label: str
    due_date: Optional[date] = None
    urgency: str
    days_remaining: Optional[int] = None
    amount: Optional[float] = None


class ActionCenter(BaseModel):
    """Computed live on every request. Nothing here is stored, because nothing in this
    stack would keep it up to date."""
    as_of: date
    overdue: list[ActionItem] = []
    today: list[ActionItem] = []
    critical: list[ActionItem] = []          # within 3 days
    soon: list[ActionItem] = []              # within 14 days
    total_overdue_amount: float = 0
    below_materialization: list[ActionItem] = []
