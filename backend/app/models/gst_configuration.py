from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Boolean, Integer, Numeric, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


# ── the three things a GST rate can be charged ON ──────────────────────────────
#
# Every rule the business has is "some money amount × a taxable-value % × a rate %".
# Only the money amount differs, so the basis is a small closed set rather than a
# free-text formula. Kept as plain strings (not a DB Enum) to match every other
# choice column in this schema — corporates.billing_type, agencies.agency_type —
# so adding a fourth basis is a code change, never a migration.
BASIS_BASIC_FARE     = "basic_fare"       # the fare the airline pays commission on
BASIS_SERVICE_CHARGE = "service_charge"   # the agency's own service charge / fee
BASIS_TOTAL_COST     = "total_cost"       # fare + taxes + service charge
# What an agency actually earns on a sale: the markup it adds, PLUS any service
# charge on the ticket. Separate from BASIS_SERVICE_CHARGE because that column is
# populated only by B2B consolidator statements — it is NULL on every LCC row and
# on every ticket punched by hand — so a rule taxing it alone computes zero tax on
# most real sales. The markup is where the earning actually is, and the service
# charge is added to it when a statement happens to carry one.
BASIS_MARKUP         = "markup"           # markup + service charge

GST_BASES = (BASIS_BASIC_FARE, BASIS_SERVICE_CHARGE, BASIS_TOTAL_COST, BASIS_MARKUP)

CATEGORY_ABATEMENT = "abatement"
CATEGORY_NORMAL    = "normal"
GST_CATEGORIES = (CATEGORY_ABATEMENT, CATEGORY_NORMAL)

# ── how each category is subdivided ────────────────────────────────────────────
#
# BOTH categories are subdivided, but along different axes, so `sub_category` is
# read against its own category and never on its own:
#
#   abatement → domestic | international   what the TRIP is. Rule 32(3) of the
#               CGST Rules deems 5% of basic fare for a domestic booking and 10%
#               for an international one — the same rule, two figures.
#   normal    → agency | reseller          who the CUSTOMER is. Reuses the exact
#               vocabulary corporates.billing_type / customers.billing_type
#               already store, so a config row can be looked up straight from a
#               customer without translating between two sets of names.
#
# The normal route taxes actual consideration (service charge, or the whole sale)
# and does not vary by sector, which is why domestic/international applies to
# abatement alone rather than being a third column on every row.
SUB_DOMESTIC      = "domestic"
SUB_INTERNATIONAL = "international"
SUB_AGENCY        = "agency"
SUB_RESELLER      = "reseller"

SUB_CATEGORIES_BY_CATEGORY = {
    CATEGORY_ABATEMENT: (SUB_DOMESTIC, SUB_INTERNATIONAL),
    CATEGORY_NORMAL:    (SUB_AGENCY, SUB_RESELLER),
}

# The union, for column-level validation that does not yet know the category.
GST_SUB_CATEGORIES = tuple(
    s for subs in SUB_CATEGORIES_BY_CATEGORY.values() for s in subs
)


# ── the three schemes a business can bill under ────────────────────────────────
#
# A SCHEME IS A CHOICE; A SUB-CATEGORY IS NOT. Rule 32(3) of the CGST Rules is an
# election made by the registered person — a business opts into the abatement
# basis or stays on the normal one, and that governs every invoice it raises.
# Whether a given ticket is then abated at 5% or 10% follows from the sector, so
# domestic/international is a property of the TICKET, never a second decision.
#
# That is why the three schemes below are not simply the four (category,
# sub_category) pairs: abatement is ONE scheme spanning TWO rules.
#
#   abatement  → the ABD and ABI rules, picked per ticket by SECTOR
#   normal     → the NA and NR rules, picked per party by BILLING TYPE
#
# BOTH schemes span two rules, and in neither case does the workspace choose
# between them — the election is only which BASIS applies. Within abatement the
# sector decides; within normal the customer's own `billing_type` decides
# ('agency' taxes the service charge, 'reseller' taxes the whole sale), which is
# already how services/billing_calc.compute_gst behaves and is set per party when
# they are onboarded in User Master.
#
# Stored on tenants.gst_scheme as a slug rather than as a row id, because a
# single id could not name a two-rule scheme, and because the rules are
# effective-dated — an id would pin a workspace to one dated row, so a later rate
# revision would silently never apply to it.
SCHEME_ABATEMENT = "abatement"
SCHEME_NORMAL    = "normal"

