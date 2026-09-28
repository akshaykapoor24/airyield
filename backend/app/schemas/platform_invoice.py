"""Platform invoices — Subscriptions → Generate invoice. See app/models/platform_invoice.py.

Inputs are deliberately loose (strings, optional fields) and validated in
services/platform_invoices.py, which words every problem for the admin — "Bill to: GSTIN
starts with 06 but the state is Delhi" beats a pydantic path like body.bill_to.gstin.
Money goes out as float: pydantic serialises Decimal as a string, and the stored figure
is already rounded to the paisa.
"""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


class BankIn(BaseModel):
    account_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    branch: Optional[str] = None
    upi_id: Optional[str] = None


class PartyIn(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = "India"
    gstin: Optional[str] = None
    pan: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class IssuerIn(PartyIn):
    bank: BankIn = BankIn()


class LineIn(BaseModel):
    description: str = ""
    sac: Optional[str] = None
    # Strings, so 0.1 × 3 is not 0.30000000000000004 before it reaches Decimal.
    quantity: str = "1"
    unit_price: str = "0"


class InvoiceCreate(BaseModel):
    invoice_date: date
    due_date: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    issuer: IssuerIn
    bill_to: PartyIn
    lines: list[LineIn] = Field(..., min_length=1, max_length=50)
    gst_rate: float = 18.0
    notes: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _dates(self) -> "InvoiceCreate":
        if self.due_date and self.due_date < self.invoice_date:
            raise ValueError("The due date can't be before the invoice date.")
        if bool(self.period_from) != bool(self.period_to):
            raise ValueError("Give the billing period both a start and an end, or neither.")
        if self.period_from and self.period_to and self.period_to < self.period_from:
            raise ValueError("The billing period ends before it starts.")
        return self


class InvoiceStatusUpdate(BaseModel):
    status: Literal["issued", "paid", "cancelled"]
    paid_at: Optional[date] = None
    payment_reference: Optional[str] = Field(None, max_length=120)
    cancel_reason: Optional[str] = Field(None, max_length=255)


class InvoiceSend(BaseModel):
    to: EmailStr
    message: Optional[str] = Field(None, max_length=2000)


class InvoiceRead(BaseModel):
    id: int
    invoice_number: str
    billed_tenant_id: Optional[int] = None
    status: str
    invoice_date: date
    due_date: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    issuer: dict
    bill_to: dict
    gst_treatment: str
    place_of_supply_code: Optional[str] = None
    place_of_supply: str = ""
    gst_rate: float
    currency: str
    line_items: list[dict]
    subtotal: float
    cgst: float
    sgst: float
    igst: float
    total_tax: float
    grand_total: float
    notes: Optional[str] = None
    paid_at: Optional[date] = None
    payment_reference: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    sent_at: Optional[datetime] = None
    sent_to: Optional[str] = None
    created_at: datetime
    # Derived: issued, unpaid and past its due date.
    overdue: bool = False

    model_config = {"from_attributes": True}


class InvoiceDraft(BaseModel):
    """What the Generate form opens with. Every field is a suggestion."""
    tenant_id: int
    # Probably, not certainly — two admins generating at once get consecutive numbers.
    next_number: str
    invoice_date: date
    due_date: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    gst_rate: float
    issuer: dict
    bill_to: dict
    lines: list[dict]
    notes: Optional[str] = None


class InvoiceSummary(BaseModel):
    """The Subscriptions table's Invoice column, per workspace."""
    count: int = 0                 # not cancelled
    unpaid_count: int = 0
    unpaid_total: float = 0.0
    overdue_count: int = 0
    last_number: Optional[str] = None
    last_status: Optional[str] = None
    last_date: Optional[date] = None
