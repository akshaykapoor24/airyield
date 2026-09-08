"""Which party columns survive when a ticket is tagged, and re-tagging a ticket.

`uploaded_tickets` carries four party columns — customer_type, customer_id,
corporate_id, customer_agency_id — and NO database constraint ties the type to
the id. `customer_type='direct'` with a `corporate_id` still set is perfectly
legal SQL and produces a ticket claimable by two billing screens at once, since
customer_ticket_scope and corporate_ticket_scope each read only their own id
column and ignore customer_type entirely.

So the rule that keeps them coherent lives in code, and it lives HERE rather than
being written out at each call site. It is the server-side twin of
frontend/src/lib/customerType.ts::buildTagPayload — the same discipline, enforced
where it cannot be skipped.
"""
from __future__ import annotations

from typing import Optional

CUSTOMER_TYPE_CORPORATE = "corporate"
CUSTOMER_TYPE_DIRECT = "direct"


def derive_party(
    customer_type: Optional[str],
    customer_id: Optional[int],
    corporate_id: Optional[int],
    *,
    employee_corporate_id: Optional[int] = None,
    upgrade_employee: bool = True,
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Normalise a party choice to (customer_type, customer_id, corporate_id).

    Ids that do not belong to the chosen type are dropped, so a stale id left over
    from a previously chosen type can never travel attached to the wrong one.

    The three states this produces, and who can then bill the ticket:

        customer_id + corporate_id   both      Customer Billing AND Corporate Billing
        customer_id alone            direct    Customer Billing only
        corporate_id alone           corporate Corporate Billing only

    `employee_corporate_id` is the picked customer's own `corporates.id` (None if
    they are an individual). It only matters when the type is 'direct':

      upgrade_employee=True  — the LCC resolver's behaviour. A customer who belongs
        to a corporate is an EMPLOYEE, so the tag becomes 'corporate' carrying both
        ids and the employer can bill their ticket. Right when a machine is
        guessing who a passenger is.

      upgrade_employee=False — the caller means the party literally. Re-tagging a
        ticket to bill an employee DIRECTLY must leave the corporate out entirely;
        carrying it would keep the ticket claimable by the employer and the
        correction the user asked for would silently do nothing. Right when a human
        has just pointed at a name.

    Clearing the tag (customer_type None) returns all-None, which makes the ticket
    UNTAGGED — and an untagged ticket falls back to passenger-name matching, so it
    can become visible to several parties at once. Callers should say so.
    """
    ct = (customer_type or "").strip().lower() or None
    if ct is None:
        return None, None, None

    if ct == CUSTOMER_TYPE_CORPORATE:
        # BOTH ids are meaningful together, and carrying them is deliberate:
        # customer_id names WHO FLEW, corporate_id names WHO PAYS. That pair is
        # what makes one ticket reachable by the employee in Customer Billing and
        # by the employer in Corporate Billing, because each scope reads only its
        # own id column. Callers that mean the corporate alone send no customer_id.
        return CUSTOMER_TYPE_CORPORATE, customer_id, corporate_id

    if ct == CUSTOMER_TYPE_DIRECT:
        if upgrade_employee and employee_corporate_id:
            return CUSTOMER_TYPE_CORPORATE, customer_id, employee_corporate_id
        return CUSTOMER_TYPE_DIRECT, customer_id, None

    # 'agency' reaches billing through its statement, never through this link —
    # see agency_account.agency_statement_scope. Callers validate the vocabulary
    # before getting here; this is the belt-and-braces.
    raise ValueError(f"Unsupported customer_type for a ticket party: {ct!r}")
