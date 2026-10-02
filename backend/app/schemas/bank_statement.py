from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class BankStatementRead(BaseModel):
    id: int
    bank_name: Optional[str] = None
    account_name: Optional[str] = None
    account_no: Optional[str] = None
    ifsc: Optional[str] = None
    branch: Optional[str] = None
    currency: Optional[str] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    file_name: str
    row_count: int
    duplicate_count: int
    total_deposits: float
    total_withdrawals: float
    created_at: datetime
    # How far the linking has got — computed on read, not stored.
    linked_count: int = 0
    linked_amount: float = 0
    unlinked_receipt_count: int = 0
    unlinked_receipt_amount: float = 0

    model_config = {"from_attributes": True}


class BankStatementUploadResult(BaseModel):
    statement: BankStatementRead
    inserted: int
    skipped_duplicates: int
    ignored_lines: int      # legend / totals lines under the table


class PartyRef(BaseModel):
    party_type: str          # corporate | customer | agency
    party_id: int
    name: str
    code: Optional[str] = None       # the party's Customer Code
    detail: Optional[str] = None     # an employee's company, an agency's branch
    channels: Optional[str] = None   # agency only: GDS | LCC | BOTH


class RowSuggestion(BaseModel):
    party: PartyRef
    score: float
    source: str              # history — linked this way before | name — matched on the name


class BankStatementRowRead(BaseModel):
    id: int
    statement_id: int
    line_no: Optional[int] = None
    tran_id: Optional[str] = None
    value_date: Optional[date] = None
    txn_date: Optional[date] = None
    posted_at: Optional[datetime] = None
    cheque_ref: Optional[str] = None
    remarks: str
    withdrawal: float
    deposit: float
    balance: Optional[float] = None
    direction: str
    counterparty: Optional[str] = None
    payment_mode: Optional[str] = None
    reference: Optional[str] = None
    category: str
    party: Optional[PartyRef] = None
    agency_ledger_id: Optional[int] = None
    note: Optional[str] = None
    suggestion: Optional[RowSuggestion] = None


class BankStatementDetail(BaseModel):
    statement: BankStatementRead
    rows: list[BankStatementRowRead]
    categories: dict[str, str]


class BankRowUpdate(BaseModel):
    """Every field optional; only what is SENT changes. `party_type: null` unlinks."""
    category: Optional[str] = None
    party_type: Optional[str] = None
    party_id: Optional[int] = None
    # Agency only, and only needed when it trades on both GDS and LCC — which of its
    # two accounts the receipt is posted to.
    agency_channel: Optional[str] = None
    note: Optional[str] = None


class AcceptSuggestionsResult(BaseModel):
    linked: int
    skipped_agencies: int    # agency matches are left for a click — they post to a ledger


class BilledReceivedRow(BaseModel):
    party: PartyRef
    billed: float
    invoices: int
    received: float
    receipts: int
    outstanding: float       # billed − received; negative means they paid in advance


class BilledReceivedSummary(BaseModel):
    rows: list[BilledReceivedRow]
    total_billed: float
    total_received: float
    total_outstanding: float
    # Deposits still marked as customer receipts but not linked to anyone — money in
    # that no party has been credited with yet.
    unlinked_receipt_count: int
    unlinked_receipt_amount: float
