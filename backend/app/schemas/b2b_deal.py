from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class B2BDealCreate(BaseModel):
    source_agent: Optional[str] = None
    deal_maker_name: Optional[str] = None
    deal_tag: Optional[str] = "standard"
    supplier_name: Optional[str] = None
    remark: Optional[str] = None
    airline_type: str
    airline_name: str
    valid_from: str
    valid_to: str
    contract_year: Optional[str] = None
    # No trigger_type, payout_type for B2B
    entity: Optional[str] = None
    iata_number: Optional[str] = None
    business_type: Optional[str] = None
    entity_lcc: Optional[str] = None
    login_id: Optional[str] = None
    incentive_types: Optional[list[str]] = None
    incentive_data: Optional[dict] = None
    incl_excl_types: Optional[list[str]] = None
    incl_excl_data: Optional[dict] = None
    vice_versa: Optional[dict] = None


class B2BDealResponse(BaseModel):
    id: int
    status: str
    deal_lifecycle_status: str = "draft"
    deal_tag: Optional[str] = "standard"
    source_agent: str
    deal_maker_name: Optional[str]
    supplier_name: Optional[str]
    remark: Optional[str]
    airline_type: Optional[str]
    airline_name: Optional[str]
    valid_from: Optional[date]
    valid_to: Optional[date]
    contract_year: Optional[str] = None
    entity: Optional[str]
    iata_number: Optional[str]
    business_type: Optional[str]
    entity_lcc: Optional[str]
    login_id: Optional[str]
    incentive_types: Optional[list]
    incentive_data: Optional[dict]
    incl_excl_types: Optional[list]
    incl_excl_data: Optional[dict]
    vice_versa: Optional[dict]
    tenant_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True
