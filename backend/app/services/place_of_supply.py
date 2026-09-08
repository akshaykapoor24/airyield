"""Which taxes a sale carries: CGST + SGST, or IGST.

A supply is intra-state when the supplier and the recipient sit in the same
state, and inter-state when they do not. Intra-state splits the rate in half
across CGST and SGST; inter-state charges the whole of it as IGST. Never both —
services/gst_calc enforces that; this module only decides WHICH.

WHY THIS IS NOT IN core/india_tax.py
────────────────────────────────────
That module knows about strings — state codes, GSTIN formats, check digits — and
must not import models. This one knows about Tenant / Corporate / Customer rows
and where each keeps its GSTIN, which differs per table (`tenants.gst_number`,
`corporates.gst_no`, `agencies.gst_number`), so it belongs beside the other
billing services.

THE LADDER, AND WHY THE GSTIN OUTRANKS THE ADDRESS
──────────────────────────────────────────────────
A GSTIN is a registration in one state and its first two characters ARE that
state. A postal address is letterhead. They can disagree, and in this database
they do: one workspace is filed under code 33 (Tamil Nadu) with "Delhi" typed in
its address. Reading the address there would put every one of its sales in the
wrong tax head, so the GSTIN wins wherever there is one.

An EMPLOYEE inherits their employer's place of supply. That is not a shortcut —
when a corporate is billed for its employee's ticket, the corporate is the
recipient, so its registration is the one that counts.

UNDECIDABLE IS A REAL ANSWER
────────────────────────────
When neither side yields a state the result is None, not False. Defaulting to
intra-state would quietly bill CGST + SGST on what might be an inter-state
supply; the caller has to choose that fallback knowingly, and say so on screen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.india_tax import GST_STATE_CODES, canonical_state, place_of_supply_code


@dataclass(frozen=True)
class PlaceOfSupply:
    """The decision, and enough of its reasoning to show a user."""
    supplier_code: Optional[str]
    recipient_code: Optional[str]
    #: True = IGST, False = CGST + SGST, None = could not be decided.
    interstate: Optional[bool]
    #: Which rung of the ladder answered, for the audit trail and the UI chip.
    source: str
    #: One sentence a human can act on.
    note: str

    @property
    def decided(self) -> bool:
        return self.interstate is not None

    @property
    def treatment(self) -> str:
        """The stored form of this decision — see billing_calc's TREATMENT_*."""
        if self.interstate is None:
            return "unsplit"
        return "igst" if self.interstate else "cgst_sgst"

    @property
    def supplier_state(self) -> Optional[str]:
        return GST_STATE_CODES.get(self.supplier_code or "")

    @property
    def recipient_state(self) -> Optional[str]:
        return GST_STATE_CODES.get(self.recipient_code or "")


def _side(gstin: Optional[str], state: Optional[str]) -> tuple[Optional[str], str]:
    """One party's state code, and which field produced it."""
    from app.core.india_tax import gstin_state_code, state_code
    code = gstin_state_code(gstin)
    if code:
        return code, "gstin"
    code = state_code(state)
    if code:
        return code, "state"
    return None, "none"


def supplier_side(tenant) -> tuple[Optional[str], str]:
    """The workspace raising the invoice."""
    if tenant is None:
        return None, "none"
    return _side(getattr(tenant, "gst_number", None), getattr(tenant, "state", None))


def recipient_side(party, *, corporate=None) -> tuple[Optional[str], str]:
    """Whoever is being billed.

    `corporate` is the employer of a customer being billed THROUGH their company —
    pass it when the ticket names a corporate, because then the corporate is the
    recipient and its registration decides, not the passenger's.
    """
    if corporate is not None:
        code, how = _side(getattr(corporate, "gst_no", None), getattr(corporate, "state", None))
        if code:
            return code, f"corporate_{how}"

    if party is None:
        return None, "none"

    # `gst_no` on customers/corporates, `gst_number` on agencies — the two masters
    # spell it differently, so try both rather than making callers care.
    gstin = getattr(party, "gst_no", None) or getattr(party, "gst_number", None)
    code, how = _side(gstin, getattr(party, "state", None))
    if code:
        return code, how

    # An employee with nothing of their own still inherits their employer, whose
    # row the caller may not have loaded separately.
    linked = getattr(party, "corporate", None)
    if linked is not None:
        code, how = _side(getattr(linked, "gst_no", None), getattr(linked, "state", None))
        if code:
            return code, f"employer_{how}"

    return None, "none"


def place_of_supply(tenant, party, *, corporate=None) -> PlaceOfSupply:
    """Decide the tax heads for a sale from `tenant` to `party`."""
    ours, ours_how = supplier_side(tenant)
    theirs, theirs_how = recipient_side(party, corporate=corporate)

    if ours is None:
        return PlaceOfSupply(
            None, theirs, None, "no_supplier",
            "This workspace has no GSTIN or state in My Profile, so CGST/SGST/IGST "
            "cannot be split. Add one under My Profile.",
        )
    if theirs is None:
        return PlaceOfSupply(
            ours, None, None, "no_recipient",
            "This customer has no GSTIN and no state, so their place of supply is "
            "unknown. Add either to bill them correctly.",
        )

    interstate = ours != theirs
    ours_name = GST_STATE_CODES.get(ours, ours)
    theirs_name = GST_STATE_CODES.get(theirs, theirs)
    note = (
        f"{theirs_name} vs {ours_name} — different states, so IGST applies."
        if interstate else
        f"Both in {ours_name}, so CGST and SGST apply."
    )
    return PlaceOfSupply(ours, theirs, interstate, f"{ours_how}_{theirs_how}", note)


def as_payload(pos: PlaceOfSupply) -> dict:
    """The decision as the API returns it (schemas.customer.PlaceOfSupplyRead).

    A plain dict rather than the schema itself, so this service stays free of
    schema imports — the routers do `PlaceOfSupplyRead(**as_payload(pos))`.
    """
    return {
        "treatment": pos.treatment,
        "decided": pos.decided,
        "supplier_state": pos.supplier_state,
        "recipient_state": pos.recipient_state,
        "source": pos.source,
        "note": pos.note,
    }


def state_choices() -> list[str]:
    """Every state a party may be filed under, for a picker.

    Straight from the GSTIN code table so a chosen state always has a code to
    compare — a free-text state that india_tax cannot canonicalise is a state
    place of supply cannot read.
    """
    return sorted(GST_STATE_CODES.values())


__all__ = [
    "PlaceOfSupply",
    "as_payload",
    "place_of_supply",
    "supplier_side",
    "recipient_side",
    "state_choices",
    "canonical_state",
    "place_of_supply_code",
]
