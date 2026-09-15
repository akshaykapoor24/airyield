"""Third Party API rows → `uploaded_tickets`, and the state machine in front of it.

Shaped on ``services/lcc_billing_projection`` — ONE ROW IS ONE TICKET — rather than on
``ndc_billing_projection``, whose whole roll-up half exists to attach a document-less seat or
bag line to the flight it belongs to. An aggregator bills a hotel night or a train berth on
the booking's own row and issues no separate ancillary line, so there is nothing to latch and
`ThirdPartyApi` deliberately does not carry `_RollUpMixin`.

What it takes from NDC instead is the header: a spec-driven type keeps no batch row, so the
per-upload billing state lives in ``statement_batch_billing`` keyed ``(slug, batch_id)``, and
``project_batch`` takes that header rather than a batch model.

EVERY CATEGORY BILLS. This is the only billable type whose file carries more than one product,
and each product is a line of business the agency invoices at its own markup: a hotel row
becomes an `uploaded_tickets` line with `product_category='hotel'`, and
`party_markup.markup_for` prices it at the party's hotel markup when the billing is raised.
The airline-only readers (BSP reconciliation, the income summary, deal slabs, series
contracts) filter on `product_category='air'`, so a hotel night never lands in them.

WHAT IS STILL OUT, AND WHY, is `bill_kind` — never a silent filter. A row whose product names
no billing category, a pending payment, a cancellation with nothing to bill, a refund with no
payment on this statement, or an unreadable amount each gets its own kind and its own
sentence, and KEEPS its parsed ``bill_amount`` so the worklist can say "1 visa · ₹3,280 not
billable" instead of a silent absence.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statement_batch_billing import StatementBatchBilling
from app.models.statement_row import ThirdPartyApi
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket
from app.services import billing_calc
from app.services import customer_resolver as cres
from app.services import markup_categories as mc
from app.services import tp_api_itinerary as itin
from app.services import tp_api_spec as tp

SLUG = "tp-api"

# The statuses that mean "a party has been settled for this row". Same three as everywhere.
BILLABLE_STATUSES = (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)

# ── bill_kind: what this row is, and if it is not billable, WHY ──────────────
# LCC and NDC need three values (sale/refund/payment) because there is only one way to be
# unbillable. Here there are several, and the extra ones are the feature: they are what the
# gaps view groups on, so "not billable" is never a single opaque bucket.
# `bill_kind` is String(12) — `needs_review` is exactly twelve characters.
SALE = "sale"
REFUND = "refund"
NO_CATEGORY = "no_category"     # the product names no billing category (blank, "Visa", …)
PENDING = "pending"             # booking_status Pending: nothing has settled yet
CANCELLED = "cancelled"         # cancelled with nothing to bill: nothing moved, or all refunded
NEEDS_REVIEW = "needs_review"   # refunded, but no payment for it on this statement
NO_AMOUNT = "no_amount"         # nothing on the row would parse as an amount
# LEGACY. Every non-flight row classified before hotels, trains, buses and cars billed was
# stamped this. Nothing migrates those rows — re-classifying is exactly what
# `resolve-customers` does, and running it on someone's behalf could re-point a row billing is
# already using — so the kind stays NOT BILLABLE until a Re-match, and the summary counts it
# as `needs_rematch` so the worklist can say so.
NOT_FLIGHT = "not_flight"
LEGACY_KINDS = (NOT_FLIGHT,)

BILLABLE_KINDS = (SALE, REFUND)
NOT_BILLABLE_KINDS = (NO_CATEGORY, PENDING, CANCELLED, NEEDS_REVIEW, NO_AMOUNT, NOT_FLIGHT)
BILL_KINDS = BILLABLE_KINDS + NOT_BILLABLE_KINDS

# One string per kind, IDENTICAL for every row of that kind — the same discipline as
# `customer_resolver.REASON` and `ndc_billing_projection.LATCH_REASON`, and for the same
# reason: `billing-gaps` GROUPs BY the reason, so a per-row sentence would turn forty
# cancelled rows into forty groups of one and tell the user nothing.
NOT_BILLABLE_REASON = {
    PENDING: "Payment is still pending on this booking, so nothing has settled to bill.",
    CANCELLED: ("Cancelled with nothing to bill — either nothing settled, or the vendor "
                "refunded all of it."),
    NEEDS_REVIEW: ("Refunded, but this statement shows no payment for the booking — the sale "
                   "was settled on an earlier statement, so raise the credit by hand."),
    NO_AMOUNT: "No amount on this row: neither Net Amount nor Total Paid Amount reads as a number.",
    NOT_FLIGHT: ("Classified before hotels, trains, buses and cars were billable. Press "
                 "Re-match to bill it."),
}


def no_category_reason(product: str | None) -> str:
    """Why a row with no billing category is out — one string per PRODUCT.

    There are only a handful of products on a statement, so the gaps list cannot explode the
    way a per-row sentence would, and naming the product is what lets someone see that a
    vendor has started sending a new one.
    """
    if not product:
        return ("This row does not say which product it is, so there is no category — and no "
                "markup — to bill it under.")
    return (f"{product} is not a billing category — only Flight, Hotel, Train, Bus and Car "
            "bookings are billed.")


def reason_for(kind: str | None, product: str | None) -> str | None:
    if kind == NO_CATEGORY:
        return no_category_reason(product)
    return NOT_BILLABLE_REASON.get(kind or "")


def row_category(data: dict) -> str | None:
    """The markup category slug this row bills under — 'air', 'hotel', … — or None.

    `markup_categories.category_slug` already maps every `tp_api_spec.PRODUCT_VALUES`
    spelling ("Flight" → 'air'), which is exactly what its docstring promised this day would
    need.
    """
    return mc.category_slug(tp._flat._clean((data or {}).get("product_type")))


# ── the billing base ─────────────────────────────────────────────────────────
# TWO COLUMNS, NOT ALIASES OF ONE. `net_amount` is TBO's NET — the invoice payable, what the
# agency owes. `total_paid_amount` is MakeMyTrip's tender total, which MMT itself decomposes
# into PG + wallet + coupon + cash on the same row. tp_api_spec keeps them apart deliberately
# (see its Money block), so each reads absent on the other vendor's file.
_BASE_FIELDS = ("net_amount", "total_paid_amount")

_CANCELLED_STATUSES = frozenset({"Cancelled", "Refunded"})
_PENDING_STATUS = "Pending"

# A cancellation that left less than a rupee behind is fully refunded. MMT's own figures do
# not reconcile to the paisa: ₹15,508 paid against ₹15,507.50 refunded, ₹10,770 against
# ₹10,770.98. Billing either residue would raise a 50-paise invoice or a 98-paise credit.
_NIL = Decimal("1")

# TBO'S CREDIT SERIES. A TBO statement carries no sign and no status column: a refund is a
# POSITIVE figure on a line from a different invoice series. The series is the text before the
# first "/" of INVOICE NUMBER, and it was read off a real statement, not a spec sheet:
#
#   SM / MW   sales — trains and hotels (SM), hotels and buses (MW), with the service charge,
#             convenience fee and GST on the line.
#   MZ        train CANCELLATIONS. NET is the refund and CANCELLATION FEE is IRCTC's charge,
#             and the two add up to the fare of the sale they reverse: SM/2627/701490 sold a
#             ₹390 berth (₹335 fare + ₹35.40 convenience fee + service charge);
#             MZ/2627/143655, same reference, same day, refunds ₹145 with a ₹190 fee.
#   RM        REFUND MEMOS for a booking IRCTC never confirmed. SM/2627/578753 sold ₹850 on
#             reference TBOB9214471937388143; RM/2627/30789 on the same reference refunds ₹833
#             — everything but the ₹14.74 service charge and its ₹2.21 tax.
#
# So a line in one of these series is a CREDIT, and its amount is negated. An unrecognised
# series is left as a sale, which is what every TBO line was before this existed — and if TBO
# starts a new credit series, it is one entry here.
TBO_CREDIT_SERIES = frozenset({"MZ", "RM"})
_TBO_VENDOR = tp.VENDOR_LABELS[tp.TBO]


def bill_base(data: dict) -> Decimal | None:
    """The figure on the row itself — before any credit or refund reading. None when nothing
    would parse.

    FIRST NON-ZERO, then first parsed. A plain coalesce would stop at an explicit "0.00" and
    never look at the other column — which on a mixed-vendor file (the stated goal of one
    table for both vendors) would zero out a real figure.

    None and 0 stay DIFFERENT ANSWERS: 0 is "the vendor said nothing is payable", None is "no
    cell here would parse". They get different `bill_kind`s and different copy, and collapsing
    them would hide a mis-mapped amount column behind a legitimate nil.
    """
    parsed = [v for v in (tp.to_decimal(data.get(f)) for f in _BASE_FIELDS) if v is not None]
    for v in parsed:
        if v != 0:
            return v
    return parsed[0] if parsed else None


def invoice_series(data: dict) -> str | None:
    """"MZ/2627/143655" → "MZ". None when the invoice number has no series prefix."""
    inv = tp._flat._clean((data or {}).get("invoice_number"))
    if not inv or "/" not in inv:
        return None
    return inv.split("/", 1)[0].strip().upper() or None


def is_tbo_credit(data: dict) -> bool:
    """Is this a TBO cancellation or refund-memo line? See TBO_CREDIT_SERIES."""
    return (data.get("vendor") == _TBO_VENDOR
            and invoice_series(data) in TBO_CREDIT_SERIES)


def _paid_is_a_tender_total(data: dict) -> bool:
    """Does this row's base come from a TENDER total that a refund has not been netted from?

    True for MakeMyTrip, whose Total Paid Amount is what was paid at booking and whose Refund
    Amount sits beside it. False whenever a NET figure is present — TBO's NET is already the
    payable after everything, so subtracting a refund from it would count the refund twice.
    """
    net = tp.to_decimal(data.get("net_amount"))
    return net is None or net == 0


def classify(data: dict) -> tuple[str, Decimal | None]:
    """`(bill_kind, bill_amount)` for one row. Pure.

    The amount is parsed for EVERY row, including the not-billable ones, and that is the
    point: the gaps view has to be able to say "1 visa · ₹3,280", and a count with no money
    attached is how ₹3,280 hides behind the word "1".

    THE ORDER IS THE RULE, and none of it is arbitrary:

    * CATEGORY FIRST. A "Visa" line with a perfectly good amount is still out, and "Visa is
      not a billing category" is a more useful sentence than anything about its amount. A
      BLANK product is out too, for the opposite reason from
      `ndc_billing_projection._looks_ancillary`'s default: there the fallback is "bill it on
      its own line"; here it would be "bill it at some category's markup", which is a guess
      about the price.
    * PENDING before any amount test: nothing has settled.
    * A TBO CREDIT is negated, then billed as a refund — see TBO_CREDIT_SERIES. The file's own
      sign still wins everywhere else: no status-driven negation, because inventing a credit
      from a status while the number stays positive is how a sale becomes a credit note.
    * A CANCELLED MMT booking with a refund bills what the vendor KEPT: Total Paid − Refund.
      Under a rupee is `cancelled`; a refund with no payment on the row is `needs_review`,
      because the sale it reverses is not on this statement and nothing here says which bill
      the credit belongs on.
    * `cancelled` BEFORE `no_amount` for a cancellation where nothing moved at all. It is a
      strict subset and exists only to say so precisely.
    """
    base = bill_base(data)

    if row_category(data) is None:
        return NO_CATEGORY, base

    status = tp._flat._clean(data.get("booking_status"))
    if status == _PENDING_STATUS:
        return PENDING, base

    if is_tbo_credit(data):
        if base is not None and base != 0:
            base = -abs(base)
    elif status in _CANCELLED_STATUSES:
        refund = tp.to_decimal(data.get("refund_amount"))
        if refund is not None and refund > 0 and _paid_is_a_tender_total(data):
            paid = tp.to_decimal(data.get("total_paid_amount"))
            if paid is None or paid <= 0:
                return NEEDS_REVIEW, -refund
            retained = paid - refund
            if abs(retained) < _NIL:
                return CANCELLED, Decimal("0")
            base = retained
        elif (_is_zero(data, "refund_amount")
              and _is_zero(data, "cancellation_fee")
              and _is_zero(data, "base_fare")
              and (base is None or base == 0)):
            return CANCELLED, base

    if base is None or base == 0:
        return NO_AMOUNT, base
    return (REFUND if base < 0 else SALE), base


# ── pax: how many passengers the booking bills for ───────────────────────────
# A party's FIXED markup is agreed per passenger, so the pax count is a billing input, not a
# display nicety. MakeMyTrip ships a `Pax count` column; TBO writes it onto the name ("GARIMA
# GUPTA X 6") and tp_api_spec.normalize reads it into the same field.
PAX_FILE = "file"
PAX_DEFAULT = "default"
PAX_USER = "user"
MAX_PAX = 99


def parse_pax(data: dict) -> tuple[int, str]:
    """`(pax, source)` from the statement: a whole number from 1 to MAX_PAX, or (1, 'default').

    NEVER 0. A pax of 0 would zero the row's fixed markup — a line billed at cost with nothing
    on screen to say why — so a blank, zero, fractional or unreadable cell bills as one
    passenger and says it defaulted, which the worklist shows and a human can correct.
    """
    raw = tp._flat._clean((data or {}).get("pax_count"))
    n = tp.to_decimal(raw)
    if n is not None and n == n.to_integral_value() and 1 <= n <= MAX_PAX:
        return int(n), PAX_FILE
    return 1, PAX_DEFAULT


def row_pax(row) -> int:
    """The pax a row bills with: what was stamped (or typed) on it, else what the file says."""
    stored = getattr(row, "bill_pax_count", None)
    if stored and stored >= 1:
        return int(stored)
    return parse_pax(getattr(row, "data", None) or {})[0]


def _is_zero(data: dict, field: str) -> bool:
    """Is this component known to be nil?

    ABSENT counts as nil; PRESENT-BUT-UNREADABLE does not. The distinction is the whole
    point. MakeMyTrip's export has no `cancellation_fee` column at all, so treating an
    absent field as unknown would stop the `cancelled` verdict ever firing on an MMT file.
    But a cell that is there and says "N/A" is a fact we do not have — and writing that row
    off as a dead cancellation would be asserting that nothing moved when we cannot tell.
    It falls through to `no_amount` instead, which is the honest verdict and a different
    sentence in the gaps view.
    """
    raw = tp._flat._clean(data.get(field))
    if raw is None:
        return True                       # the column is not in this vendor's export
    return tp.to_decimal(raw) == 0        # None (unreadable) != 0, so this is False


# ── billing state: one definition, written twice ─────────────────────────────
# LCC's seven states verbatim, with its payment test swapped for this type's not-billable
# test. `billing_state` answers in Python for the response; `billing_state_cond` says the same
# thing in SQL so the worklist can filter on it.
#
# THE NULL TRAP, inherited from LCC's note and just as live here. A row imported but never
# resolved has `bill_kind IS NULL`. In Python `None not in NOT_BILLABLE_KINDS` is True; in SQL
# `bill_kind NOT IN (...)` is NULL, so the naive predicate silently drops every unresolved row
# out of every result set. Both helpers below are explicitly NULL-safe.

BILLING_STATES = (
    "invoiced",      # on an invoice; frozen, whatever the row now says
    "not_billable",  # no category, pending, nothing to bill, needs review, or no amount
    "no_party",      # not in billing, and still has nobody to bill
    "ready",         # has a party, not yet in billing
    "withdrawn",     # in billing, but the row is no longer billable
    "stale",         # in billing, but under a different party or pax than the row now says
    "sent",          # in billing, and billing agrees with the row
)

SENDABLE_STATES = ("ready", "stale")


def _is_not_billable(kind: str | None) -> bool:
    return kind in NOT_BILLABLE_KINDS


def _billable_kind_cond():
    """SQL twin of `not _is_not_billable(...)`. NULL-safe — see the note above."""
    return or_(ThirdPartyApi.bill_kind.is_(None),
               ThirdPartyApi.bill_kind.notin_(NOT_BILLABLE_KINDS))


def billing_state(row, ticket) -> str:
    """Where one row stands on its way into billing. Pure — no session, no I/O.

    `ticket` is the UploadedTicket this row was projected into, or None. A row whose
    `projected_ticket_id` was nulled underneath it (the FK is ON DELETE SET NULL) arrives here
    as None too, and correctly falls back to ready/no_party rather than claiming to be in
    billing when the ticket is gone.
    """
    projected = ticket is not None
    if projected and ticket.billing_id is not None:
        return "invoiced"
    if _is_not_billable(row.bill_kind):
        return "not_billable"

    billable = row.bill_status in BILLABLE_STATUSES
    if not projected:
        return "ready" if billable else "no_party"
    if not billable:
        return "withdrawn"

    same_party = (
        ticket.customer_type == row.bill_customer_type
        and ticket.customer_id == row.bill_customer_id
        and ticket.corporate_id == row.bill_corporate_id
    )
    # The pax is a billing input too — a fixed markup is multiplied by it — so a ticket sent
    # with a different count is out of date exactly as one sent to a different party is.
    # The STAMPED pax, not a re-read of the file: this has to say what `billing_state_cond`
    # says in SQL, which cannot parse `data`. `project_batch` stamps it on every row it sends.
    same_pax = (getattr(ticket, "pax_count", None) or 1) == (row.bill_pax_count or 1)
    return "sent" if same_party and same_pax else "stale"


def billing_state_cond(state: str, T):
    """A `billing_state` value (or the `sendable` aggregate) as a SQL condition.

    `T` is an aliased UploadedTicket already LEFT JOINed on `projected_ticket_id`.
    Returns None for an unknown state, so a caller can treat it as "no filter".
    """
    projected = T.id.isnot(None)
    invoiced = and_(projected, T.billing_id.isnot(None))
    kind_ok = _billable_kind_cond()
    billable = and_(kind_ok, ThirdPartyApi.bill_status.in_(BILLABLE_STATUSES))
    # IS NOT DISTINCT FROM, never `=`: two NULL corporate_ids are a MATCH, but `NULL = NULL`
    # is NULL, which would report every direct-billed row as stale.
    same_party = and_(
        T.customer_type.is_not_distinct_from(ThirdPartyApi.bill_customer_type),
        T.customer_id.is_not_distinct_from(ThirdPartyApi.bill_customer_id),
        T.corporate_id.is_not_distinct_from(ThirdPartyApi.bill_corporate_id),
        # A row that has never been resolved has no stamped pax, and its ticket cannot exist
        # either (sending requires a resolve), so coalescing to 1 only ever meets real rows.
        T.pax_count == func.coalesce(ThirdPartyApi.bill_pax_count, 1),
    )
    live = not_(invoiced)

    return {
        "invoiced": invoiced,
        "not_billable": and_(live, ThirdPartyApi.bill_kind.in_(NOT_BILLABLE_KINDS)),
        "no_party": and_(live, kind_ok, not_(projected), not_(billable)),
        "ready": and_(live, not_(projected), billable),
        "withdrawn": and_(live, kind_ok, projected, not_(billable)),
        "stale": and_(live, projected, billable, not_(same_party)),
        "sent": and_(live, projected, billable, same_party),
        "sendable": and_(live, billable),
    }.get(state)


def is_projectable(row) -> bool:
    """Would `project_batch` write a ticket for this row?"""
    return (not _is_not_billable(row.bill_kind)
            and row.bill_status in BILLABLE_STATUSES)


def category_product_values(category: str) -> list[str]:
    """Every lower-cased product spelling that bills under `category` — for a SQL filter on
    `lower(data->>'product_type')`."""
    return [k for k, v in mc.CATEGORY_ALIASES.items() if v == category]


# ── the field map ────────────────────────────────────────────────────────────

def _clean(value):
    return tp._flat._clean(value)


def _first(data: dict, *fields: str) -> str | None:
    for f in fields:
        v = _clean(data.get(f))
        if v is not None:
            return v
    return None


def _num(data: dict, field: str) -> Decimal | None:
    return tp.to_decimal(data.get(field))


def _sig(data: dict, field: str, refund: bool) -> Decimal | None:
    """A component amount, signed to agree with the row's own total.

    An aggregator writes the components of a refund as positive magnitudes while the settled
    figure is negative; leaving them positive would make a credit note's fare read as a sale's.
    """
    v = _num(data, field)
    if v is None:
        return None
    return -abs(v) if refund else v


def _abs(data: dict, field: str) -> Decimal | None:
    v = _num(data, field)
    return None if v is None else abs(v)


def _cap(value: str | None, n: int) -> str | None:
    return None if value is None else value[:n]


def _sector(data: dict) -> str | None:
    a = _first(data, "origin_code", "origin")
    b = _first(data, "destination_code", "destination")
    if a and b:
        return f"{a}/{b}"
    return a or b


def _intl_dom(value) -> str | None:
    s = (_clean(value) or "").upper()
    if s.startswith("I"):
        return "International"
    if s.startswith("D"):
        return "Domestic"
    return None


_TAX_FIELDS = (
    ("CGST", "cgst_amount"), ("SGST", "sgst_amount"), ("IGST", "igst_amount"),
    ("TOTAL_GST", "total_gst"), ("SERVICE_TAX", "service_tax_amount"),
    ("LEGACY_CESS", "legacy_cess"), ("TCS", "tcs_amount"), ("TDS", "tds"),
)


def _tax_breakup(data: dict, refund: bool) -> dict | None:
    """The VENDOR's tax on this booking, recorded for audit.

    Deliberately NOT written to `cgst_sell` / `sgst_sell` / `igst_sell`. Those three are the
    GST the AGENCY charges ITS customer, and `api/v1/customers.py` computes them from scratch
    at billing time via `billing_calc.split_gst`. Putting the vendor's figures there would
    store a number nothing reads under a name that says the opposite.
    """
    out = {}
    for label, field in _TAX_FIELDS:
        v = _sig(data, field, refund)
        if v is not None:
            out[label] = str(v)
    return out or None


_RAW_FIELDS = (
    "pax_count", "booking_channel", "booking_type", "booked_by", "amendment_type",
    "payment_mode", "payment_id", "oxi_trx_id", "pending_amount", "agent_markup",
    "pg_charges", "wallet_amount", "pg_amount", "e_coupon_amount", "promo_cash_amount",
    "my_cash", "plus_amount", "trip_type", "origin_country", "booking_date", "booking_time",
    "category", "quota", "date_parse_failed", "booking_status_source",
    "total_paid_amount", "net_amount", "refund_amount", "cancellation_fee",
)
_MAX_SECTOR = 200            # UploadedTicket.sector / .flight_no are String(200)
_STATEMENT_TYPE = "TP-API"   # `statement_type` is String(10); no CHECK. Joins {LCC, B2B, NDC}.


def _build_ticket(row: ThirdPartyApi, *, now: datetime, billing_batch_id: str,
                  source_file: str | None, vendor: str | None,
                  category: str | None = None) -> dict:
    """One billable tp-api row → the UploadedTicket column values.

    Returned as a mapping rather than an ORM object so the same function serves both the
    INSERT and the in-place UPDATE of an already-projected ticket.

    `product_category` is what the line IS, and it splits the map in two. An AIR line fills
    the airline columns exactly as before. Every other line leaves them NULL — the model says
    so ("every column grouped under Airline: … stays NULL on the rest") — and carries what it
    is in `service_details` instead, which the billing pages and the invoice read. A hotel's
    name in `airline_name` would be one income-by-airline row away from reporting "Trident
    Chennai" as a carrier.
    """
    data = row.data or {}
    category = category or row_category(data) or mc.CATEGORY_AIR
    air = category == mc.CATEGORY_AIR
    details = None if air else itin.describe(data, category)

    pax = tp.strip_pax_suffix(data.get("passenger_name"))
    first, last = cres.split_person_name(pax)
    amount = row.bill_amount
    refund = amount is not None and Decimal(str(amount)) < 0
    sector = _sector(data) if air else None

    return {
        # ── provenance
        "batch_id": billing_batch_id,
        "file_name": source_file or "API Statement",
        "tenant_id": row.tenant_id,
        "created_by_id": row.created_by_id,
        "created_at": now,
        "statement_type": _STATEMENT_TYPE,
        "product_category": category,
        "service_details": details,

        # ── money. `total_amt` IS the billing base: api/v1/customers.py reads it first and
        # falls back to sell_fare only when it is NULL. Stored SIGNED, so a refund projects as
        # a negative line with no extra negation step.
        "total_amt": amount,
        "net_amt": amount,
        "sell_fare": _sig(data, "base_fare", refund),
        "sell_tax": _sig(data, "taxes", refund),
        "booking_fee_sell": _sig(data, "convenience_fee", refund),
        # RECORDED, NEVER SUMMED. All three are already netted inside the vendor's payable, so
        # adding them to the billing base would charge the customer twice for the same money.
        "can_charge": _abs(data, "cancellation_fee"),
        "serv_charge": _abs(data, "service_charges"),
        "total_refund_amount": _abs(data, "refund_amount"),
        "dis_sell": _num(data, "discount"),
        "roe": _num(data, "rate_of_exchange"),

        # ── identity
        "pax_name": pax,
        "first_name": first,
        "last_name": last,
        # How many passengers the booking covers — a fixed markup is charged per passenger.
        "pax_count": row_pax(row),
        # An aggregator issues NO airline ticket number — tp_api_spec has no such field. Do
        # NOT synthesise one: `_find_original_ticket` and BSP reconciliation both key on it.
        # Same choice as lcc_billing_projection. The billing pages show `booking_ref` instead.
        "ticket_number": None,
        "booking_ref": _first(data, "booking_id", "invoice_number", "confirmation_no", "reference_no"),
        # Air only. A train's 10-digit IRCTC PNR lives in service_details: series contract
        # matching counts seats on a group PNR, and a berth is not an airline seat.
        "air_pnr": _clean(data.get("pnr")) if air else None,
        "invoice_no": _clean(data.get("invoice_number")),
        "doc_no": _first(data, "tbo_confirmation_no", "confirmation_no"),
        "reference": _first(data, "agency_reference", "supplier_bill_number"),

        # ── flight. `Airline/Property Name` IS the carrier on a Flight row — the column is
        # polymorphic by design (see tp_api_spec's "role-named, not product-named" note), so
        # on any other row it is a hotel or an operator and must not land here.
        "airline_name": _clean(data.get("airline_property_name")) if air else None,
        # DELIBERATELY None. tp-api declares no `resolve_airline`, and deriving a code from
        # the first two characters of a flight number would be a guess that makes an AIRLINE
        # DEAL match an aggregator booking. tickets.py then reports "No airline code on
        # ticket", which is the honest outcome — for a hotel line as much as a flight.
        "airlines_code": None,
        "sector": _cap(sector, _MAX_SECTOR),
        "flight_no": _cap(_clean(data.get("flight_number")), _MAX_SECTOR) if air else None,
        # A train's coach class ("3A") is as much a class as a fare basis is.
        "booking_class": _clean(data.get("booking_class")),
        "segment_type": _intl_dom(data.get("intl_dom")) if air else None,
        # Already ISO after tp_api_spec.normalize, so billing_calc.safe_date's fast path hits.
        "ticket_date": _first(data, "transaction_date", "booking_date"),
        "departure_datetime": _first(data, "start_date", "travel_date") if air else None,
        # Every category: the sold-tickets "travel date" filter reads it. A TBO train carries
        # its journey date only inside the narration, which is where `itin` found it.
        "travel_dt": _first(data, "travel_date", "start_date") or itin.travel_date(details),
        "segments": ([{"route": sector,
                       "flight_no": _clean(data.get("flight_number")),
                       "dep_date": _first(data, "start_date", "travel_date")}]
                     if air and sector else None),

        # ── classification
        "transaction_type": "REFUND" if refund else "SALE",
        "document_type": _STATEMENT_TYPE,
        # None, for LCC's and NDC's reason: the sign of total_amt already carries
        # refund-vs-sale, and tickets.py::_CANCELLED_INVOICE_TYPES drives an unrelated
        # cancellation path off "refund"/"credit note" — setting it would flip these tickets
        # to ticket_status='cancelled' and zero their commission.
        "invoice_type": None,
        # The aggregator, named. Not the airline and not an Agency-master agency; this is the
        # one column on uploaded_tickets that means "who we booked through".
        "booking_agency_name": vendor,
        "narration": _cap(_clean(data.get("narration")), 500),
        "sold_to": "customer",

        # ── party
        "customer_type": row.bill_customer_type,
        "customer_id": row.bill_customer_id,
        "corporate_id": row.bill_corporate_id,
        "customer_agency_id": None,

        # ── audit
        "tax_breakup": _tax_breakup(data, refund),
        "raw_data": {
            "tp_api_row_id": row.id,
            "tp_api_batch_id": row.batch_id,
            "source_format": row.source_format,
            "vendor": data.get("vendor"),
            "product_type": data.get("product_type"),
            "product_category": category,
            "booking_status": data.get("booking_status"),
            "invoice_series": invoice_series(data),
            "bill_kind": row.bill_kind,
            "bill_status": row.bill_status,
            "bill_match_reason": row.bill_match_reason,
            # Before the pax suffix was stripped, so the projection is reversible.
            "passenger_name_raw": data.get("passenger_name"),
            "tp_api": {k: data[k] for k in _RAW_FIELDS if k in data},
        },
    }


_TICKET_COLUMNS = {c.key for c in UploadedTicket.__table__.columns}


def _only_columns(values: dict) -> dict:
    """Drop anything that is not a real column, rather than let a typo ride into an INSERT."""
    return {k: v for k, v in values.items() if k in _TICKET_COLUMNS}


# ── the statement header ─────────────────────────────────────────────────────

def _period(rows) -> tuple:
    """(valid_from, valid_to) over the batch's dates, PARSED not string-compared.

    `tp_api_spec.normalize` leaves ISO strings, where `min()` would be safe — but a row whose
    date failed to parse KEEPS its original text and is flagged `date_parse_failed`, and one
    "13-08-2026" among ISO strings makes a lexicographic min wrong. So it goes through
    `billing_calc.safe_date`, like ndc_billing_projection's.
    """
    dates = []
    for r in rows:
        d = (r.data or {})
        raw = d.get("transaction_date") or d.get("booking_date")
        parsed = billing_calc.safe_date(raw) if raw else None
        if parsed:
            dates.append(parsed)
    return (min(dates), max(dates)) if dates else (None, None)


async def _ensure_statement(db: AsyncSession, header: StatementBatchBilling, *, rows,
                            source_file: str | None, vendor: str | None,
                            supplier_name: str | None) -> TicketStatement:
    """One `ticket_statements` header per batch, created once and refreshed thereafter.

    THE AGENCY GUARD, carried over from lcc_billing_projection verbatim because it is load
    bearing. `agency_account.agency_statement_scope` claims a statement when
    `agency_id == <agency>` OR (`agency_id IS NULL` AND the `agency` TEXT equals an agency's
    name AND `customer_type IN (NULL, 'agency')`). So:

      * `agency_id = None` is set EXPLICITLY, not left to chance.
      * `customer_type = "direct"` is THE guarantee — it fails the third conjunct whatever the
        `agency` text happens to say. The same three-way test is in api/v1/reports.py, so this
        header stays out of supplier income reports too.
      * The "API …" prefix is defence in depth, not the proof.

    `agency` names the DECLARED CONSOLIDATOR when the upload has one: tp-api is
    `requires_supplier`, so `statement_batch_suppliers` holds a snapshot of who actually
    issued the statement. The detected vendor label is the fallback.
    """
    who = supplier_name or vendor or "Statement"
    valid_from, valid_to = _period(rows)
    # `valid_from`, `valid_to` and `file_name` are all NOT NULL on ticket_statements, and a
    # file whose every date failed to parse would otherwise fail the whole send at the last
    # step. Today is the honest fallback: the row's own dates are still on the ticket.
    today = datetime.utcnow().date()
    valid_from = valid_from or today
    valid_to = valid_to or today

    stmt = await db.scalar(
        select(TicketStatement).where(TicketStatement.batch_id == header.billing_batch_id)
    )
    if stmt is None:
        stmt = TicketStatement(
            batch_id=header.billing_batch_id,
            tenant_id=header.tenant_id,
            created_by_id=header.created_by_id,
            created_at=datetime.utcnow(),
            file_name=source_file or "API Statement",
            file_url=None,
        )
        db.add(stmt)

    stmt.statement_type = _STATEMENT_TYPE
    stmt.statement_name = f"API - {who} - {source_file or header.batch_id}"
    stmt.agency = f"API {who}".strip()
    stmt.agency_id = None
    stmt.customer_type = "direct"
    stmt.customer_agency_id = None
    stmt.corporate_id = None
    stmt.customer_id = None
    stmt.valid_from = valid_from
    stmt.valid_to = valid_to
    return stmt


# ── the projection ───────────────────────────────────────────────────────────

async def _drop_unbilled_ticket(db: AsyncSession, row: ThirdPartyApi, ticket) -> bool:
    """Take a row's ticket back out of billing, unless it is already on an invoice."""
    if ticket is None or ticket.billing_id is not None:
        return False
    await db.delete(ticket)
    row.projected_ticket_id = None
    return True


