from datetime import date, datetime
from pydantic import BaseModel
from typing import Optional


class PaymentTerm(BaseModel):
    """One instalment of a block booking's payment schedule.

    `amount` is what the percentage works out to against the contract total. It is
    stored alongside rather than recomputed on read so the schedule still reads
    correctly after someone renegotiates the total.
    """
    due_date: Optional[str] = None      # YYYY-MM-DD
    percent: Optional[float] = None
    amount: Optional[float] = None


class SeriesContractCreate(BaseModel):
    contract_type: Optional[str] = None   # 'Series' | 'SIT' | 'MICE'
    agent_type: Optional[str] = None      # 'AIRLINE' | 'B2B'
    agent_name: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    pnr_no: Optional[str] = None
    pax_count: Optional[int] = None
    trip_type: Optional[str] = None       # 'ONE_WAY' | 'RETURN'
    date_of_travel: Optional[date] = None
    fare_per_pax: Optional[float] = None
    total_fare: Optional[float] = None
    payment_terms: Optional[list[PaymentTerm]] = None


class SeriesContractUpdate(BaseModel):
    contract_type: Optional[str] = None
    agent_type: Optional[str] = None
    agent_name: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    pnr_no: Optional[str] = None
    pax_count: Optional[int] = None
    trip_type: Optional[str] = None
    date_of_travel: Optional[date] = None
    fare_per_pax: Optional[float] = None
    total_fare: Optional[float] = None
    payment_terms: Optional[list[PaymentTerm]] = None


class SeriesContractRead(BaseModel):
    id: int
    contract_type: Optional[str] = None
    agent_type: Optional[str] = None
    agent_name: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    pnr_no: Optional[str] = None
    pax_count: Optional[int] = None
    trip_type: Optional[str] = None
    date_of_travel: Optional[date] = None
    fare_per_pax: Optional[float] = None
    total_fare: Optional[float] = None
    payment_terms: Optional[list[PaymentTerm]] = None

    # Server-owned. Written by the matching service, never accepted on input.
    tickets_issued: int = 0
    ticket_numbers: Optional[list[str]] = None
    amount_issued: float = 0
    match_status: Optional[str] = None
    last_matched_at: Optional[datetime] = None

    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ContractMatchResult(BaseModel):
    """What a matching run did — counters, not rows, like BatchRunCalculationResult."""
    contracts: int = 0
    pending: int = 0
    partial: int = 0
    complete: int = 0
    over_issued: int = 0
    tickets_matched: int = 0
    amount_matched: float = 0.0
