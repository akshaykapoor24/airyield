from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, Numeric, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


# The distribution channel a booking is made through. These are the two worlds a
# sub-agency trades in and they are commercially different, which is the whole
# reason this vocabulary exists:
#
#   GDS — the sub-agent books on OUR IATA stock through a mirror office, so the
#         BSP liability is ours the moment the ticket is issued. Credentials are
#         mirror ids.
#   LCC — each airline runs its own agent portal and settles through its own
#         wallet, so exposure is smaller and capped per carrier. Credentials are
#         portal login / airline ids.
#
# Uppercase to match the repo's existing GDS/LCC convention (`Deal.airline_type`,
# `AirlineClassMaster.airline_type`), NOT the lowercase used by `agency_type`.
CHANNELS = {"GDS", "LCC"}

# What a party TRADES ON, as opposed to what a single arrangement or credential
# belongs to. An entity may work both channels; a terms period and a login id may
# not — see AgencyTerms / AgencyLoginId.
#
# "BOTH" IS READ-ONLY FOR AGENCIES NOW. An agency working both channels is
# onboarded TWICE — one row per channel — so that each channel gets its own
# terms, its own deposit and its own line in the table, and so that picking one
# in a dropdown is unambiguous. New agencies are therefore GDS or LCC (see
# AGENCY_CHANNELS below); "BOTH" survives here only for rows created before that
# and for AgencyEntity, whose scope genuinely can span the two.
CHANNEL_SCOPES = {"GDS", "LCC", "BOTH"}

# What a NEW agency may declare. Deliberately narrower than CHANNEL_SCOPES.
AGENCY_CHANNELS = {"GDS", "LCC"}

# An agency entered by hand rather than picked from a supplier branch still needs
# a branch key, because (user_id, name, branch_code) is what keeps two branches of
# one vendor apart.
DEFAULT_BRANCH_CODE = "MAIN"


def norm_channel(v: str | None) -> str | None:
    """'  gds ' -> 'GDS'; blank -> None. Mirrors classes.py's airline_type handling."""
    return (str(v).strip().upper() or None) if v else None


def scope_covers(scope: str | None, channel: str) -> bool:
    """Does a GDS|LCC|BOTH scope include this single channel?"""
    return scope == "BOTH" or scope == channel


