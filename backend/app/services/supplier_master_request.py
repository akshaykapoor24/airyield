"""Add a row to the shared supplier master — directly, or as a request.

The `suppliers` table is one global list every workspace reads. Nobody edits it
in place except the platform admin; everyone else asks, and an approval is what
actually writes the row (see api/v1/suppliers.py's approve endpoint).

That rule was implemented once, inline, in `POST /suppliers/`. Agency Master now
needs the same thing — a user onboarding an agency that is not in the master has
to be able to ask for it — so the rule lives here instead of being copied. One
implementation means the two entry points cannot drift on who may write directly,
what a generated code looks like, or which fields a request carries.

NOTHING HERE COMMITS. Both callers do more work in the same transaction — the
suppliers endpoint returns the created row, and the agencies endpoint writes an
Agency, its terms and its opening ledger entry alongside — so committing here
would split those apart and could leave an agency without its request or a
request without its agency.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import is_platform_admin
from app.models.supplier import Supplier
from app.models.supplier_approval import SupplierApproval
from app.models.user import User, UserRole, role_matches

# Who may put something into the master queue at all — every role except VIEWER,
# matching `POST /suppliers/`'s own guard and `canSubmitMasterRequest` on the
# frontend. Declared here because Agency Master now asks the same question, and
# two copies of "who may request" is how they come to disagree.
SUBMITTER_ROLES = (
    UserRole.PLATFORM_ADMIN,
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.OPERATIONS_USER,
    UserRole.FINANCE_USER,
    UserRole.APPROVER,
)


def can_submit_master_request(user: User) -> bool:
    """A view-only user reads the shared masters; they do not propose changes."""
    return role_matches(user.role, *SUBMITTER_ROLES)

# The vendor business fields `suppliers` and `supplier_approvals` share. `code`,
# `is_active` and the timestamps are deliberately absent: the approval table does
# not mirror them, and `code` is generated here rather than supplied by a caller.
SUPPLIER_VALUE_FIELDS = (
    "name", "vendor_type", "vendor_name", "branch", "branches",
    "contact_phone", "alternate_phone", "contact_email", "alternate_email",
    "gst_number", "pan_number", "notes",
)

# Directory / member-list fields, also shared by both tables. Kept as one constant
# so create / update / approve / bulk-upload cannot list them differently.
DIRECTORY_FIELDS = (
    "region_chapter", "membership_category",
    "address_1", "address_2", "address_3",
    "city", "pincode", "telephone_mobile", "website",
    "email_address", "alternate_email_id", "accounts_email",
    "fax_no", "representative_1", "representative_2",
)

ALL_FIELDS = (*SUPPLIER_VALUE_FIELDS, *DIRECTORY_FIELDS)


def directory_kwargs(obj) -> dict:
    """Extract the directory fields from a payload/ORM object as a kwargs dict."""
    return {f: getattr(obj, f, None) for f in DIRECTORY_FIELDS}


def value_kwargs(obj) -> dict:
    """Every shared field, from a payload/ORM object. `name` is stripped."""
    out = {f: getattr(obj, f, None) for f in ALL_FIELDS}
    if out.get("name"):
        out["name"] = str(out["name"]).strip()
    return out


async def generate_code(db: AsyncSession) -> str:
    """The next `SUPP-0001`-style code.

    Derived from max(id) rather than a sequence because the master was seeded from
    a spreadsheet whose rows carry no code of their own.
    """
    max_id = (await db.execute(select(func.max(Supplier.id)))).scalar() or 0
    return f"SUPP-{(max_id + 1):04d}"


async def create_or_request_supplier(
    db: AsyncSession,
    user: User,
    values: dict,
    *,
    code: str | None = None,
) -> tuple[Supplier | None, SupplierApproval | None]:
    """Put a new vendor into the master, or ask for it.

    Returns `(supplier, None)` when the caller may write the master directly — a
    platform admin — and `(None, approval)` for everyone else, whose row appears
    only once the request is approved.

    `values` holds the shared fields (use `value_kwargs`); anything absent lands
    NULL. Only `name` is required, matching the master itself, where `name` and
    `code` are the sole NOT NULL columns and `code` is generated here.

    Flushes so the caller has an id to link against; does not commit.
    """
    name = (values.get("name") or "").strip()
    if not name:
        raise ValueError("name is required to create or request a supplier.")

    clean = {f: values.get(f) for f in ALL_FIELDS}
    clean["name"] = name

    if is_platform_admin(user):
        supplier = Supplier(code=code or await generate_code(db), **clean)
        db.add(supplier)
        await db.flush()
        return supplier, None

    approval = SupplierApproval(
        **clean,
        submitted_by_id=user.id,
        tenant_id=user.tenant_id,
        status="pending",
        request_type="new",
        # A "new" request names no existing row. Approve reads this only on an
        # "update", and leaving it NULL is what tells the two apart.
        target_supplier_id=None,
    )
    db.add(approval)
    await db.flush()
    return None, approval


def supplier_values_from_agency(agency) -> dict:
    """Map an Agency onto the supplier master's field names.

    The two tables describe the same real-world vendor with different vocabularies,
    and the mapping is not one-to-one:

      * `agencies.address` is one free-text line; the master splits it across
        address_1..3, so it goes in address_1 whole rather than being guessed apart.
      * The master's own `contact_phone` / `contact_email` columns are empty across
        the entire seeded file — the real values live in `telephone_mobile` and
        `email_address` (see _from_supplier in api/v1/agencies.py, which reads them
        back out that way). Writing the pair the reader actually reads keeps a
        round trip lossless.
      * `agencies.state` has no counterpart at all. The master holds
        `region_chapter` — an IATA chapter such as "WESTERN REGION" — which is a
        different fact, so state is dropped rather than mangled into it.
      * `branch_code` is not sent either: it is the agency's own uniqueness key and
        the master generates its own `code` on approval.
    """
    return {
        "name": agency.name,
        "vendor_type": "AGENCY",
        "vendor_name": agency.name,
        "branch": agency.branch_name,
        "address_1": agency.address,
        "city": agency.city,
        "region_chapter": agency.region_chapter,
        "gst_number": agency.gst_number,
        "pan_number": agency.pan_number,
        "telephone_mobile": agency.contact_phone,
        "email_address": agency.contact_email,
        "notes": agency.notes,
    }
