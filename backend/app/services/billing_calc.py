"""Shared helpers for billing math and ticket scoping (customer + corporate + agency).

These were originally private to `api/v1/customers.py`; they are extracted here
so the agency-billing router can reuse the exact same markup/GST/date logic and
keep a single source of truth.

The scoping half answers "whose ticket is this?" and exists in ONE place for the same
reason: the list endpoint and the create-billing endpoint have to agree exactly, or the
selector shows one set of rows and the POST accepts another.
"""
import re
from datetime import date
from typing import Optional

from dateutil import parser as _du
from sqlalchemy import and_, or_

from app.models.uploaded_ticket import UploadedTicket

GST_RATE = 0.18
# CGST and SGST are each half of it. An intra-state supply is not taxed twice —
# the 18% is SPLIT between the centre and the state, 9% apiece, which is why
# 9 + 9 and a flat 18 come to the same money.
HALF_GST_RATE = GST_RATE / 2

# Which heads a line was charged under. Stored on the billing so a later edit
# cannot silently re-decide it, and returned on every row so a zero in the CGST
# column can never be mistaken for "no tax" when it means "IGST carried it".
TREATMENT_INTRA = "cgst_sgst"   # supplier and recipient in one state
TREATMENT_INTER = "igst"        # different states
TREATMENT_UNSPLIT = "unsplit"   # place of supply unknown — see split_gst