class Agency(Base):
    """One BRANCH of a sub-agency the user works with ("User master → Agency Master").

    User-scoped: every user maintains their OWN set of agencies, visible only to
    them. Details are COPIED from the global suppliers master at add-time — there
    is no live foreign key back to a supplier, so editing a supplier later never
    rewrites an agency.

    ONE ROW IS ONE BRANCH ON ONE CHANNEL, and that is deliberate. A vendor exists
    as several supplier rows, one per branch (three "Air India Limited", fourteen
    "Riya Travel & Tours"). Lords Delhi and Lords Mumbai are separate commercial
    relationships — separate deposits, separate limits, separate invoices — so
    they are separate agencies. So are Lords Delhi GDS and Lords Delhi LCC: an
    agency is routinely cash on GDS (we carry the BSP liability, so it pays first)
    and credit on LCC (each airline settles through its own wallet, so exposure is
    capped), and the two accounts never net against each other. All three are held
    apart by `uq_agencies_user_name_branch_channel` on
    (user_id, name, branch_code, channels). `branch_code` is a snapshot of
    `suppliers.code` (unique across the supplier master) rather than a foreign key,
    so deleting a supplier can neither orphan nor collide an agency.

    THE TRAP THAT COMES WITH THAT. Ticket statements record only a bare vendor
    NAME (`ticket_statements.agency`), so two rows for one vendor would both
    match the same tickets and whichever billed first would take them —
    `uploaded_tickets.billing_id` is a single FK. That is why
    `ticket_statements.agency_id` exists: billing resolves by id when it is set,
    and falls back to the name match ONLY when that name resolves to exactly one
    agency. An ambiguous name refuses to bill rather than guessing — and a vendor
    onboarded on both channels IS ambiguous, so its statements must be uploaded
    against a picked agency. Every dropdown that offers agencies therefore labels
    them name — branch · channel; a label that stops at the branch would show two
    identical options. The same care is needed in the `_agency_resolver` helpers in
    agency_entities.py and agency_login_ids.py, which now key by
    (name, branch_code, channel) for the same reason.

    Commercial terms are NOT here. They live in `agency_terms`, one effective-dated
    row per channel, because an agency is routinely cash on one channel and credit
    on the other — Lords pays up front on GDS (we carry the BSP liability) and runs
    a credit line on LCC. A single `agency_type` column could not say that, and the
    denormalised copy that used to sit on this row had two disagreeing writers.
    `channels` declares WHICH channels this branch trades on; every one of them must
    have exactly one open terms row.
    """
    __tablename__ = "agencies"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "name", "branch_code", "channels",
            name="uq_agencies_user_name_branch_channel",
        ),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    user_id:       Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)

    name:          Mapped[str]        = mapped_column(String(255), nullable=False)   # copied from supplier.name

    # ── Branch identity ──────────────────────────────────────────────────────
    # supplier_id is provenance only (which row we copied from) and may be NULL for
    # a hand-entered agency; branch_code is the key that makes the row unique.
    supplier_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    # The supplier-master request this agency was typed in under, when it was not
    # picked from the master. The master holds a couple of thousand agencies and
    # the trade has lakhs, so "not in the list" is the normal case, not an error:
    # the agency is created and usable at once, and a request goes to the platform
    # admin in parallel. Approving it inserts the vendor into `suppliers` for
    # everybody and back-fills `supplier_id` here — see the approve endpoint in
    # api/v1/suppliers.py.
    #
    # Two rows share ONE request when a vendor is onboarded on both channels; the
    # back-link updates every agency pointing at the approval, not just one.
    #
    # NULL means one of three different things, and they are distinguishable only
    # together with supplier_id: picked from the master (supplier_id set), typed in
    # before this existed or via an XLS upload (both NULL — those rows offer a
    # "Request master entry" action), or a request that was deleted.
    supplier_request_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("supplier_approvals.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    branch_code:   Mapped[str]        = mapped_column(String(50),  nullable=False)   # copied from supplier.code, else "MAIN"
    branch_name:   Mapped[str | None] = mapped_column(String(255), nullable=True)    # supplier.branch or city, display only

    # The branch's postal address. Copied from the supplier's address_1..3 at
    # add-time; `state` has NO source in the master (it holds region_chapter —
    # "WESTERN REGION" — which is an IATA chapter, not a state) so it is typed in.
    # Entities inherit all three as their default address, because an entity is a
    # office of this branch and usually sits at the same place.
    #
    # `state` is NULLABLE but REQUIRED on every path where a human types it (the
    # Add Agency form, an edit, an XLS row). It stays nullable because bulk-add
    # from the supplier master has nothing to put there and because rows created
    # before this predate the rule. It is required because it is what a GSTIN's
    # first two characters are checked against — see gst_number below.
    address:       Mapped[str | None] = mapped_column(Text, nullable=True)
    state:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    city:          Mapped[str | None] = mapped_column(String(120), nullable=True)    # branch city
    region_chapter: Mapped[str | None] = mapped_column(Text, nullable=True)          # branch region / chapter
    # TAX IDS, IN THE ORDER THEY CAN BE CHECKED. `state` fixes the first two
    # characters of the GSTIN and `pan_number` fixes characters 3-12, so the Add
    # Agency form asks for both before it offers the GSTIN box and
    # app.core.india_tax verifies all three against each other.
    # `gst_registered` is stored rather than inferred from `gst_number IS NOT NULL`:
    # "this agency is not registered" and "nobody has filled the GSTIN in yet" are
    # different facts, and only the first one means the blank is correct.
    gst_registered: Mapped[bool]      = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    gst_number:    Mapped[str | None] = mapped_column(String(20),  nullable=True)   # only set when gst_registered
    pan_number:    Mapped[str | None] = mapped_column(String(20),  nullable=True)
    # Wide enough for the supplier directory's telephone_mobile / email_address,
    # which are the columns that actually hold contact data (max seen: 134 / 334).
    contact_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes:         Mapped[str | None] = mapped_column(Text, nullable=True)

    # GDS or LCC — which channel this row trades on, and part of what makes it
    # unique. A new agency is one or the other; working both means being onboarded
    # twice, once per channel, which is why the Add Agency form no longer offers a
    # "Both" card. Every declared channel must have exactly one open `agency_terms`
    # row; widening or narrowing goes through POST /agencies/{id}/channels/open|close,
    # never a PATCH, because adding a channel opens a commercial arrangement and
    # removing one has to close it at a settled balance.
    #
    # "BOTH" still occurs, in rows created before the split and in any row widened
    # through /channels/open, so every reader must keep using `scope_covers` rather
    # than an equality test. What open_channel will NOT do is widen a row onto a
    # channel a sibling row already covers — that would bill the same tickets twice.
    channels:      Mapped[str]        = mapped_column(String(10), nullable=False)

    # ── Service charge / service fee ─────────────────────────────────────────
    # TWO DIRECTIONS, BECAUSE THIS ROW IS READ FROM BOTH SIDES OF THE BUSINESS.
    # The same agency reaches us as a VENDOR (`deals.supplier_agency_id` — we buy
    # from them, so what they charge is a COST) and as a CUSTOMER (`deals.agency_id`,
    # `billings.agency_id` — we sell to them, so what we charge is INCOME). The
    # migration deal_supplier_agency_01 already names that opposition. One pair of
    # columns would be read as a cost on one screen and as income on another with
    # nothing saying which was meant, and the rate we pay Lords is not the rate we
    # charge Lords — so each direction is stored separately.
    #
    # PER CHANNEL FOR FREE. One row is one branch on ONE channel (see the class
    # docstring), so Lords Delhi GDS and Lords Delhi LCC already carry their own
    # rates without any extra modelling.
    #
    # NOT IN `agency_terms`, even though these are commercial terms: a terms period
    # may only be closed and reopened at a cycle boundary with a settled, zero
    # balance (services/agency_account.switch_blockers). That is right for a credit
    # limit and absurd for a fee rate. The shape follows `customers.markup_type` /
    # `markup_value` — one Numeric column holding either a percentage or a rupee
    # amount, with `*_type` saying which.
    #
    # `*_gst` IS 'inclusive' | 'exclusive' AND IS NOT COSMETIC. Exclusive means the
    # value is net and tax is added on top; inclusive means the value already
    # contains it and must be divided out. A ₹1,000 fee differs by ₹180 between the
    # two on every line, so it is stored beside the value, never inferred from it.
    # NULL reads as exclusive — see service_fee.DEFAULT_GST_TREATMENT for why that
    # is the safe default rather than the other way round.
    #
    # ALL SIX ARE NULLABLE AND NOTHING BACKFILLED THEM. NULL means "nobody has been
    # asked", which is honest for every row created before this existed; a stored 0
    # means "we deliberately charge nothing". Resolve them through
    # services/service_fee.py (vendor_service_charge / customer_service_fee) rather
    # than reading the columns directly — it prunes a half-set rate, which would
    # otherwise bill as zero and leak revenue silently.
    #
    # NOTHING BILLS FROM THESE YET: api/v1/agency_billing.py still hardcodes its
    # markup at 0.0. They are collected and stored; the wiring is a separate pass.
    vendor_service_charge_type:   Mapped[str | None]   = mapped_column(String(20), nullable=True)   # percentage | fixed
    vendor_service_charge_value:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    vendor_service_charge_gst:    Mapped[str | None]   = mapped_column(String(20), nullable=True)   # inclusive | exclusive

    customer_service_fee_type:    Mapped[str | None]   = mapped_column(String(20), nullable=True)   # percentage | fixed
    customer_service_fee_value:   Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    customer_service_fee_gst:     Mapped[str | None]   = mapped_column(String(20), nullable=True)   # inclusive | exclusive

    is_active:     Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
