from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class IncomeRecordRead(BaseModel):
    id: int
    ticket_id: int
    deal_id: int
    base_fare: float
    commission_amount: float
    override_amount: float
    incentive_amount: float
    total_income: float
    currency: str
    is_manual_override: bool
    is_approved: bool
    calculated_at: datetime

    model_config = {"from_attributes": True}


class IncomeOverrideRequest(BaseModel):
    total_income: float
    override_reason: str