# scheme -> (category, the sub-categories it covers)
SCHEME_MAP = {
    SCHEME_ABATEMENT: (CATEGORY_ABATEMENT, (SUB_DOMESTIC, SUB_INTERNATIONAL)),
    SCHEME_NORMAL:    (CATEGORY_NORMAL,    (SUB_AGENCY, SUB_RESELLER)),
}

GST_SCHEMES = tuple(SCHEME_MAP)

# What the screens call each scheme. Here rather than in the frontend so the
# master page, My Profile and any future export all name them identically.
SCHEME_LABELS = {
    SCHEME_ABATEMENT: "Abatement",
    SCHEME_NORMAL:    "Normal",
}


class GstConfiguration(Base):
    """One GST rule: what the tax is charged on, and at what rates.

    A GLOBAL master (Master Governance → GST Configuration). Like IataCommission
    the row carries a nullable tenant_id, but the platform admin's rows are the
    ones that matter and they are global (tenant_id NULL); the column exists so a
    tenant-specific override remains possible without a migration.

    THE WHOLE POINT IS THAT NO FORMULA IS HARDCODED. Each row evaluates as

        taxable_value = <basis amount> × taxable_value_pct / 100
        cgst          = taxable_value × cgst_pct / 100
        sgst          = taxable_value × sgst_pct / 100
        igst          = taxable_value × igst_pct / 100

    which reproduces every business rule from data alone:

        Abatement / Domestic (ABD)      basis=basic_fare      taxable_value_pct=5
                                        → CGST = Basic × 5% × 9%
        Abatement / International (ABI) basis=basic_fare      taxable_value_pct=10
                                        → CGST = Basic × 10% × 9%
        Normal / Agency (NA)            basis=service_charge  taxable_value_pct=100
                                        → CGST = ServiceCharge × 9%
        Normal / Reseller (NR)          basis=total_cost      taxable_value_pct=100
                                        → CGST = (fare + taxes + service charge) × 9%

    CGST+SGST AND IGST ARE MUTUALLY EXCLUSIVE. All three rates live on the row
    because the row does not know where the supply lands; the caller picks the
    pair by place of supply. services/gst_calc.py is what enforces that — never
    read the three columns and add them up.
    """
    __tablename__ = "gst_configurations"
    __table_args__ = (
        # One live rule per (scope, code, effective date). valid_from is in the key
        # so a rate change is a NEW row with a later date rather than an edit that
        # silently restates history.
        UniqueConstraint("tenant_id", "code", "valid_from", name="uq_gst_config_scope_code_from"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    # Nullable, unlike IataCommission.created_by_id: the three default rows are
    # seeded by the migration itself, and no user account exists to attribute them to.
    created_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # ── identity ──────────────────────────────────────────────────────────────
    code:          Mapped[str]        = mapped_column(String(10), nullable=False, index=True)   # 'AB' | 'NA' | 'NR'
    name:          Mapped[str]        = mapped_column(String(120), nullable=False)
    category:      Mapped[str]        = mapped_column(String(20), nullable=False, index=True)   # see GST_CATEGORIES
    # Nullable at the column level only so gst_config_02 could backfill the row
    # seeded before abatement was split; every row carries one. Which values are
    # legal depends on the category — see SUB_CATEGORIES_BY_CATEGORY.
    sub_category:  Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    # ── the formula, as data ──────────────────────────────────────────────────
    basis:             Mapped[str]   = mapped_column(String(30), nullable=False)                # see GST_BASES
    # The slice of the basis that is taxable. 5 for the Rule 32(3) abatement,
    # 100 when the whole amount is taxable. Numeric(7,3) so 5, 10 and 12.5 all fit.
    taxable_value_pct: Mapped[float] = mapped_column(Numeric(7, 3), nullable=False, default=100)

    # ── rates ─────────────────────────────────────────────────────────────────
    cgst_pct:      Mapped[float]      = mapped_column(Numeric(6, 3), nullable=False, default=0)
    sgst_pct:      Mapped[float]      = mapped_column(Numeric(6, 3), nullable=False, default=0)
    igst_pct:      Mapped[float]      = mapped_column(Numeric(6, 3), nullable=False, default=0)

    # ── documentation ─────────────────────────────────────────────────────────
    sac_code:      Mapped[str | None]  = mapped_column(String(20), nullable=True)   # e.g. '998551'
    valid_from:    Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to:      Mapped[date | None] = mapped_column(Date, nullable=True)
    notes:         Mapped[str | None]  = mapped_column(Text, nullable=True)

    is_active:     Mapped[bool]     = mapped_column(Boolean, default=True, nullable=False)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
