from datetime import date
from pydantic import BaseModel
from typing import Optional


class IataCommissionCreate(BaseModel):
    airline_name: str
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    iata_commission_pct: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: Optional[bool] = True


class IataCommissionUpdate(BaseModel):
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    iata_commission_pct: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: Optional[bool] = None


class IataCommissionRead(BaseModel):
    id: int
    airline_name: str
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    iata_commission_pct: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
