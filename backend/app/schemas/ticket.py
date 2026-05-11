from pydantic import BaseModel
from typing import Optional
from datetime import date


class TicketCreate(BaseModel):
    ticket_number: str
    pnr: Optional[str] = None
    airline_id: int
    booking_class: str
    travel_date: date
    issue_date: date
    passenger_name: Optional[str] = None
    origin_code: str
    destination_code: str
    base_fare: float
    taxes: float = 0
    total_fare: float
    currency: str = "USD"


class TicketRead(BaseModel):
    id: int
    ticket_number: str
    pnr: Optional[str]
    airline_id: int
    booking_class: str
    travel_date: date
    origin_code: str
    destination_code: str
    base_fare: float
    total_fare: float
    currency: str
    matched_deal_id: Optional[int]
    is_manually_matched: bool

    model_config = {"from_attributes": True}
