from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


# Allowed values (validated server-side; mirrors the String(n) column comments).
ADJUSTMENT_TYPES = {"ADM", "ACM", "Refund", "RA", "DebitNote", "CreditNote"}
ADJUSTMENT_STATUSES = {"open", "settled", "disputed", "void"}


class TicketAdjustmentCreate(BaseModel):
    ticket_id:       Optional[int]  = None
    ticket_number:   Optional[str]  = None
    type:            str
    reference_no:    Optional[str]  = None
    amount:          float          = 0
    reason:          Optional[str]  = None
    adjustment_date: Optional[date] = None
    remarks:         Optional[str]  = None
    status:          str            = "open"


class TicketAdjustmentUpdate(BaseModel):
    ticket_id:       Optional[int]  = None
    ticket_number:   Optional[str]  = None
    type:            Optional[str]  = None
    reference_no:    Optional[str]  = None
    amount:          Optional[float] = None
    reason:          Optional[str]  = None
    adjustment_date: Optional[date] = None
    remarks:         Optional[str]  = None
    status:          Optional[str]  = None


class TicketAdjustmentRead(BaseModel):
    id:              int
    tenant_id:       Optional[int]
    created_by_id:   int
    ticket_id:       Optional[int]
    ticket_number:   Optional[str]
    type:            str
    reference_no:    Optional[str]
    amount:          float
    reason:          Optional[str]
    adjustment_date: Optional[date]
    remarks:         Optional[str]
    status:          str
    source:          str
    uploaded_statement_id: Optional[str]
    created_at:      datetime
    updated_at:      datetime

    model_config = {"from_attributes": True}
