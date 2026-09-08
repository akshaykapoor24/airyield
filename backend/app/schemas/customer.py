from pydantic import BaseModel
from typing import Optional


class CustomerCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    # The corporate this person works for; None = individual / direct. `company`
    # is derived from it and ignored on input whenever corporate_id is set.
    corporate_id: Optional[int] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    # Where they are, for place of supply. Only consulted when they have no
    # GSTIN — a GSTIN already says which state it is registered in.
    state: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None   # 'percentage' | 'fixed'
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None  # 'reseller' | 'agency'


class CustomerUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    corporate_id: Optional[int] = None   # send explicitly as null to unlink
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    state: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerRead(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    corporate_id: Optional[int] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    state: Optional[str] = None
    gst_registered: bool = False
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class CustomerBulkCreateRow(BaseModel):
    """One row of the import wizard, after the user mapped and reviewed it.

    All-optional so a single bad row cannot 422 the batch — `first_name` is
    checked per row in the endpoint and reported against that row's number, the
    way the .xls path does. Reviewed in the browser is not validated: the
    endpoint re-checks and re-normalises everything.

    `company` is a NAME here, not an id: it is matched to Corporate Master the
    same way the .xls import matches it, so a sheet of employees links itself.
    """
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gst_registered: Optional[bool] = None
    gst_no: Optional[str] = None
    pan_no: Optional[str] = None
    markup_type: Optional[str] = None
    markup_value: Optional[float] = None
    billing_type: Optional[str] = None


class CustomerBulkCreate(BaseModel):
    rows: list[CustomerBulkCreateRow]


class CustomerBulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]


class CustomerListItem(CustomerRead):
    """A row of the Employee Master / Customer Billing list.

    The counts are of tickets HARD-LINKED to this customer
    (`uploaded_tickets.customer_id`). A customer's billing screen additionally claims
    untagged tickets whose passenger name matches, and that half cannot be expressed as
    a grouped aggregate — see `services/billing_calc.py::customer_ticket_scope`. So this
    can read LOWER than the drill-down. It is exact for LCC-sourced tickets, which
    always carry the link.

    A subclass rather than two defaulted fields on CustomerRead, because the four
    endpoints that return a single customer count nothing — reporting a hard `0` there
    would be a lie rather than a default.
    """
    ticket_count: int = 0
    unbilled_ticket_count: int = 0


class RelinkRequest(BaseModel):
    """`dry_run` previews the real numbers so the confirmation can state them."""
    dry_run: bool = False


class RelinkResult(BaseModel):
    scanned: int                        # owned employees examined
    linked: int                         # corporate_id newly set
    already_linked: int
    unmatched: int                      # company text matched no corporate
    company_synced: int                 # spelling rewritten to the corporate's
    employees_filled: int               # gained at least one term
    fields_filled: dict[str, int]       # {"markup_type": 12, "billing_type": 12, …}
    unmatched_companies: list[str]      # distinct, capped — the human's to-do list
    dry_run: bool


class SoldTicketRead(BaseModel):
    """A ticket sold to a customer, with markup applied."""
    id: int
    ticket_number: Optional[str] = None
    airline_name: Optional[str] = None
    airlines_code: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    pax_name: Optional[str] = None
    sector: Optional[str] = None
    booking_class: Optional[str] = None
    ticket_date: Optional[str] = None
    ticket_status: Optional[str] = None
    sell_fare: Optional[float] = None
    total_amt: Optional[float] = None
    calculated_incentive: Optional[float] = None
    incentive_breakdown: Optional[dict] = None
    is_billed: bool = False
    billing_id: Optional[int] = None
    # How this ticket reached the party: 'link' = it explicitly names them,
    # 'name' = nobody claimed it and the passenger's name matched. Computed per row,
    # not a column — see services/billing_calc.py::ticket_matched_by.
    matched_by: Optional[str] = None
    # WHO FLEW and WHO PAYS, as stored. Both are needed on the row because the
    # screen offers to move the ticket between them: `corporate_id` set means the
    # employer is billed, cleared means the passenger is. Without these the
    # Corporate column could not show which of the two a ticket is on.
    customer_id: Optional[int] = None
    corporate_id: Optional[int] = None
    # computed
    base_amount: float
    markup_amount: float
    gst_amount: float
    # The same tax as `gst_amount`, in the heads it is charged under. Exactly one
    # side is non-zero: CGST + SGST for a supply inside one state, IGST across
    # states. All three are zero when the place of supply could not be decided,
    # and `gst_treatment` says which of those three cases this row is — a zero in
    # the CGST column never has to be guessed at.
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    gst_treatment: Optional[str] = None   # 'cgst_sgst' | 'igst' | 'unsplit'
    total_with_markup: float


class SoldTicketsSummary(BaseModel):
    count: int
    total_base: float
    total_markup: float
    total_gst: float
    total_cgst: float = 0.0
    total_sgst: float = 0.0
    total_igst: float = 0.0
    total_with_markup: float


class PlaceOfSupplyRead(BaseModel):
    """Why these rows carry the heads they do — shown, not just applied.

    A user whose CGST/SGST/IGST columns are empty needs to be told what is
    missing and where to fix it, or the screen just looks broken.
    """
    #: 'cgst_sgst' | 'igst' | 'unsplit'
    treatment: str
    decided: bool
    supplier_state: Optional[str] = None
    recipient_state: Optional[str] = None
    #: Which rung of the ladder answered — 'gstin_gstin', 'gstin_state', …
    source: str
    #: One sentence a human can act on.
    note: str


class SoldTicketsResponse(BaseModel):
    customer: CustomerRead
    tickets: list[SoldTicketRead]
    summary: SoldTicketsSummary
    place_of_supply: Optional[PlaceOfSupplyRead] = None
