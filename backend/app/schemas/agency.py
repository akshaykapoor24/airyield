from pydantic import BaseModel
from typing import Optional, List


class AgencyCreate(BaseModel):
    name: str
    vendor_type: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = True


class AgencyUpdate(BaseModel):
    name: Optional[str] = None
    vendor_type: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class AgencyRead(BaseModel):
    id: int
    name: str
    vendor_type: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class AgencyOverviewRow(BaseModel):
    id: int
    name: str
    entity_count: int
    login_id_count: int


class AgencyFromSuppliers(BaseModel):
    """Create several agencies at once by copying details from the supplier master."""
    supplier_ids: List[int]


class AgencyFromSuppliersResult(BaseModel):
    created: int
    skipped: int
    agencies: List[AgencyRead]


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
