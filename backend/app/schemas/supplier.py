from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SupplierCreate(BaseModel):
    name: str
    code: Optional[str] = None
    vendor_type: Optional[str] = None
    vendor_name: Optional[str] = None
    branch: Optional[str] = None
    branches: Optional[list] = None   # [{name: str, iata_code: str}]
    contact_phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    contact_email: Optional[str] = None
    alternate_email: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    notes: Optional[str] = None
    # Directory / member-list fields
    region_chapter: Optional[str] = None
    membership_category: Optional[str] = None
    address_1: Optional[str] = None
    address_2: Optional[str] = None
    address_3: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    telephone_mobile: Optional[str] = None
    website: Optional[str] = None
    email_address: Optional[str] = None
    alternate_email_id: Optional[str] = None
    accounts_email: Optional[str] = None
    fax_no: Optional[str] = None
    representative_1: Optional[str] = None
    representative_2: Optional[str] = None
    request_type: Optional[str] = "new"
    target_id: Optional[int] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    vendor_type: Optional[str] = None
    vendor_name: Optional[str] = None
    branch: Optional[str] = None
    branches: Optional[list] = None
    contact_phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    contact_email: Optional[str] = None
    alternate_email: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    notes: Optional[str] = None
    # Directory / member-list fields
    region_chapter: Optional[str] = None
    membership_category: Optional[str] = None
    address_1: Optional[str] = None
    address_2: Optional[str] = None
    address_3: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    telephone_mobile: Optional[str] = None
    website: Optional[str] = None
    email_address: Optional[str] = None
    alternate_email_id: Optional[str] = None
    accounts_email: Optional[str] = None
    fax_no: Optional[str] = None
    representative_1: Optional[str] = None
    representative_2: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierRead(BaseModel):
    id: int
    name: str
    code: str
    vendor_type: Optional[str]
    vendor_name: Optional[str] = None
    branch: Optional[str]
    branches: Optional[list] = None
    contact_phone: Optional[str]
    alternate_phone: Optional[str]
    contact_email: Optional[str]
    alternate_email: Optional[str]
    gst_number: Optional[str]
    pan_number: Optional[str]
    notes: Optional[str]
    # Directory / member-list fields
    region_chapter: Optional[str] = None
    membership_category: Optional[str] = None
    address_1: Optional[str] = None
    address_2: Optional[str] = None
    address_3: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    telephone_mobile: Optional[str] = None
    website: Optional[str] = None
    email_address: Optional[str] = None
    alternate_email_id: Optional[str] = None
    accounts_email: Optional[str] = None
    fax_no: Optional[str] = None
    representative_1: Optional[str] = None
    representative_2: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class SupplierSubmittedBy(BaseModel):
    id: int
    full_name: str
    email: str

    model_config = {"from_attributes": True}


class SupplierApprovalRead(BaseModel):
    id: int
    name: str
    vendor_type: Optional[str]
    vendor_name: Optional[str] = None
    branch: Optional[str]
    branches: Optional[list] = None
    contact_phone: Optional[str]
    alternate_phone: Optional[str]
    contact_email: Optional[str]
    alternate_email: Optional[str]
    gst_number: Optional[str]
    pan_number: Optional[str]
    notes: Optional[str]
    # Directory / member-list fields
    region_chapter: Optional[str] = None
    membership_category: Optional[str] = None
    address_1: Optional[str] = None
    address_2: Optional[str] = None
    address_3: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    telephone_mobile: Optional[str] = None
    website: Optional[str] = None
    email_address: Optional[str] = None
    alternate_email_id: Optional[str] = None
    accounts_email: Optional[str] = None
    fax_no: Optional[str] = None
    representative_1: Optional[str] = None
    representative_2: Optional[str] = None
    status: str
    submitted_by: SupplierSubmittedBy
    submitted_at: datetime
    reviewed_at: Optional[datetime]
    rejection_reason: Optional[str]
    request_type: str
    target_id: Optional[int]

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):
        data = {
            "id": obj.id,
            "name": obj.name,
            "vendor_type": obj.vendor_type,
            "vendor_name": obj.vendor_name,
            "branch": obj.branch,
            "branches": obj.branches,
            "contact_phone": obj.contact_phone,
            "alternate_phone": obj.alternate_phone,
            "contact_email": obj.contact_email,
            "alternate_email": obj.alternate_email,
            "gst_number": obj.gst_number,
            "pan_number": obj.pan_number,
            "notes": obj.notes,
            "region_chapter": obj.region_chapter,
            "membership_category": obj.membership_category,
            "address_1": obj.address_1,
            "address_2": obj.address_2,
            "address_3": obj.address_3,
            "city": obj.city,
            "pincode": obj.pincode,
            "telephone_mobile": obj.telephone_mobile,
            "website": obj.website,
            "email_address": obj.email_address,
            "alternate_email_id": obj.alternate_email_id,
            "accounts_email": obj.accounts_email,
            "fax_no": obj.fax_no,
            "representative_1": obj.representative_1,
            "representative_2": obj.representative_2,
            "status": obj.status,
            "submitted_by": SupplierSubmittedBy.model_validate(obj.submitted_by),
            "submitted_at": obj.submitted_at,
            "reviewed_at": obj.reviewed_at,
            "rejection_reason": obj.rejection_reason,
            "request_type": obj.request_type,
            "target_id": obj.target_supplier_id,
        }
        return cls(**data)


class SupplierApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None


class SupplierBulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
