from pydantic import BaseModel
from typing import Optional


class CustomerCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    # The corporate this person works for; None = individual / direct. `company`
    # is derived from it and ignored on input whenever corporate_id is set.
    corporate_id: Optional[int] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None   # 'percentage' | 'fixed'
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None  # 'reseller' | 'agency'


class CustomerUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    corporate_id: Optional[int] = None   # send explicitly as null to unlink
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerRead(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    corporate_id: Optional[int] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_registered: bool = False
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class CustomerBulkCreateRow(BaseModel):
    """One row of the import wizard, after the user mapped and reviewed it.

    All-optional so a single bad row cannot 422 the batch — `first_name` is
    checked per row in the endpoint and reported against that row's number, the
    way the .xls path does. Reviewed in the browser is not validated: the
    endpoint re-checks and re-normalises everything.

    `company` is a NAME here, not an id: it is matched to Corporate Master the
    same way the .xls import matches it, so a sheet of employees links itself.
    """
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None


class CustomerBulkCreate(BaseModel):
    rows: list[CustomerBulkCreateRow]


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
    incentive_breakdown: Optional[dict] = None
    is_billed: bool = False
    billing_id: Optional[int] = None
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
