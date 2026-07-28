from pydantic import BaseModel
from typing import Optional

from app.schemas.customer import SoldTicketRead, SoldTicketsSummary


class CorporateCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
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


class CorporateUpdate(BaseModel):
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
    is_active: Optional[bool] = None


class CorporateRead(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
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


class CorporateBulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]


class CorporateSoldTicketsResponse(BaseModel):
    corporate: CorporateRead
    tickets: list[SoldTicketRead]
    summary: SoldTicketsSummary
