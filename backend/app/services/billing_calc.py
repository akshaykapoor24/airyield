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


def compute_gst(base: float, markup: float, billing_type: Optional[str], discount: float = 0.0) -> float:
    """GST (18%) base depends on billing type. The discount reduces the taxable
    amount BEFORE GST is applied (clamped at 0 so a large discount can't create
    negative tax):
      - reseller: GST on (gross + markup − discount)
      - agency:   GST on (markup − discount)
      - unset/other: no GST applied
    """
    bt = (billing_type or "").lower()
    if bt == "reseller":
        return max(0.0, base + markup - discount) * GST_RATE
    if bt == "agency":
        return max(0.0, markup - discount) * GST_RATE
    return 0.0


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
    """SQL clause for the tickets a customer may bill."""
    link = UploadedTicket.customer_id == customer.id
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
    if customer is not None and t.customer_id == customer.id:
        return MATCHED_BY_LINK
    if corporate is not None and t.corporate_id == corporate.id:
        return MATCHED_BY_LINK
    if _is_untagged(t) and any(_name_matches(t, f, l) for f, l in (names or [])):
        return MATCHED_BY_NAME
    return None
