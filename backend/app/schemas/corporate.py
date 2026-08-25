from pydantic import BaseModel
from typing import Optional

from app.schemas.customer import SoldTicketRead, SoldTicketsSummary


class CorporateCreate(BaseModel):
    """A corporate is an organisation — `company` is its name, and it is required.

    There is deliberately no first_name / last_name / title here: those columns
    survive on the model for pre-split rows only (models/corporate.py).
    """
    company: str
    corporate_type: Optional[str] = None    # 'proprietorship' | 'private_limited' | … (api/v1/corporates.py:_CORPORATE_TYPES)
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None   # 'percentage' | 'fixed'
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None  # 'reseller' | 'agency'


class CorporateUpdate(BaseModel):
    company: Optional[str] = None
    corporate_type: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: Optional[bool] = None


class CorporateRead(BaseModel):
    id: int
    company: Optional[str] = None
    corporate_type: Optional[str] = None
    # Legacy person fields — read-only, so pre-split rows still render a name.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    gst_registered: bool = False
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class CorporateBulkCreateRow(BaseModel):
    """One row of the import wizard, after the user mapped and reviewed it.

    Every field is optional HERE so that one bad row cannot 422 the whole batch:
    `company` is checked per row in the endpoint, which reports it against that
    row's number the way the .xls path does. Reviewed in the browser is not the
    same as validated — the endpoint re-checks and re-normalises all of it.
    """
    company: Optional[str] = None
    corporate_type: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None


class CorporateBulkCreate(BaseModel):
    rows: list[CorporateBulkCreateRow]


class CorporateBulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]


class CorporateSoldTicketsResponse(BaseModel):
    corporate: CorporateRead
    tickets: list[SoldTicketRead]
    summary: SoldTicketsSummary
