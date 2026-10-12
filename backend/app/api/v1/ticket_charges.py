"""Service charges for a hand-punched ticket, quoted from User master.

Internal Statement → Create Ticket asks this while the desk types, so the charges
on a ticket come from the rates agreed at onboarding instead of being retyped (and
mistyped) on every line.

EVERYTHING COMES FROM THE SOLD TO PARTY. There is no separate supplier to pick: a
B2B agency is onboarded with BOTH of its rates on its own Agency Master row, and a
corporate or customer carries its markup on its own row.

    Sold To     client side (we charge them)      supplier side (charged to us)
    agency      customer_service_fee              vendor_service_charge
    corporate   markup, "air" category            —
    customer    markup, "air" category            —
                (place of supply falls back to their corporate when they have none)

A percentage is of the ticket's Total Fare, the base the party billing routers
already use (`total_amt`, falling back to the basic fare). A fixed amount is per
ticket — and a punched ticket is one passenger, so that is also per passenger, the
convention `party_markup.line_markup` states.

GST is on the CLIENT charge only — it is the tax we raise on our own service, and
CGST + SGST versus IGST is decided by services/place_of_supply exactly as billing
decides it. The supplier's charge comes back gross: their GST is on their invoice
to us, not a tax line on this ticket.

Read-only and side-effect free: nothing is stored here. The form fills its fields
from the answer and the user may still overwrite them.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency import Agency
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.user import User
from app.services.billing_calc import GST_RATE, compute_markup
from app.services.markup_categories import CATEGORY_AIR
from app.services.party_markup import markup_for
from app.services.place_of_supply import place_of_supply
from app.services.service_fee import (
    DEFAULT_GST_TREATMENT, customer_service_fee, taxable_and_gst, vendor_service_charge,
)

router = APIRouter()


class ChargeQuoteIn(BaseModel):
    customer_type:      Optional[str] = None   # agency | corporate | direct
    agency_id:          Optional[int] = None
    corporate_id:       Optional[int] = None
    customer_id:        Optional[int] = None
    base:               float = 0.0             # the ticket's Total Fare


class FeeQuote(BaseModel):
    source:        str                 # "Agency Master", ...
    fee_type:      str                 # percentage | fixed
    fee_value:     float
    gst_treatment: str                 # inclusive | exclusive
    amount:        float               # as quoted
    taxable:       float               # what GST is charged on
    gst:           float
    gross:         float               # what is actually paid
    note:          str                 # "2% of fare · GST extra"


class ChargeQuoteOut(BaseModel):
    client:      Optional[FeeQuote] = None
    supplier:    Optional[FeeQuote] = None
    gst_rate:    float = GST_RATE
    # True → IGST, False → CGST + SGST, None → could not be decided (see gst_note).
    interstate:  Optional[bool] = None
    gst_note:    Optional[str] = None


def _quote(base: float, ftype, fvalue, treatment, source: str) -> Optional[FeeQuote]:
    if ftype not in ("percentage", "fixed") or fvalue is None:
        return None
    value = float(fvalue)
    amount = compute_markup(base, ftype, value)
    split = taxable_and_gst(amount, treatment)
    shown = f"{value:g}% of fare" if ftype == "percentage" else f"₹{value:g} per ticket"
    return FeeQuote(
        source=source, fee_type=ftype, fee_value=value, gst_treatment=split["gst_treatment"],
        amount=split["amount"], taxable=split["taxable"], gst=split["gst"], gross=split["gross"],
        note=f"{shown} · " + ("incl. GST" if split["gst_treatment"] == "inclusive" else "GST extra"),
    )


async def _one(db: AsyncSession, model, obj_id: Optional[int], user: User):
    """A master row the user owns, by the same scope each master's own router uses:
    agencies are private to `user_id` (api/v1/agencies._scope); corporates and
    customers to tenant + creator."""
    if obj_id is None:
        return None
    scope = (model.user_id == user.id) if model is Agency else and_(
        model.tenant_id == user.tenant_id, model.created_by_id == user.id,
    )
    return (await db.execute(
        select(model).where(model.id == obj_id, scope)
    )).scalar_one_or_none()


@router.post("/quote", response_model=ChargeQuoteOut)
async def quote_ticket_charges(
    payload: ChargeQuoteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = float(payload.base or 0)
    out = ChargeQuoteOut()

    # ── client side ─────────────────────────────────────────────────────────
    party = None
    pos_party, pos_corporate = None, None
    kind = (payload.customer_type or "").strip().lower()
    if kind == "agency":
        party = await _one(db, Agency, payload.agency_id, current_user)
        if party is not None:
            out.client = _quote(base, *customer_service_fee(party), "Agency Master")
            # The same agency's other rate — what it charges us — is the supplier side.
            out.supplier = _quote(base, *vendor_service_charge(party), "Agency Master")
            pos_party = party
    elif kind == "corporate":
        party = await _one(db, Corporate, payload.corporate_id, current_user)
        if party is not None:
            mtype, mval = markup_for(party, CATEGORY_AIR)
            # A markup carries no inclusive/exclusive flag; billing adds tax on top.
            out.client = _quote(base, mtype, mval, DEFAULT_GST_TREATMENT, "Corporate Master")
            pos_party = party
    elif kind == "direct":
        party = await _one(db, Customer, payload.customer_id, current_user)
        if party is not None:
            mtype, mval = markup_for(party, CATEGORY_AIR)
            out.client = _quote(base, mtype, mval, DEFAULT_GST_TREATMENT, "Employee Master")
            pos_party = party
            # Customer has no ORM relationship to its corporate, so place_of_supply
            # cannot reach the employer by itself — load it for the fallback below.
            if party.corporate_id:
                pos_corporate = await _one(db, Corporate, party.corporate_id, current_user)

    if pos_party is not None:
        pos = place_of_supply(current_user.tenant, pos_party)
        if pos.interstate is None and pos_corporate is not None:
            # The employee has no state of their own; their employer's decides.
            pos = place_of_supply(current_user.tenant, pos_corporate)
        out.interstate = pos.interstate
        out.gst_note = pos.note

    return out