async def project_batch(db: AsyncSession, header: StatementBatchBilling, *,
                        row_ids: list[int] | None = None,
                        source_file: str | None = None,
                        vendor: str | None = None,
                        supplier_name: str | None = None) -> dict:
    """Write this batch's billable rows — every category — into `uploaded_tickets`.

    `row_ids=None` is a FULL-BATCH SYNC: a row that lost its party has its ticket DELETED —
    that is how a ticket leaves billing. `row_ids=[…]` is ADDITIVE and scoped: untouched rows
    are never read, updated or deleted, and a selected row with no party is reported rather
    than acted on.

    The caller owns the commit.
    """
    now = datetime.utcnow()
    if not header.billing_batch_id:
        # Allocated once and reused forever, so the ticket_statements header is stable across
        # re-projections and a user's saved filters keep working.
        header.billing_batch_id = str(uuid4())

    q = (select(ThirdPartyApi)
         .where(ThirdPartyApi.batch_id == header.batch_id)
         # No row_seq on this model — it carries no _SplitMixin, so ingest order IS file order.
         .order_by(ThirdPartyApi.id.asc()))
    rows = list((await db.execute(q)).scalars().all())

    scoped = row_ids is not None
    wanted = set(row_ids or ())
    touch = [r for r in rows if not scoped or r.id in wanted]

    await _ensure_statement(db, header, rows=rows, source_file=source_file,
                            vendor=vendor, supplier_name=supplier_name)

    created = updated = deleted = 0
    skipped_billed = skipped_no_party = 0
    skipped_by_reason: dict[str, int] = {}
    sent_by_category: dict[str, int] = {}
    credits = 0

    for row in touch:
        ticket = None
        if row.projected_ticket_id is not None:
            ticket = await db.get(UploadedTicket, row.projected_ticket_id)

        kind = row.bill_kind
        category = row_category(row.data or {})
        # A row resolved as billable whose product was edited to something with no category
        # since. Its stored kind is out of date; it is treated as what it now is rather than
        # priced at a guessed category's markup.
        if not _is_not_billable(kind) and category is None:
            kind = NO_CATEGORY

        if _is_not_billable(kind):
            skipped_by_reason[kind] = skipped_by_reason.get(kind, 0) + 1
            # A row that USED to be billable and has a ticket: in a full sync the ticket goes,
            # in a scoped send it is left alone (the user did not ask about it).
            if not scoped and await _drop_unbilled_ticket(db, row, ticket):
                deleted += 1
            continue

        if row.bill_status not in BILLABLE_STATUSES:
            skipped_no_party += 1
            if not scoped and await _drop_unbilled_ticket(db, row, ticket):
                deleted += 1
            continue

        # Stamped before the ticket is built, so the row and its ticket agree on the pax —
        # which is what `billing_state` compares. A row resolved before pax was tracked has
        # none stamped yet.
        if not row.bill_pax_count:
            row.bill_pax_count, row.bill_pax_source = parse_pax(row.data or {})

        values = _only_columns(_build_ticket(
            row, now=now, billing_batch_id=header.billing_batch_id,
            source_file=source_file, vendor=vendor, category=category,
        ))

        if ticket is not None:
            # FROZEN once invoiced. Never edited, never removed — the invoice is the record.
            if ticket.billing_id is not None:
                skipped_billed += 1
                continue
            for k, v in values.items():
                if k != "created_at":
                    setattr(ticket, k, v)
            updated += 1
        else:
            ticket = UploadedTicket(**values)
            db.add(ticket)
            await db.flush()
            row.projected_ticket_id = ticket.id
            created += 1
        sent_by_category[category] = sent_by_category.get(category, 0) + 1
        if kind == REFUND:
            credits += 1

    projected = await db.scalar(
        select(func.count()).select_from(ThirdPartyApi)
        .where(ThirdPartyApi.batch_id == header.batch_id,
               ThirdPartyApi.projected_ticket_id.isnot(None))
    ) or 0
    header.projected_rows = projected
    header.projected_tickets = projected     # one row is one ticket here, unlike NDC
    header.projected_at = now
    header.resolution_status = "projected"

    return {
        "batch_id": header.batch_id,
        "statement_batch_id": header.billing_batch_id,
        "scoped": scoped,
        "requested": len(touch),
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "skipped_billed": skipped_billed,
        "skipped_no_party": skipped_no_party,
        "skipped_not_billable": sum(skipped_by_reason.values()),
        # Per-kind, so the toast can say "3 pending" rather than "3 skipped".
        "skipped_by_reason": skipped_by_reason,
        # Per category, so the toast can say "40 train, 5 hotel" rather than "45 tickets".
        "sent_by_category": sent_by_category,
        "credits": credits,
        "projected_rows": projected,
        "projected_tickets": projected,
    }
