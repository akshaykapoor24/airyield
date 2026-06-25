from pydantic import BaseModel
from typing import Optional


class CustomerCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_no: Optional[str] = None
    markup_type: Optional[str] = None   # 'percentage' | 'fixed'
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None  # 'reseller' | 'agency'


class CustomerUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerRead(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class CustomerBulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]


class SoldTicketRead(BaseModel):
    """A ticket sold to a customer, with markup applied."""
    id: int
    ticket_number: Optional[str] = None
    airline_name: Optional[str] = None
    airlines_code: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    pax_name: Optional[str] = None
    sector: Optional[str] = None
    booking_class: Optional[str] = None
    ticket_date: Optional[str] = None
    ticket_status: Optional[str] = None
    sell_fare: Optional[float] = None
    total_amt: Optional[float] = None
    calculated_incentive: Optional[float] = None
    # computed
    base_amount: float
    markup_amount: float
    gst_amount: float
    total_with_markup: float


class SoldTicketsSummary(BaseModel):
    count: int
    total_base: float
    total_markup: float
    total_gst: float
    total_with_markup: float


class SoldTicketsResponse(BaseModel):
    customer: CustomerRead
    tickets: list[SoldTicketRead]
    summary: SoldTicketsSummary
