"""Roll NDC statement rows up per ticket and project them into `uploaded_tickets`.

Customer and Corporate Billing read exactly one table — `uploaded_tickets` — and NDC rows
live in `ndc.data` (JSONB), invisible to it. This module is the bridge, and it is modelled
on `services/lcc_billing_projection.py`, which does the same job for LCC Detailed.

WHAT IS DIFFERENT FROM LCC, AND WHY THIS IS NOT THAT MODULE PARAMETERISED.

* **NDC issues a real ticket number.** LCC deliberately synthesises none, so its
  idempotency can only be the stored `projected_ticket_id` FK. NDC keeps that key (see
  below) but `Document No` is also the natural grouping key, which LCC has no equivalent of.
* **NDC ancillaries are their OWN ROWS.** An LCC line carries its SSR money in a column;
  an NDC export writes `PAID_SEAT` / `REFUND_SEAT` as separate transaction lines with no
  document number, tied to the flight only by PNR and passenger. Latching those onto the
  right ticket is the whole of `build_groups`, and LCC has nothing like it.
* **NDC names its transaction.** `bill_kind` reads `TXN Type`; LCC has to infer sale from
  refund from the sign of a total because its export has no type column.

WHERE THE ROLL-UP RUNS: at RESOLVE time, never at ingest. The `ndc` table is a faithful
copy of the vendor's file — `/records` still shows every `PAID_SEAT` line, `Product` and
`TXN Type` are declared filters precisely so a human can separate them on screen, and
commission keys on `ndc.id`. Rolling up at ingest would also make the rule unfixable: NDC
declares no `parser`, so `reprocess` refuses it and the only way to re-decide would be to
re-upload. `resolve-customers` writes its verdict to columns and `project_batch` READS
them, which is what makes "what you saw on the worklist is what you sent" true.

TWO INVARIANTS CARRIED OVER FROM LCC:

  * **Idempotency is keyed on the stored `projected_ticket_id`**, not on the ticket number.
    Re-uploading the same file legitimately produces the same document numbers, and a
    natural key would silently merge two uploads.
  * **A ticket carrying a `billing_id` is frozen.** Re-resolving must never edit or delete
    a row that is already on an invoice.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statement_batch_billing import StatementBatchBilling
from app.models.statement_row import Ndc
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket
from app.services import customer_resolver as cres
from app.services import ndc_spec
from app.services.billing_calc import safe_date

__all__ = [
    "SLUG", "BILLABLE_STATUSES", "BILLING_STATES", "SENDABLE_STATES", "LATCH_STATUSES",
    "LATCH_REASON", "Line", "Group",
    "norm_doc", "norm_pnr", "pax_key", "is_refund", "bill_kind", "signed_total",
    "build_groups", "ticket_fields", "billing_state", "billing_state_cond",
    "is_projectable", "project_batch", "airline_names",
]

SLUG = "ndc"
_STATEMENT_TYPE = "NDC"          # `statement_type` is String(10); no CHECK on it.
_MAX_SECTOR = 200                # UploadedTicket.sector / .flight_no are String(200)

# The statuses that mean "a party has been settled for this row" — cres' own vocabulary.
BILLABLE_STATUSES = (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISATION — lookup only. Never displayed, never stored.
# ══════════════════════════════════════════════════════════════════════════════

_NON_KEY = re.compile(r"[^A-Z0-9]+")


def _clean(value) -> str | None:
    """A verbatim cell → a usable string, or None. Matches statements.py::_clean."""
    if value is None:
        return None
    s = str(value).strip()
    return None if s == "" or s.lower() == "nan" else s


def norm_doc(value) -> str | None:
    """"0982185569174" — a ticket number reduced to a comparison key.

    An export can pad, hyphenate or space a document number differently on the flight line
    and on a later coupon line for the same ticket. Two spellings of one number would
    become two tickets and two invoice lines.
    """
    s = _clean(value)
    if s is None:
        return None
    return _NON_KEY.sub("", s.upper()) or None


#: A PNR is alphanumeric and case-insensitive; same reduction as a document number.
norm_pnr = norm_doc


def pax_key(value) -> str | None:
    """The passenger's name as a latch key — `customer_resolver.person_match_key`.

    THE SAME KEY THE PARTY RESOLVER USES, on purpose. "NITIN/CHAUHAN", "MR NITIN CHAUHAN"
    and "CHAUHAN NITIN" have to be one passenger on both axes, or a seat would latch onto a
    ticket that then resolves to a different customer.

    The dropped-initials set is deliberately discarded, exactly as `CustomerIndex.resolve`
    refuses to expand initials: a seat row spelled "N CHAUHAN" will NOT latch onto "NITIN
    CHAUHAN" and becomes an orphan instead. That is the same refusal, restated where it now
    costs money — see the evidence table at customer_resolver.py's foot.
    """
    key, _initials = cres.person_match_key(value)
    return key or None


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

#: The two TXN Types that move money back. `EXCLUDED_TXN_TYPES` has already dropped the
#: unpaid and free-seat lines at ingest, so what reaches here is six types.
REFUND_TXN = frozenset({"REFUND", "REFUND_SEAT"})

#: What the TRANSPORT is called. Everything else the airline sells on a line of its own —
#: a seat, a bag, a meal, lounge access, an EMD of any kind — is an add-on to a ticket.
#:
#: DEFINED THIS WAY ROUND ON PURPOSE. An earlier version enumerated the add-ons
#: (`SEAT|BAG|MEAL|…`) and had to be right about every product name an airline might
#: invent; the first unlisted one — "Lounge Access" — would quietly become a ticket of its
#: own with its own invoice line. There is exactly one word for the thing being flown, and
#: `Product` is the airline's own field for it.
_FLIGHT_PRODUCT = re.compile(r"^(FLIGHT|AIR|TRANSPORT|TICKET|ITINERARY)")
#: The fallback when `Product` is blank: a `*_SEAT` transaction is never the flight.
_ANCILLARY_TXN = re.compile(r"_SEAT$|^SEAT")

# Which `uploaded_tickets` column an ancillary's money lands in.
#
# WHY THE DEFAULT IS `booking_fee_sell` AND NOT `seat_selection`. `uploaded_tickets`
# documents its incentive bases as "sell_fare / sell_tax_yq / sale_yr and the NAMED
# ancillaries" (models/uploaded_ticket.py). An unrecognised product dropped into
# `seat_selection` would silently inflate an incentive nobody asked it to. `booking_fee_sell`
# is a recorded, non-base column — the same one LCC uses for `other_fee_total`. Every such
# row is counted as `unclassified_ancillaries` in the send response and its product name is
# written into `raw_data`, so this map grows on evidence rather than on a guess.
ANCILLARY_BUCKETS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"SEAT"),            "seat_selection"),
    (re.compile(r"BAG"),             "excess_baggage"),
    (re.compile(r"MEAL|MENU|FOOD"),  "meals"),
]
DEFAULT_ANCILLARY_BUCKET = "booking_fee_sell"


def is_refund(data: dict) -> bool:
    """From `TXN Type` alone, so `signed_total` can use it without a cycle."""
    return ndc_spec.norm_txn(data.get("txn_type") or "") in REFUND_TXN


def signed_total(data: dict) -> Decimal | None:
    """The settled figure for one row, signed. None when no cell would parse.

    `Payment Amount` is the file's own settled figure and the only signed column in it — on
    a REFUND line `Total Fare` stays the positive magnitude of the original sale. It is why
    that column was restored to the spec.

    `Total Fare` is the fallback, for batches imported before it was a column (see the
    module docstring's note on `reprocess`). A fallback value carries no sign of its own, so
    the TXN Type supplies one; `-abs()` is idempotent, which means a portal that already
    writes negatives needs no branch here.

    None rather than 0.00 for an unparseable cell: a total silently short by one row is the
    failure mode this whole module exists to avoid. `ndc_spec.to_decimal` makes the same
    choice for the same reason, and using it keeps the repository's `Other Taxes` and this
    figure parsed by one function.
    """
    amount = ndc_spec.to_decimal(data.get("payment_amount"))
    if amount is None:
        amount = ndc_spec.to_decimal(data.get("total_fare"))
    if amount is None:
        return None
    return -abs(amount) if is_refund(data) else amount


def bill_kind(data: dict) -> str:
    """sale | refund | payment, for one row.

    CLASSIFIED ON `TXN Type`, NOT ON THE SIGN. LCC has to read the sign of its total because
    its export has no type column; NDC's TXN Type is the airline's own word for what
    happened, and it is already the column `EXCLUDED_TXN_TYPES` trusts at ingest. Reading
    the sign instead would let a REFUND whose portal wrote a positive Payment Amount project
    as a charge — a credit note issued as an invoice.

    `payment` means no money moved on this line, so there is nothing to bill. It is the same
    verdict `lcc_detailed._bill_kind` reaches for a zero total, and it keeps the row visible
    and inert rather than absent.
    """
    if is_refund(data):
        return "refund"
    amount = signed_total(data)
    return "payment" if (amount is None or amount == 0) else "sale"


def _bucket_for(data: dict) -> str:
    """Which `uploaded_tickets` column this ancillary's money belongs in."""
    subject = f"{ndc_spec.norm_txn(data.get('product') or '')} " \
              f"{ndc_spec.norm_txn(data.get('txn_type') or '')}"
    for pattern, column in ANCILLARY_BUCKETS:
        if pattern.search(subject):
            return column
    return DEFAULT_ANCILLARY_BUCKET


def _looks_ancillary(data: dict) -> bool:
    """Is this line an add-on rather than the flight it hangs off?

    Anything the airline does not call transport. When `Product` is blank the TXN Type
    decides, and the default is FLIGHT: a line we cannot classify is better billed on its
    own than latched onto someone's ticket, because the first is visible and the second
    silently moves money.
    """
    product = ndc_spec.norm_txn(data.get("product") or "")
    if product:
        return not _FLIGHT_PRODUCT.match(product)
    return bool(_ANCILLARY_TXN.search(ndc_spec.norm_txn(data.get("txn_type") or "")))


# ══════════════════════════════════════════════════════════════════════════════
# GROUPING — pure. No session, no model; `Line.from_row` is the only seam.
# ══════════════════════════════════════════════════════════════════════════════

ANCHOR = "anchor"              # carries a document number; becomes the ticket
LATCHED = "latched"            # rolled into an anchor's ticket
ORPHAN = "orphan"              # no document number and no anchor shares its PNR + passenger
AMBIGUOUS = "ambiguous"        # several anchors do — never guessed
UNIDENTIFIED = "unidentified"  # no document number, and no PNR or no name to latch by

LATCH_STATUSES = (ANCHOR, LATCHED, ORPHAN, AMBIGUOUS, UNIDENTIFIED)

# Reason strings are IDENTICAL per gap type, following customer_resolver.REASON: the gaps
# endpoint groups on this column, and naming the passenger here would turn 40 ancillaries
# into 40 groups of one. Specifics belong in the grouped response's sample list.
LATCH_REASON = {
    ORPHAN: "No ticket in this upload shares this row's PNR and passenger.",
    AMBIGUOUS: "This row's PNR and passenger match more than one ticket in this upload.",
    UNIDENTIFIED: "This row has no document number and no PNR or passenger to attach it by.",
}


@dataclass
class Line:
    """One NDC row, reduced to what grouping and projection read.

    `source` is the object the caller passed in — an `Ndc` ORM row in production, a plain
    stub in the tests. Carrying it rather than copying its billing columns is what lets
    `build_groups` stay pure while `project_batch` still reaches the party on the anchor.
    """
    id: int
    seq: int
    data: dict
    source: Any = None

    # filled by build_groups
    group_key: str = ""
    latch_status: str = ""

    @classmethod
    def from_row(cls, row) -> "Line":
        seq = getattr(row, "row_seq", None)
        return cls(id=row.id, seq=row.id if seq is None else seq,
                   data=dict(row.data or {}), source=row)

    # ── derived, computed once per line ──────────────────────────────────────
    @property
    def kind(self) -> str:
        return bill_kind(self.data)

    @property
    def amount(self) -> Decimal | None:
        return signed_total(self.data)

    @property
    def doc(self) -> str | None:
        return norm_doc(self.data.get("document_no"))

    @property
    def pnr(self) -> str | None:
        return norm_pnr(self.data.get("airline_pnr"))

    @property
    def pax(self) -> str | None:
        return pax_key(self.data.get("passenger_name"))

    @property
    def sign(self) -> str:
        """`credit` or `debit`.

        The third component of the latch key, and the reason the common real case needs no
        guess: a PNR holding one PAID_BOOKING and one REFUND for one passenger has one debit
        anchor and one credit anchor, so PAID_SEAT goes to the first and REFUND_SEAT to the
        second.
        """
        return "credit" if is_refund(self.data) else "debit"

    @property
    def is_anchor(self) -> bool:
        return self.latch_status == ANCHOR

    @property
    def bucket(self) -> str:
        return _bucket_for(self.data)


@dataclass
class Group:
    """One ticket-to-be: an anchor line plus the ancillary lines latched onto it."""
    key: str
    anchor: Line
    latched: list[Line] = field(default_factory=list)

    @property
    def lines(self) -> list[Line]:
        return [self.anchor, *self.latched]

    @property
    def kind(self) -> str:
        """The group's kind is the ANCHOR's. A latched line is by definition part of the
        same transaction, and a REFUND_SEAT only ever latches onto a credit anchor."""
        return self.anchor.kind

    @property
    def total(self) -> Decimal | None:
        """Anchor + every latched line. None only when the anchor itself would not parse —
        an unreadable ancillary is skipped rather than voiding the whole ticket, and it is
        reported as `unclassified_ancillaries`/None in the response."""
        base = self.anchor.amount
        if base is None:
            return None
        for line in self.latched:
            if line.amount is not None:
                base += line.amount
        return base

    def ancillary_totals(self) -> dict[str, Decimal]:
        """`{uploaded_tickets column: signed sum}` for the latched lines."""
        out: dict[str, Decimal] = {}
        for line in self.latched:
            if line.amount is None:
                continue
            out[line.bucket] = out.get(line.bucket, Decimal(0)) + line.amount
        return out


def _anchor_rank(line: Line) -> tuple:
    """Sort key picking the ticket line out of several sharing one document number.

    Several rows legitimately share a document number — SPLIT_BOOKING beside TICKETING, or
    coupon-level lines. Determinism is load-bearing rather than cosmetic: idempotency is
    keyed on the anchor's `projected_ticket_id`, so an anchor that moved between two runs
    would orphan a ticket and create a second one. A test asserts that reversing the input
    order picks the same anchor.

    Prefer a real ticket line over an ancillary, then the largest amount, then file order.
    """
    amount = line.amount
    return (1 if _looks_ancillary(line.data) else 0,
            -abs(amount) if amount is not None else Decimal(0),
            line.seq, line.id)


def _group_key(line: Line) -> str:
    """The key of the group a document-carrying line belongs to.

    `(document number, sign)`, NOT the document number alone. A ticket and its own refund
    share one document number — a real Air India export has TICKETING and REFUND lines on
    the same 13 digits — and grouping on the number alone put both in one group whose total
    was exactly zero. The customer was then neither charged nor credited: the sale vanished
    and so did the credit note. A sale and its reversal are two transactions on one
    document and must remain two billed lines. Same reasoning as the `sign` component of
    the passenger key.
    """
    return f"{'C' if line.sign == 'credit' else 'D'}:{line.doc}"


def build_groups(rows) -> list[Group]:
    """NDC rows → the tickets they should become. Pure: no session, no I/O.

    `rows` is anything with `.id`, `.row_seq` and `.data` — an `Ndc` ORM row, or a stub.
    Every line comes back carrying its `group_key` and `latch_status`, which is what the
    caller writes to the columns the worklist and `project_batch` then read.

    WHAT AN ANCHOR IS. A flight line — a row whose `Product` and `TXN Type` say it is the
    transport itself rather than an add-on. Ancillaries are latched onto the anchor that
    shares their PNR, passenger and sign, so a traveller's seat is billed on their ticket.

    NOT "the row that has a document number", which is what an earlier version of this
    keyed on. Air India issues an EMD for a paid seat, so a PAID_SEAT line carries its own
    13-digit document and would never have reached the latching path at all — the roll-up
    would have been dead code on the very file it was written for. `Product` / `TXN Type`
    are the airline's own words for what was sold, and they are what this reads.

    An ancillary that cannot be latched keeps its own line rather than being dropped: if it
    has a document number it IS a document the airline settles, so it bills on its own; only
    a document-less one has to wait for a human (see `is_projectable`).

    AMBIGUITY IS NEVER TIE-BROKEN. Two flight lines sharing PNR + passenger + sign is
    either a conjunction ticket (two documents the airline settles separately) or a reissue.
    "Latch to the first / the latest / the biggest" are each a guess that ends on an
    invoice, and this codebase's stance is already that refusing to attribute is the correct
    failure (customer_resolver.CustomerIndex.resolve).
    """
    lines = [Line.from_row(r) for r in rows]
    lines.sort(key=lambda ln: (ln.seq, ln.id))
    groups: dict[str, Group] = {}

    # ── pass 1: the flight lines, and where an ancillary can attach ──────────
    anchors: dict[str, list[Line]] = {}
    by_pnr_pax: dict[tuple[str, str, str], set[str]] = {}
    ancillaries: list[Line] = []
    for line in lines:
        if _looks_ancillary(line.data):
            ancillaries.append(line)
            continue
        # A flight line with no document number still bills — it is a ticket the portal has
        # not numbered, not an orphan. It simply cannot take ancillaries.
        key = _group_key(line) if line.doc else f"O:{line.id}"
        anchors.setdefault(key, []).append(line)
        if line.doc and line.pnr and line.pax:
            by_pnr_pax.setdefault((line.pnr, line.pax, line.sign), set()).add(key)

    for key, members in anchors.items():
        anchor = min(members, key=_anchor_rank)
        anchor.group_key, anchor.latch_status = key, ANCHOR
        groups[key] = Group(key=key, anchor=anchor)
        for other in members:
            if other is not anchor:
                # Several lines on one document and one sign — coupon-level detail.
                other.group_key, other.latch_status = key, LATCHED
                groups[key].latched.append(other)

    # ── pass 2: latch the ancillaries, or give them a line of their own ──────
    for line in ancillaries:
        candidates = (by_pnr_pax.get((line.pnr, line.pax, line.sign), set())
                      if line.pnr and line.pax else set())
        if len(candidates) == 1:
            key = next(iter(candidates))
            line.group_key, line.latch_status = key, LATCHED
            groups[key].latched.append(line)
            continue

        if line.doc:
            # Its own EMD. A document the airline settles is a line we can bill.
            key = _group_key(line)
            if key in groups:
                line.group_key, line.latch_status = key, LATCHED
                groups[key].latched.append(line)
            else:
                line.group_key, line.latch_status = key, ANCHOR
                groups[key] = Group(key=key, anchor=line)
            continue

        # No document and nothing to attach to — real money awaiting a decision.
        if not line.pnr or not line.pax:
            status = UNIDENTIFIED
        else:
            status = AMBIGUOUS if candidates else ORPHAN
        line.group_key, line.latch_status = f"O:{line.id}", status
        groups[line.group_key] = Group(key=line.group_key, anchor=line)

    for group in groups.values():
        group.latched.sort(key=lambda ln: (ln.seq, ln.id))
    return [groups[k] for k in sorted(groups, key=lambda k: (groups[k].anchor.seq,
                                                             groups[k].anchor.id))]


# ══════════════════════════════════════════════════════════════════════════════
# BILLING STATE — one definition, written twice
# ══════════════════════════════════════════════════════════════════════════════
# `billing_state` classifies a row in Python for the response; `billing_state_cond` says the
# same thing in SQL so the worklist can filter on it. They live together because keeping
# them apart is exactly how they drift.
#
# THE NULL TRAP, carried over verbatim from lcc_billing_projection. A row imported but never
# resolved has `bill_kind IS NULL`. In Python `None != "payment"` is True; in SQL
# `NULL != 'payment'` is NULL, so the naive predicate silently drops those rows out of every
# result set. Everything below goes through `_is_payment` and its `_not_payment_cond` twin.

BILLING_STATES = (
    "invoiced",      # its ticket is on an invoice; frozen, whatever the row now says
    "not_billable",  # no money moved on this line
    "latched",       # rolled into another row's ticket — nothing of its own to send
    "unlatched",     # an ancillary with no ticket to latch to; awaiting a decision
    "no_party",      # not in billing, and still has nobody to bill
    "ready",         # has a party, not yet in billing
    "withdrawn",     # in billing, but the row is no longer billable
    "stale",         # in billing, but under a different party than the row now names
    "sent",          # in billing, and billing agrees with the row
)

# Exactly the rows a "send these" would act on. `sent` is deliberately absent for the same
# reason as LCC: a row already in billing has nothing left to send, and letting a user tick
# it produced a no-op update reported as "1 updated". `latched` and `unlatched` are absent
# because neither has a ticket of its own to create.
SENDABLE_STATES = ("ready", "stale")

_UNLATCHED = (ORPHAN, AMBIGUOUS, UNIDENTIFIED)


def _is_payment(kind: str | None) -> bool:
    return kind == "payment"


def _not_payment_cond():
    """The SQL twin of `not _is_payment(...)`. Explicitly NULL-safe; see the note above."""
    return or_(Ndc.bill_kind.is_(None), Ndc.bill_kind != "payment")


def is_projectable(row) -> bool:
    """Does this row become a ticket of its own?

    One ticket per document number — except on a human's explicit say-so. A latched row's
    money is already on its anchor's ticket, so projecting it too would double the invoice.
    An unlatched ancillary is real money (an orphaned REFUND_SEAT is a seat refunded on a
    kept flight), so it is never silently dropped — but it only becomes its own
    document-less ticket once someone has pointed it at a party, which is what
    `OVERRIDDEN` records.
    """
    status = getattr(row, "bill_latch_status", None)
    if status == LATCHED:
        return False
    if status in _UNLATCHED:
        return getattr(row, "bill_status", None) == cres.OVERRIDDEN
    return True


def billing_state(row, ticket) -> str:
    """Where one row stands on its way into billing. Pure — no session, no I/O.

    `ticket` is the UploadedTicket this row was projected into, or None. A row whose
    `projected_ticket_id` was nulled underneath it (the FK is ON DELETE SET NULL) arrives
    here as None and correctly falls back to ready/no_party, rather than claiming to be in
    billing when the ticket is gone.

    `invoiced` is evaluated FIRST, and that ordering matters more here than it does for LCC:
    every row in a group shares one `projected_ticket_id`, so a latched row is frozen the
    moment its anchor's ticket is invoiced and must say so rather than saying `latched`.
    """
    projected = ticket is not None
    if projected and ticket.billing_id is not None:
        return "invoiced"
    if _is_payment(getattr(row, "bill_kind", None)):
        return "not_billable"

    status = getattr(row, "bill_latch_status", None)
    if status == LATCHED:
        return "latched"

    billable = getattr(row, "bill_status", None) in BILLABLE_STATUSES
    if status in _UNLATCHED and not billable:
        # Visible, counted and inert. It becomes `ready` the moment a party is picked.
        return "unlatched"

    if not projected:
        return "ready" if billable else "no_party"
    if not billable:
        return "withdrawn"

    same_party = (
        ticket.customer_type == row.bill_customer_type
        and ticket.customer_id == row.bill_customer_id
        and ticket.corporate_id == row.bill_corporate_id
    )
    return "sent" if same_party else "stale"


def billing_state_cond(state: str, T):
    """A `billing_state` value (or the `sendable` aggregate) as a SQL condition.

    `T` is an aliased UploadedTicket already LEFT JOINed on `projected_ticket_id`.
    Returns None for an unknown state, so a caller can treat it as "no filter".
    """
    projected = T.id.isnot(None)
    invoiced = and_(projected, T.billing_id.isnot(None))
    not_payment = _not_payment_cond()
    latched = Ndc.bill_latch_status == LATCHED
    unlatched_latch = Ndc.bill_latch_status.in_(_UNLATCHED)
    billable = and_(not_payment, Ndc.bill_status.in_(BILLABLE_STATUSES))
    # IS NOT DISTINCT FROM, never `=`: two NULL corporate_ids are a MATCH, but `NULL = NULL`
    # is NULL, which would report every direct-billed row as stale.
    same_party = and_(
        T.customer_type.is_not_distinct_from(Ndc.bill_customer_type),
        T.customer_id.is_not_distinct_from(Ndc.bill_customer_id),
        T.corporate_id.is_not_distinct_from(Ndc.bill_corporate_id),
    )
    live = not_(invoiced)          # `invoiced` is built from IS NOT NULL, never NULL itself
    # The two NDC-only states short-circuit ahead of the party question, exactly as
    # `billing_state` does, so a latched row is never also reported as `no_party`.
    own_line = and_(not_(latched), not_(and_(unlatched_latch, not_(billable))))

    return {
        "invoiced": invoiced,
        "not_billable": and_(live, Ndc.bill_kind == "payment"),
        "latched": and_(live, not_payment, latched),
        "unlatched": and_(live, not_payment, unlatched_latch, not_(billable)),
        "no_party": and_(live, not_payment, own_line, not_(projected), not_(billable)),
        "ready": and_(live, not_payment, own_line, not_(projected), billable),
        "withdrawn": and_(live, not_payment, own_line, projected, not_(billable)),
        "stale": and_(live, not_payment, own_line, projected, billable, not_(same_party)),
        "sent": and_(live, not_payment, own_line, projected, billable, same_party),
        # ready ∪ sent ∪ stale collapses to "has a line of its own, billable, not frozen".
        "sendable": and_(live, not_payment, own_line, billable),
    }.get(state)


# ══════════════════════════════════════════════════════════════════════════════
# THE FIELD MAP
# ══════════════════════════════════════════════════════════════════════════════

def _iso_date(value) -> str | None:
    """A verbatim date cell → ISO, or the cell itself when it will not parse.

    `UploadedTicket` stores every date as a string, read back by `billing_calc.safe_date`.
    Normalising with that same function is what stops the writer and the reader disagreeing
    about what "08-09-26" means.
    """
    raw = _clean(value)
    if raw is None:
        return None
    parsed = safe_date(raw)
    return parsed.isoformat() if parsed else raw


def _sig(data: dict, key: str, kind: str) -> Decimal | None:
    """One of the anchor's money cells, signed by the group's kind.

    The export writes `Basic Fare`, `Total Tax` and the four tax columns as positive
    MAGNITUDES on a REFUND line — only `Payment Amount` carries the sign. So a refund's
    components are negated here, and `-abs()` is idempotent for a portal that already
    writes them negative.
    """
    value = ndc_spec.to_decimal(data.get(key))
    if value is None:
        return None
    return -abs(value) if kind == "refund" else value


def _abs(data: dict, key: str) -> Decimal | None:
    """A magnitude that is recorded rather than summed — a penalty or a service fee."""
    value = ndc_spec.to_decimal(data.get(key))
    return None if value is None else abs(value)


def _tax_breakup(data: dict, kind: str) -> dict | None:
    out = {}
    for code, field_name in (("K3", "k3_tax"), ("YQ", "yq_tax"),
                             ("YR", "yr_tax"), ("OTHER", "other_taxes")):
        value = _sig(data, field_name, kind)
        if value is not None:
            out[code] = str(value)
    return out or None


def ticket_fields(group: Group, *, airline_name: str | None = None) -> dict:
    """The NDC → UploadedTicket field map for one group. Pure — a dict of column values.

    Returned as a mapping rather than an ORM object so one function serves both the INSERT
    and the in-place UPDATE of an already-projected ticket. Provenance and the billing party
    are added by `_build_ticket`, which is the only part that needs the batch.

    THE MONEY. `total_amt` is the anchor's settled figure PLUS every latched ancillary,
    because `total_amt` IS the billing base — api/v1/customers.py reads it first and falls
    back to `sell_fare` only when it is NULL. The ancillaries also land in their own bucket
    so the invoice can show what the money was for.

    THE TAXES STAY ANCHOR-ONLY. If a carrier ships tax on an ancillary line, that tax is
    already inside the ancillary's own settled figure and therefore already in `total_amt`;
    adding it to `sell_tax` as well would double it and stop `sell_fare + sell_tax`
    describing the flight document.
    """
    data = group.anchor.data
    kind = group.kind
    total = group.total
    first, last = cres.split_person_name(data.get("passenger_name"))
    sectors = _clean(data.get("sectors"))
    flight_no = _clean(data.get("flight_no"))
    departure = _iso_date(data.get("departure_date"))

    values = {
        # ── identity. NDC has a real ticket number, unlike LCC — see Risk 2 in the plan:
        # it makes these tickets visible to BSP reconciliation, which keys on it.
        "ticket_number": norm_doc(data.get("document_no")),
        "air_pnr": _clean(data.get("airline_pnr")),
        "booking_ref": _clean(data.get("airline_pnr")),
        "pax_name": _clean(data.get("passenger_name")),
        "first_name": first,
        "last_name": last,

        # ── money
        "total_amt": total,
        "net_amt": total,
        "sell_fare": _sig(data, "basic_fare", kind),
        "sell_tax": _sig(data, "total_tax", kind),
        "sale_k3": _sig(data, "k3_tax", kind),
        "sell_tax_yq": _sig(data, "yq_tax", kind),
        "sale_yr": _sig(data, "yr_tax", kind),
        "other_tax": _sig(data, "other_taxes", kind),
        # Recorded, never summed: the penalty is already netted inside Payment Amount, so
        # subtracting it again would double-charge the cancellation.
        "can_charge": _abs(data, "penalty_amount"),
        "serv_charge": _abs(data, "service_fee"),
        "dis_sell": ndc_spec.to_decimal(data.get("discount")),
        "base_fare_currency": _clean(data.get("currency")),
        "fop": _clean(data.get("form_of_payment")),

        # ── flight
        "airline_name": airline_name,
        "airlines_code": _clean(data.get("airline")),
        "ai_code": _clean(data.get("airline_iata_code")),
        "sector": sectors[:_MAX_SECTOR] if sectors else None,
        "flight_no": flight_no[:_MAX_SECTOR] if flight_no else None,
        "booking_class": _clean(data.get("class_of_booking")),
        "fare_basis": _clean(data.get("farebasis")),
        # The whole reason `Date Of Issue` was restored: deal validity and BSP
        # reconciliation are both checked against the issue date. `Date Of Booking` is the
        # fallback only for batches imported before that column existed.
        "ticket_date": _iso_date(data.get("date_of_issue")) or _iso_date(data.get("date_of_booking")),
        "departure_datetime": departure,
        "travel_dt": departure,
        "segments": [{"route": sectors, "flight_no": flight_no, "dep_date": departure}]
                    if (sectors or flight_no) else None,

        # ── classification. `invoice_type` stays None for LCC's reason: the sign of
        # `total_amt` already carries refund-vs-sale, and tickets.py drives cancellation
        # matching off that field for a different source.
        "transaction_type": "REFUND" if kind == "refund" else "SALE",
        "document_type": _clean(data.get("document_type")) or _STATEMENT_TYPE,
        "coupon_status": _clean(data.get("coupon_status")),
        "tour_code": _clean(data.get("tour_code")),
        "value_code": _clean(data.get("deal_code")),
        "booking_signon": _clean(data.get("booking_signin")),
        "ticketing_signon": _clean(data.get("tkt_issue_signin")),
        "invoice_type": None,
        "statement_type": _STATEMENT_TYPE,
        "sold_to": "customer",
        "tax_breakup": _tax_breakup(data, kind),

        # ── ancillary money, by bucket ───────────────────────────────────────
        # EVERY bucket is listed, None included. `project_batch` updates an already-
        # projected ticket by setattr over this dict, so a column absent from it keeps
        # whatever it held before — and a group whose seat row was deleted, re-typed or
        # re-latched elsewhere would silently keep charging for the seat.
        "seat_selection": None,
        "excess_baggage": None,
        "meals": None,
        DEFAULT_ANCILLARY_BUCKET: None,
    }
    values.update(group.ancillary_totals())
    return values


# `currency` and friends are not columns on UploadedTicket; drop unknown keys rather than
# letting a typo ride into a TypeError at insert time.
_TICKET_COLUMNS = {c.key for c in UploadedTicket.__table__.columns}


def _only_columns(values: dict) -> dict:
    return {k: v for k, v in values.items() if k in _TICKET_COLUMNS}


#: Everything the spec keeps that has no column on `uploaded_tickets`. Recorded on the
#: ticket's `raw_data` so the projection is lossless even though the table is narrower.
_RAW_FIELDS = (
    "date_of_booking", "total_fare", "txn_type", "product", "coupon_number",
    "conjunction_ticket_no", "inconnection_doc_number", "child_parent_pnr",
    "passenger_type", "cabin_code", "cabin_name", "agency_type", "payment_status",
    "promo_code", "agency_code",
)


def _build_ticket(group: Group, header: StatementBatchBilling, *,
                  now: datetime, airline_name: str | None, source_file: str | None) -> dict:
    """`ticket_fields` plus the provenance and the party — the full column map."""
    anchor = group.anchor.source
    data = group.anchor.data
    return {
        **ticket_fields(group, airline_name=airline_name),
        "batch_id": header.billing_batch_id,
        "file_name": source_file or "NDC Statement",
        "tenant_id": anchor.tenant_id,
        "created_by_id": anchor.created_by_id,
        "created_at": now,
        # party — resolved onto the ANCHOR; every latched row inherits it at resolve time.
        "customer_type": anchor.bill_customer_type,
        "customer_id": anchor.bill_customer_id,
        "corporate_id": anchor.bill_corporate_id,
        "customer_agency_id": None,
        "raw_data": {
            "ndc_row_id": anchor.id,
            "ndc_batch_id": anchor.batch_id,
            "ndc_group_key": group.key,
            "bill_kind": anchor.bill_kind,
            "bill_status": anchor.bill_status,
            "bill_match_reason": anchor.bill_match_reason,
            "latched_row_ids": [ln.id for ln in group.latched],
            "ancillaries": [
                {"row_id": ln.id, "product": ln.data.get("product"),
                 "txn_type": ln.data.get("txn_type"), "bucket": ln.bucket,
                 "amount": None if ln.amount is None else str(ln.amount)}
                for ln in group.latched
            ],
            "ndc": {k: data[k] for k in _RAW_FIELDS if k in data},
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# PROJECTION
# ══════════════════════════════════════════════════════════════════════════════

async def airline_names(db: AsyncSession, codes: Collection[str]) -> dict[str, str]:
    """`{code: airline name}` for the codes a batch carries, in one query.

    NDC gives BOTH keys — `Airline` is the 2-letter marketing code ("AI", unique on
    `airlines.iata_code`) and `Airline IATA Code` is the 3-digit accounting code ("098",
    indexed as `iata_numeric_code`) — so this is a lookup, not a match. Worth doing: without
    it every invoice line for these tickets shows a blank airline.
    """
    from app.models.airline import Airline

    wanted = {c.strip().upper() for c in codes if c and str(c).strip()}
    if not wanted:
        return {}
    rows = (await db.execute(
        select(Airline.iata_code, Airline.iata_numeric_code, Airline.name).where(
            or_(func.upper(Airline.iata_code).in_(wanted),
                Airline.iata_numeric_code.in_(wanted))
        )
    )).all()
    out: dict[str, str] = {}
    for iata, numeric, name in rows:
        if iata:
            out[iata.strip().upper()] = name
        if numeric:
            out[numeric.strip().upper()] = name
    return out


def _period(rows) -> tuple[date | None, date | None]:
    """(earliest, latest) issue date across a batch, for the statement header's validity.

    PARSED, not compared as strings. The export writes "15-Aug-2026", and on those
    `min()` is lexicographic: "01-Dec-2026" would sort before "31-Jan-2026" and the header
    would claim a period that starts in December and ends in January.
    """
    dates = [d for d in (safe_date(r.data.get("date_of_issue"), r.data.get("date_of_booking"))
                         for r in rows) if d is not None]
    return (min(dates), max(dates)) if dates else (None, None)


async def _ensure_statement(db: AsyncSession, header: StatementBatchBilling, *,
                            source_file: str | None, airline: str | None,
                            period: tuple[date | None, date | None]) -> TicketStatement:
    """One `ticket_statements` header per NDC batch, created once and refreshed thereafter.

    THE AGENCY GUARD, carried over from lcc_billing_projection verbatim.
    `agency_account.agency_statement_scope` claims a statement when either
    `agency_id == <agency>` OR (`agency_id IS NULL` AND the `agency` text equals an agency's
    name AND `customer_type IN (NULL, 'agency')`). So `customer_type = "direct"` is the
    actual guarantee that Agency Billing cannot claim these tickets — not the `agency_id`,
    which a payload can leak, and not the "NDC …" prefix on the name, which is defence in
    depth. The same three-way test appears in api/v1/reports.py, so this header is excluded
    from supplier income reports too.
    """
    stmt = await db.scalar(
        select(TicketStatement).where(TicketStatement.batch_id == header.billing_batch_id)
    )
    today = datetime.utcnow().date()
    valid_from = period[0] or today
    valid_to = period[1] or today

    carrier = (airline or "Statement").strip()
    if stmt is None:
        stmt = TicketStatement(
            batch_id=header.billing_batch_id,
            tenant_id=header.tenant_id,
            created_by_id=header.created_by_id,
            created_at=datetime.utcnow(),
            statement_type=_STATEMENT_TYPE,
            file_name=source_file or "NDC Statement",
            file_url=None,
        )
        db.add(stmt)

    stmt.statement_name = f"NDC - {carrier} - {source_file or header.batch_id}"
    stmt.agency = f"NDC {carrier}".strip()
    stmt.agency_id = None
    stmt.customer_type = "direct"
    stmt.customer_agency_id = None
    stmt.corporate_id = None
    stmt.customer_id = None
    stmt.valid_from = valid_from
    stmt.valid_to = valid_to
    return stmt


async def project_batch(db: AsyncSession, header: StatementBatchBilling, *,
                        row_ids: Collection[int] | None = None) -> dict:
    """Sync `uploaded_tickets` to the batch's current resolution. Caller commits.

    Two modes, and the difference is deletion:

      * `row_ids=None` — a full-batch SYNC. Groups that are no longer billable have their
        ticket DELETED, which is how a ticket leaves billing.
      * a set of ids — an ADDITIVE, SCOPED pass. Groups no row of which was selected are
        never read, never updated and never deleted; a selected row that has since lost its
        party is reported in `skipped_no_party` rather than un-billed. Withdrawing stays the
        whole-upload send's job, so "send these five" can never be the thing that quietly
        removed a sixth.

    ITERATES GROUPS, NOT ROWS — that is the one structural difference from LCC. Every row in
    a group carries the same `projected_ticket_id`, read off the anchor. A re-group that
    leaves two different ids in one group keeps the anchor's ticket and re-points the rest
    (`regrouped`); an anchor with no id whose latched row has one ADOPTS that ticket, which
    is the "this seat used to be its own ticket" transition and avoids a duplicate.
    """
    now = datetime.utcnow()
    scoped = row_ids is not None
    if not header.billing_batch_id:
        # Allocated once and reused forever, so the statement header is stable across every
        # re-projection instead of a new one appearing per run.
        header.billing_batch_id = str(uuid.uuid4())
        await db.flush()

    rows = (await db.execute(
        select(Ndc).where(Ndc.batch_id == header.batch_id,
                          Ndc.tenant_id == header.tenant_id,
                          Ndc.created_by_id == header.created_by_id,
                          Ndc.is_total.is_(False))
        .order_by(func.coalesce(Ndc.row_seq, Ndc.id).asc())
    )).scalars().all()
    if not rows:
        return {"statement_batch_id": header.billing_batch_id, "scoped": scoped,
                "requested": 0, "created": 0, "updated": 0, "deleted": 0, "regrouped": 0,
                "skipped_billed": 0, "skipped_no_party": 0, "skipped_not_billable": 0,
                "skipped_unlatched": 0, "latched_rolled_up": 0,
                "unclassified_ancillaries": 0, "duplicate_ticket_numbers": 0,
                "projected_rows": 0, "projected_tickets": 0}

    by_id = {r.id: r for r in rows}
    source_file = rows[0].source_file
    codes = {r.data.get("airline") for r in rows} | {r.data.get("airline_iata_code") for r in rows}
    names = await airline_names(db, [c for c in codes if c])

    # Groups are rebuilt from the STORED verdict, not recomputed — `resolve-customers` owns
    # the grouping, so what the worklist showed is what gets sent.
    groups: dict[str, Group] = {}
    for row in rows:
        key = row.bill_group_key or f"O:{row.id}"
        line = Line.from_row(row)
        line.group_key, line.latch_status = key, (row.bill_latch_status or ANCHOR)
        if key not in groups:
            groups[key] = Group(key=key, anchor=line)
        elif line.latch_status == ANCHOR:
            groups[key].latched.append(groups[key].anchor)
            groups[key].anchor = line
        else:
            groups[key].latched.append(line)

    selected = set(row_ids or ())
    await _ensure_statement(db, header, source_file=source_file,
                            airline=next((n for n in names.values()), None),
                            period=_period(rows))

    touched = [g for g in groups.values()
               if not scoped or any(ln.id in selected for ln in g.lines)]

    should: dict[str, Group] = {}
    skipped_no_party = skipped_not_billable = skipped_unlatched = 0
    for group in touched:
        anchor = group.anchor.source
        if _is_payment(anchor.bill_kind):
            skipped_not_billable += 1
            continue
        if not is_projectable(anchor):
            skipped_unlatched += 1
            continue
        if anchor.bill_status not in BILLABLE_STATUSES:
            skipped_no_party += 1
            continue
        should[group.key] = group

    # Existing tickets, read off the anchor first and any latched row second (the adoption
    # case). One query for every group in play.
    existing: dict[str, int] = {}
    for group in touched:
        tid = group.anchor.source.projected_ticket_id
        if tid is None:
            tid = next((ln.source.projected_ticket_id for ln in group.latched
                        if ln.source.projected_ticket_id is not None), None)
        if tid is not None:
            existing[group.key] = tid
    tickets: dict[int, UploadedTicket] = {}
    if existing:
        tickets = {t.id: t for t in (await db.execute(
            select(UploadedTicket).where(UploadedTicket.id.in_(set(existing.values())))
        )).scalars().all()}

    created = updated = deleted = regrouped = skipped_billed = 0

    def _link(group: Group, ticket_id: int | None) -> int:
        """Point every row in the group at one ticket, counting the re-pointing."""
        moved = 0
        for line in group.lines:
            row = by_id[line.id]
            if row.projected_ticket_id != ticket_id:
                if row.projected_ticket_id is not None and ticket_id is not None:
                    moved += 1
                row.projected_ticket_id = ticket_id
        return moved

    # ── update or free the groups already projected ──────────────────────────
    for key, ticket_id in existing.items():
        group = groups[key]
        ticket = tickets.get(ticket_id)
        if ticket is None:
            # The ticket was deleted underneath us; the FK already nulled the links.
            continue
        if ticket.billing_id is not None:
            # FROZEN: on an invoice. Never edited, never removed, whatever the resolution
            # now says — and that covers every latched row too, since they share the ticket.
            skipped_billed += 1
            should.pop(key, None)
            continue
        if should.pop(key, None) is None:
            if scoped:
                # ADDITIVE: the user ticked a row that has since lost its party. That is a
                # request to send it, not to withdraw it — leave the ticket alone.
                continue
            await db.delete(ticket)
            _link(group, None)
            deleted += 1
            continue
        anchor_row = group.anchor.source
        values = _build_ticket(group, header, now=now,
                               airline_name=names.get((anchor_row.data.get("airline") or "").strip().upper()),
                               source_file=source_file)
        for column, value in _only_columns(values).items():
            if column != "created_at":       # keep the original import timestamp
                setattr(ticket, column, value)
        regrouped += _link(group, ticket.id)
        updated += 1

    # ── insert what is newly billable ────────────────────────────────────────
    for group in should.values():
        anchor_row = group.anchor.source
        values = _build_ticket(group, header, now=now,
                               airline_name=names.get((anchor_row.data.get("airline") or "").strip().upper()),
                               source_file=source_file)
        ticket = UploadedTicket(**_only_columns(values))
        db.add(ticket)
        await db.flush()                     # assign the PK before linking back
        _link(group, ticket.id)
        created += 1

    # Two figures worth reporting rather than discovering later on an invoice.
    unclassified = sum(1 for g in groups.values() for ln in g.latched
                       if ln.bucket == DEFAULT_ANCILLARY_BUCKET)

    # Ticket numbers this upload is putting into billing that are ALREADY there from
    # somewhere else — the signal that the same file has been uploaded twice. NDC carries a
    # real ticket number, unlike LCC, so that is newly possible and worth saying out loud.
    #
    # Counted ACROSS statements, never within this one: a ticket and its own credit note
    # share a document number by definition, so counting duplicates inside the batch fired
    # on every file that contained a refund — a warning that cried wolf on normal data.
    numbers = {g.anchor.doc for g in should.values() if g.anchor.doc}
    duplicates = 0
    if numbers:
        duplicates = await db.scalar(
            select(func.count(func.distinct(UploadedTicket.ticket_number))).where(
                UploadedTicket.tenant_id == header.tenant_id,
                UploadedTicket.ticket_number.in_(numbers),
                UploadedTicket.batch_id != header.billing_batch_id,
            )
        ) or 0

    header.projected_at = now
    # Always the whole batch, both modes — it is the count the uploads list shows.
    header.projected_rows = await db.scalar(
        select(func.count()).select_from(Ndc)
        .where(Ndc.batch_id == header.batch_id, Ndc.projected_ticket_id.isnot(None))
    ) or 0
    header.projected_tickets = await db.scalar(
        select(func.count(func.distinct(Ndc.projected_ticket_id))).select_from(Ndc)
        .where(Ndc.batch_id == header.batch_id, Ndc.projected_ticket_id.isnot(None))
    ) or 0
    # A scoped send that projected nothing must not claim the batch is in billing.
    if not scoped or header.projected_rows:
        header.resolution_status = "projected"

    return {
        "statement_batch_id": header.billing_batch_id,
        "scoped": scoped,
        "requested": len(touched),
        "created": created,
        "updated": updated,
        # Always 0 when scoped — the delete branch above cannot be reached.
        "deleted": deleted,
        "regrouped": regrouped,
        "skipped_billed": skipped_billed,
        "skipped_no_party": skipped_no_party,
        "skipped_not_billable": skipped_not_billable,
        "skipped_unlatched": skipped_unlatched,
        # Over every group this send touched, not just the newly created ones: on a
        # re-send `should` has been emptied by the update branch above, and reporting 0
        # would read as "the ancillaries stopped rolling up".
        "latched_rolled_up": sum(len(g.latched) for g in touched),
        "unclassified_ancillaries": unclassified,
        "duplicate_ticket_numbers": duplicates,
        "projected_rows": header.projected_rows,
        "projected_tickets": header.projected_tickets,
    }
