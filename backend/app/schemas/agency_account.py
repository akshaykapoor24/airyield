from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class LedgerEntryCreate(BaseModel):
    """A hand-posted entry. `invoice` and `reversal` are posted by the system."""
    entry_type: str                       # opening_balance | topup | receipt | refund | adjustment
    amount: float                         # always positive here; the sign is derived from entry_type
    channel: Optional[str] = None         # GDS | LCC — required when the agency trades on both
    entry_date: Optional[date] = None     # defaults to today
    payment_mode: Optional[str] = None
    reference_no: Optional[str] = None
    note: Optional[str] = None


class LedgerEntryRead(BaseModel):
    id: int
    channel: str
    entry_date: date
    entry_type: str
    amount: float
    # Running total computed on read, and accumulated PER CHANNEL — a combined
    # statement covers two separate accounts, so one shared total would be
    # arithmetic across money that never mixes.
    balance_after: float
    billing_id: Optional[int] = None
    payment_mode: Optional[str] = None
    reference_no: Optional[str] = None
    note: Optional[str] = None
    reversal_of_id: Optional[int] = None
    is_reversed: bool = False


class TermsRead(BaseModel):
    id: int
    channel: str                          # GDS | LCC
    effective_from: date
    effective_to: Optional[date] = None
    agency_type: str
    credit_limit: Optional[float] = None
    usage_percent: Optional[float] = None
    billing_cycle: str
    cycle_anchor_date: date
    note: Optional[str] = None

    model_config = {"from_attributes": True}


class CycleRead(BaseModel):
    seq: int
    period_from: date
    period_to: date
    elapsed: bool
    status: str                           # open | unbilled | billed
    billing_id: Optional[int] = None
    billing_name: Optional[str] = None
    billed_amount: Optional[float] = None


class SettlementPlan(BaseModel):
    direction: str                        # incoming (collect) | outgoing (refund)
    amount: float
    options: List[str]
    message: str


class AccountSummary(BaseModel):
    agency_id: int
    agency_name: str
    branch_name: Optional[str] = None
    agency_channels: str                  # GDS | LCC | BOTH — what the agency trades on
    channel: str                          # GDS | LCC — which account this summary is
    agency_type: Optional[str] = None
    billing_cycle: Optional[str] = None
    cycle_anchor_date: Optional[date] = None
    terms_id: Optional[int] = None
    effective_from: Optional[date] = None
    balance: float
    paid_in: float
    billed: float
    limit: Optional[float] = None
    available: Optional[float] = None
    used_percent: Optional[float] = None
    usage_threshold: Optional[float] = None
    threshold_breached: bool = False
    unbilled_exposure: float = 0
    # Always "agency": no ticket records GDS vs LCC, so this figure cannot be
    # split and both channels report the same number. The screen says so.
    unbilled_exposure_scope: str = "agency"
    is_settled: bool = True
    settlement: Optional[SettlementPlan] = None


class Blocker(BaseModel):
    code: str                             # no_terms | cycle_open | tickets_unbilled | balance_nonzero
    message: str
    settlement: Optional[SettlementPlan] = None


class SwitchPreview(BaseModel):
    can_switch: bool
    channel: str
    current_type: Optional[str] = None
    blockers: List[Blocker] = []


class SwitchRequest(BaseModel):
    """Close this channel's terms period and open a new one."""
    agency_type: str                      # cash | credit
    billing_cycle: str
    channel: Optional[str] = None         # GDS | LCC — required when the agency trades on both
    credit_limit: Optional[float] = None  # credit only
    usage_percent: Optional[float] = None # cash only
    effective_from: Optional[date] = None # defaults to today
    note: Optional[str] = None


class ChannelOpenRequest(BaseModel):
    """Start trading on a channel this agency did not trade on before."""
    channel: str                          # GDS | LCC
    agency_type: str                      # cash | credit
    billing_cycle: str
    credit_limit: Optional[float] = None  # credit only, required then
    usage_percent: Optional[float] = None # cash only
    deposit_amount: Optional[float] = None  # cash only, required then — posted as the opening topup
    effective_from: Optional[date] = None
    note: Optional[str] = None


class ChannelCloseRequest(BaseModel):
    """Stop trading on one channel. Refused unless that channel is settled."""
    channel: str                          # GDS | LCC
    effective_from: Optional[date] = None
    note: Optional[str] = None
