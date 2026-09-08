"""Validating the Supplier master row a third-party statement upload is attributed to.

A consolidator statement never names its sender — the sample GDS export's "Customer Name"
is the tenant's own name, as the consolidator's customer — so the uploader declares it,
exactly as an LCC upload declares its carrier. Without it the B2B supplier guard in
`services/deal_matching.py` has nothing to compare against and every row comes back
unmatched.

THE SOURCE IS THE PLATFORM-ADMIN SUPPLIER MASTER, and that is the point. It is the same
list the B2B deal form picks `supplier_name` from, so both sides of the match name the same
thing. The earlier version of this file read the tenant's own Agency Master instead, which
could not line up with a deal: `agencies` splits one vendor into a GDS row and an LCC row
with the same name, so a statement attributed to one of them was attributed to half a
relationship.

WHAT IS AND IS NOT CHECKED HERE. A supplier row is one branch and its `code` is unique, so
the id alone identifies the counterparty — there is no channel to validate, which is why
the channel rule that used to live here is gone rather than moved. What remains is
existence and `is_active`: 141 of the master's 2,340 names repeat across branches, so an id
that does not resolve is a stale client, and an inactive vendor is one nobody should be
filing new statements against.

`resolve_supplier_choice` is the rule itself — pure and session-free, so it is unit-tested
without a database, like `services/lcc_airline_selection.py`. Neither function raises
HTTPException: the router maps these errors to 400.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supplier import Supplier


class UnknownSupplier(ValueError):
    """Nothing was chosen, or the id is not in the supplier master. User-facing message."""


class InactiveSupplier(ValueError):
    """The chosen supplier has been deactivated."""


def supplier_label(supplier) -> str:
    """'Riya Travel & Tours — MUMBAI · SUPP-0421'.

    The branch and code are NOT decoration. Fourteen rows of the master share the name
    "Riya Travel & Tours", so a label that stops at the name shows fourteen identical
    options and the pick is a coin toss. `code` is the unique one.
    """
    parts = [supplier.name]
    where = getattr(supplier, "branch", None) or getattr(supplier, "city", None)
    if where:
        parts.append(f"— {where}")
    if getattr(supplier, "code", None):
        parts.append(f"· {supplier.code}")
    return " ".join(parts)


def resolve_supplier_choice(supplier):
    """The supplier to attribute this upload to, or a ValueError carrying what to tell the user."""
    if supplier is None:
        raise UnknownSupplier(
            "Select the agency this statement came from — the file itself doesn't name your "
            "consolidator, and the commission run needs it to find the right B2B deal. "
            "Names come from the Supplier master; ask your platform admin to add them if "
            "they aren't listed."
        )
    if not supplier.is_active:
        raise InactiveSupplier(
            f"'{supplier_label(supplier)}' is marked inactive in the Supplier master. Pick "
            f"another branch, or ask your platform admin to re-activate it."
        )
    return supplier


async def resolve_for_upload(db: AsyncSession, supplier_id: int | None):
    """The Supplier master row for an upload, or None.

    NOT scoped by tenant or user: `suppliers` is global platform-admin master data, unlike
    `agencies`, which every user maintains their own copy of. There is nothing here that
    belongs to one workspace, so there is nothing to scope by — the id either names a real
    vendor or it does not.
    """
    if supplier_id is None:
        return None
    return (await db.execute(
        select(Supplier).where(Supplier.id == supplier_id)
    )).scalar_one_or_none()


async def resolve(db: AsyncSession, supplier_id: int | None):
    """The whole check in one call: look the supplier up, then apply the rule."""
    return resolve_supplier_choice(await resolve_for_upload(db, supplier_id))
