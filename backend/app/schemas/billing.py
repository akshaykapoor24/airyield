from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

from app.schemas.customer import SoldTicketRead, SoldTicketsSummary


class BillingItemInput(BaseModel):
    ticket_id: int
    additional_markup: float = 0
    discount: float = 0


class BillingCreate(BaseModel):
    billing_name: str
    period_from: date
    period_to: date
    # Agency billings only: GDS | LCC, required when the agency trades on both.
    channel: Optional[str] = None
    items: list[BillingItemInput]


class BillingUpdateItem(BaseModel):
    ticket_id: int
    additional_markup: float


class BillingUpdate(BaseModel):
    items: list[BillingUpdateItem]


class BillingLineItem(BaseModel):
    ticket_id: int
    ticket_number: Optional[str] = None
    airline_name: Optional[str] = None
    airlines_code: Optional[str] = None
    passenger: Optional[str] = None
    sector: Optional[str] = None
    ticket_date: Optional[str] = None
    base_amount: float
    markup_amount: float
    additional_markup: float
    discount: float = 0
    gst_amount: float
    total: float


class BillingRead(BaseModel):
    id: int
    customer_id: Optional[int] = None
    agency_id: Optional[int] = None
    corporate_id: Optional[int] = None
    billing_name: str
    period_from: date
    period_to: date
    billing_type: Optional[str] = None
    channel: Optional[str] = None
    total_base: float
    total_markup: float
    total_additional_markup: float
    total_gst: float
    grand_total: float
    line_items: list[BillingLineItem]
    created_at: datetime

    model_config = {"from_attributes": True}


class BillingListItem(BaseModel):
    id: int
    billing_name: str
    period_from: date
    period_to: date
    channel: Optional[str] = None
    total_base: float
    total_markup: float
    total_additional_markup: float
    total_gst: float
    grand_total: float
    item_count: int
    created_at: datetime


# ── Agency billing ───────────────────────────────────────────────────────────

class AgencyLite(BaseModel):
    """Minimal agency info returned alongside its billable tickets."""
    id: int
    name: str
    branch_name: Optional[str] = None
    city: Optional[str] = None
    # What the agency trades on. `agency_type` is gone from this row — cash or
    # credit is now per channel and lives in agency_terms.
    channels: str
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

    model_config = {"from_attributes": True}


class AgencyTicketsResponse(BaseModel):
    """An agency's tickets (tagged by statement agency) with markup/GST applied."""
    agency: AgencyLite
    tickets: list[SoldTicketRead]
    summary: SoldTicketsSummary