def to_float(value) -> float:
    """Coerce a possibly-None Decimal/str to float (0.0 on failure)."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_markup(base: float, markup_type: Optional[str], markup_value) -> float:
    """Markup amount for a base fare: percentage of base, a fixed amount, or none.

    Both forms follow the sign of the base. A refund is a negative base, so a flat
    ₹500 markup on it has to come back as −500 — otherwise the credit note bills the
    customer for the markup on a ticket they gave back. Percentage already carried
    the sign through `base`; `fixed` did not, and silently over-charged every credit.
    A zero base keeps +mval: no such row is billable today, but the branch has to be
    defined.
    """
    mtype = (markup_type or "").lower()
    mval = to_float(markup_value)
    if mtype == "percentage":
        return base * mval / 100.0
    if mtype == "fixed":
        return -mval if base < 0 else mval
    return 0.0


def gst_taxable(base: float, markup: float, billing_type: Optional[str], discount: float = 0.0) -> float:
    """What GST is charged ON, before any rate is applied.

    The taxable value depends on billing type. The discount reduces it BEFORE
    the rate applies (clamped at 0 so a large discount can't create negative tax):
      - reseller: gross + markup − discount
      - agency:   markup − discount
      - unset/other: nothing is taxable

    Split out of `compute_gst` so the heads can each be taken from the same
    figure. Charging CGST at 9% of the taxable value is not the same arithmetic
    as halving an 18% total, and only the first is what an invoice must show.
    """
    bt = (billing_type or "").lower()
    if bt == "reseller":
        return max(0.0, base + markup - discount)
    if bt == "agency":
        return max(0.0, markup - discount)
    return 0.0


def compute_gst(base: float, markup: float, billing_type: Optional[str], discount: float = 0.0) -> float:
    """The single 18% figure, as this system has always computed it.

    Kept exactly as it was. `split_gst` is what new code should call; this
    remains for the legacy single-column reads and as the definition the split
    is measured against.
    """
    return gst_taxable(base, markup, billing_type, discount) * GST_RATE


def split_gst(
    base: float,
    markup: float,
    billing_type: Optional[str],
    discount: float = 0.0,
    *,
    interstate: Optional[bool],
) -> dict:
    """The same tax, in the heads it is actually charged under.

    `interstate` is the place-of-supply decision — see services/place_of_supply:
      True  → IGST at the full rate, CGST and SGST zero
      False → CGST and SGST at half each, IGST zero
      None  → UNDECIDABLE. All three come back zero and `gst_amount` still
              carries the total, so the row shows what is owed without claiming
              a head it cannot justify. Deliberately not treated as intra-state:
              a missing state must not quietly become CGST + SGST.

    `gst_amount` is the authoritative total for the line — callers must add THIS
    to the line total rather than re-deriving it, or the preview and the invoice
    can differ by a paisa. On an intra-state line it is cgst + sgst, each rounded
    at 9%, which is how the tax is actually levied.

    `interstate` is keyword-only with no default on purpose. A default of False
    would silently bill CGST + SGST on inter-state supplies at every call site
    that forgot it, and nothing on screen would say so.
    """
    taxable = gst_taxable(base, markup, billing_type, discount)

    if interstate is None:
        return {
            "cgst": 0.0, "sgst": 0.0, "igst": 0.0,
            "gst_amount": round(taxable * GST_RATE, 2),
            "gst_treatment": TREATMENT_UNSPLIT,
        }
    if interstate:
        igst = round(taxable * GST_RATE, 2)
        return {
            "cgst": 0.0, "sgst": 0.0, "igst": igst,
            "gst_amount": igst,
            "gst_treatment": TREATMENT_INTER,
        }
    # Each head from the taxable value, not half of the total: CGST and SGST have
    # to be EQUAL on an invoice, and halving an odd-paise total makes them differ.
    half = round(taxable * HALF_GST_RATE, 2)
    return {
        "cgst": half, "sgst": half, "igst": 0.0,
        "gst_amount": round(half * 2, 2),
        "gst_treatment": TREATMENT_INTRA,
    }


def interstate_from_treatment(treatment: Optional[str]) -> Optional[bool]:
    """Read a stored treatment back as the flag `split_gst` takes.

    Editing a raised billing must re-apply the decision the billing was RAISED
    under, not re-decide it from the party's current address — a customer who
    updates their GSTIN next month must not silently move an issued invoice from
    CGST + SGST to IGST.
    """
    if treatment == TREATMENT_INTER:
        return True
    if treatment == TREATMENT_INTRA:
        return False
    return None


def safe_date(*raws) -> Optional[date]:
    """Parse a ticket date string to a date. Handles ISO YYYY-MM-DD and dayfirst formats.
    Mirrors the parser used in services/deal_matching.py.
    """
    for raw in raws:
        if not raw:
            continue
        try:
            s = str(raw).strip()
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return date.fromisoformat(s[:10])
            return _du.parse(s, dayfirst=True).date()
        except Exception:
            continue
    return None


def passenger_name(t) -> str:
    """Best passenger name from an UploadedTicket (pax_name, else first+last)."""
    if getattr(t, "pax_name", None):
        return t.pax_name
    name = f"{getattr(t, 'first_name', '') or ''} {getattr(t, 'last_name', '') or ''}".strip()
    return name or "—"


# ══════════════════════════════════════════════════════════════════════════════
# WHOSE TICKET IS THIS?  —  the explicit link wins; the name is only a fallback
# ══════════════════════════════════════════════════════════════════════════════
#
# `uploaded_tickets` has carried customer_type / customer_agency_id / corporate_id /
# customer_id since cust_party_01, written at upload from the customer picker — but
# until now nothing read them, and billing matched purely on the passenger's name.
# That is wrong in both directions: a ticket explicitly sold to one party could be
# billed by another whose customer happens to share a name, and a party whose name
# never matched could not be billed at all.
#
# So: if a ticket names a party, only that party may bill it. A ticket that names
# nobody still falls back to passenger-name matching, exactly as before.
#
# ONE TICKET, ONE PAYER. The three tagged shapes and who each one belongs to:
#
#   customer_id + corporate_id   the employer — an employee's ticket billed to the
#                                company they work for; the person is still named
#                                so the row says who travelled, but they are not
#                                the payer
#   customer_id alone            the person, billed directly
#   corporate_id alone           the company, with nobody named
#
# `is_billed` is a single FK, so a ticket claimable by two parties is a race —
# whoever invoices first takes it and the other silently loses the fare.

MATCHED_BY_LINK = "link"
MATCHED_BY_NAME = "name"


def untagged_ticket():
    """No party has claimed this ticket.

    All four columns, not just `customer_type`: cust_party_01 backfilled
    customer_type='agency' onto tagged rows, and Create Tickets can set an id on a row
    whose type is still NULL. Treating any one of them as authoritative would leak
    tickets between parties.
    """
    return and_(
        UploadedTicket.customer_type.is_(None),
        UploadedTicket.customer_id.is_(None),
        UploadedTicket.corporate_id.is_(None),
        UploadedTicket.customer_agency_id.is_(None),
    )


def customer_ticket_scope(customer, name_conds):
    """SQL clause for the tickets a customer may bill.

    NAMING A CORPORATE TAKES THE TICKET OFF THE PERSON'S BILL. `customer_id` and
    `corporate_id` answer two different questions — who flew, and who pays — and a
    ticket routed to an employer keeps both: the person so the row still says who
    travelled, the company because that is who is invoiced. Reading the person's
    id alone as a claim put every corporate ticket on the employee's bill as well,
    so the same fare appeared on two screens and whichever was invoiced first took
    it. One payer, one bill: a person bills what names them and names no company.
    """
    link = and_(UploadedTicket.customer_id == customer.id,
                UploadedTicket.corporate_id.is_(None))
    if not name_conds:
        # Note this is a behaviour change in the customer's favour: previously a
        # customer with no usable name matched nothing at all.
        return link
    return or_(link, and_(untagged_ticket(), or_(*name_conds)))


def corporate_ticket_scope(corporate, name_conds):
    """SQL clause for the tickets a corporate may bill (its employees' tickets)."""
    link = UploadedTicket.corporate_id == corporate.id
    if not name_conds:
        return link
    return or_(link, and_(untagged_ticket(), or_(*name_conds)))


def _is_untagged(t) -> bool:
    return not (t.customer_type or t.customer_id or t.corporate_id or t.customer_agency_id)


def _name_matches(t, raw_first: Optional[str], raw_last: Optional[str]) -> bool:
    """Python twin of the ILIKE conditions the two routers build.

    Kept beside the SQL so the create-billing guard can never drift from the list
    query it is supposed to be validating.
    """
    fn = (raw_first or "").strip().lower()
    ln = (raw_last or "").strip().lower()
    if not fn:
        return False
    t_first = (t.first_name or "").strip().lower()
    t_last = (t.last_name or "").strip().lower()
    pax = (t.pax_name or "").lower()
    if ln:
        if t_first == fn and t_last == ln:
            return True
        # Mirrors pax_name ILIKE '%fn%ln%' — order matters in that pattern.
        return bool(re.search(re.escape(fn) + ".*" + re.escape(ln), pax))
    return t_first == fn or fn in pax


def ticket_matched_by(t, *, customer=None, corporate=None, names=None) -> Optional[str]:
    """'link' | 'name' | None — how (and whether) this ticket reaches the party.

    `names` is the list of (first, last) pairs to try: one pair for a customer, the
    employee set plus the legacy own-name for a corporate.
    """
    # `corporate_id is None` mirrors customer_ticket_scope exactly: a ticket routed
    # to an employer is the employer's to bill, not the employee's. These two must
    # not drift — the list query and the create-billing guard have to agree, or the
    # selector offers rows the POST then rejects.
    if customer is not None and t.customer_id == customer.id and t.corporate_id is None:
        return MATCHED_BY_LINK
    if corporate is not None and t.corporate_id == corporate.id:
        return MATCHED_BY_LINK
    if _is_untagged(t) and any(_name_matches(t, f, l) for f, l in (names or [])):
        return MATCHED_BY_NAME
    return None
