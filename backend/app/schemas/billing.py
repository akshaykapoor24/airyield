from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class BillingItemInput(BaseModel):
    ticket_id: int
    additional_markup: float = 0


class BillingCreate(BaseModel):
    billing_name: str
    period_from: date
    period_to: date
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
    gst_amount: float
    total: float


class BillingRead(BaseModel):
    id: int
    customer_id: int
    billing_name: str
    period_from: date
    period_to: date
    billing_type: Optional[str] = None
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
    total_base: float
    total_markup: float
    total_additional_markup: float
    total_gst: float
    grand_total: float
    item_count: int
    created_at: datetime
