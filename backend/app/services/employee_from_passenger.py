"""Filing a statement's passenger as an employee of the corporate they flew for.

A billing worklist can MATCH a passenger against the Employee Master but has never
been able to ADD one — ``services/customer_resolver`` says so in its own docstring: it
reads the masters and never writes them. So an unrecognised traveller meant leaving
the screen for User master → Employee Master, retyping the name, and coming back.
This is that round trip, as one call.

**Shared between the LCC and NDC worklists on purpose.** Their two routers are
otherwise deliberate copies of each other (see the note atop
``frontend/src/components/statements/ndc/NdcBillingWorklist.tsx``), and their GUARDS
genuinely differ — an NDC row can be latched to another ticket, an LCC row cannot. But
the rule below decides what lands in the Employee Master and on what terms, and two
copies of that would drift into two different answers to the same question. The guards
stay with each router; this does not.

Two duplicate checks stand in the way, and the gap between them is the whole reason
both are here:

  * ``party_dedupe.CustomerDuplicates`` keys on the EXACT name string per employer. It
    catches a second press of the button, and it CLAIMS each identity as it passes, so
    a bulk run over two rows naming one passenger files them once.
  * ``customer_resolver.CustomerIndex`` keys order-insensitively and drops single-letter
    initials. It catches ``"JATIN L K WASNIK"`` against a ``"Jatin lk wasnik"`` already
    on file — which the first check waves straight through, because the two strings
    differ. That is not a hypothetical: it is the row the worklist was already flagging
    "Initials only" when this was written.

The corporate's terms are copied down HERE rather than left to ``POST /customers/``,
which does not inherit anything. It does not need to: the form in front of it has
already done the copy in the browser (``lib/party.ts`` ``seedFromCorporate``). There is
no form in front of this, and an employee created with no ``billing_type`` is invoiced
with NO GST AT ALL — ``billing_calc.gst_taxable`` returns 0.0 for an unset type.
"""
from __future__ import annotations

from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.user import User
from app.services import customer_resolver as cres
from app.services.party_inherit import inherit_from_corporate

__all__ = ["EmployeeOutcome", "blocked_by_existing", "create_employee_from_passenger"]


class EmployeeOutcome(NamedTuple):
    """What happened for one row. ``reason`` is set only when nothing was created.

    Returned rather than raised so a bulk caller can skip one row and carry on; the
    single-row callers turn a refusal into the HTTP error.
    """
    created: bool
    reason: str | None = None
    customer_id: int | None = None
    display_name: str | None = None
    inherited: tuple[str, ...] = ()


def blocked_by_existing(index: "cres.CustomerIndex | None", display: str,
                        corporate_id: int, company: str | None) -> str | None:
    """Is someone under this employer already this person, however it is spelt?

    Scoped to the SAME employer deliberately. Two people of one name at two different
    companies are two different people — the exact-name check takes that stance
    (api/v1/customers.py) and undoing it here would refuse a legitimate namesake.
    """
    if index is None:
        return None
    match = index.resolve(display)
    for cid in match.candidate_ids:
        known = index.get(cid)
        if known is not None and known.corporate_id == corporate_id:
            return (f"“{display}” looks like {known.full_name}, already in Employee "
                    f"Master under {company}. Pick them in Bill to instead.")
    return None


async def create_employee_from_passenger(
    db: AsyncSession, user: User, display: str | None, corp, dupes,
    index=None,
) -> EmployeeOutcome:
    """Create the passenger as an employee of ``corp``. Does NOT touch the row.

    The caller owns the row — its guards, and pointing it at the new employee — because
    that is the part that differs between statement types.
    """
    display = (display or "").strip()
    if not display:
        return EmployeeOutcome(False, "This row has no passenger name.")

    # Last token is the surname, everything before it the given name — the same split
    # the billing projections already use to fill a ticket's name columns, so the
    # employee reads back the way the statement wrote it. A file using the GDS
    # SURNAME/FIRSTNAME order lands the two the other way round; matching still works,
    # because person_match_key sorts its tokens.
    first_name, last_name = cres.split_person_name(display)
    if not first_name:
        return EmployeeOutcome(False, "This row has no usable passenger name.")

    seen = blocked_by_existing(index, display, corp.id, corp.company)
    if seen:
        return EmployeeOutcome(False, seen)

    clash = dupes.check(first_name, last_name, corp.id, corp.company)
    if clash:
        return EmployeeOutcome(False, clash)

    # Blank everything the statement cannot know, then let the corporate fill it. The
    # order is the rule party_inherit states: inherit AFTER normalisation, never before.
    values: dict = {f: None for f in ("phone", "email", "markup_type", "markup_value",
                                      "billing_type", "gst_no", "pan_no")}
    values["gst_registered"] = False
    filled = inherit_from_corporate(values, corp)
    values.update(filled)

    customer = Customer(
        tenant_id=user.tenant_id,
        created_by_id=user.id,
        first_name=first_name,
        last_name=last_name,
        corporate_id=corp.id,
        # A MIRROR of the corporate's name, not an inherited default — the routers
        # rewrite it on link, unlink and rename, so it is set the same way they do.
        company=corp.company,
        # NOT inherited, deliberately: `state` is place of supply for a DIRECT bill,
        # and someone billed directly is billed where THEY are, not where their
        # employer is. frontend/src/components/party/PartyModal.tsx makes the same call.
        state=None,
        **values,
    )
    db.add(customer)
    await db.flush()          # the caller needs the id to point its row at them

    return EmployeeOutcome(True, None, customer.id, display, tuple(sorted(filled)))
