"""How much work a workspace has actually put through the product.

The platform-admin console at ``/admin/subscriptions`` used to show two numbers,
Deals and Tickets. A workspace that had uploaded thousands of BSP rows, TGQ HMPR
sectors and third-party statements but no deal sheets read as ``0 / 0`` — exactly
like one that signed up and never came back. That is the wrong answer to the only
question that console exists to support: is this workspace worth keeping active?

So this module owns ONE list — every table a workspace fills by using the
product — and counts them all in a single round trip.

WHAT IS COUNTED
    Uploaded / transactional data at its top-level grain. Deals, tickets, the BSP
    settlement and summary legs, ADM/ACM/RA, every spec-driven vendor statement,
    LCC Detailed, the statement and billing records the workspace creates.

WHAT IS NOT, AND WHY
    * Child rows — deal_incentives, deal_incentive_slabs, deal_incentive_slab_values,
      deal_rules, deal_rule_conditions, bsp_tax_breakups, customer_statement_tickets,
      approval steps. One deal is one record, not one plus its seventy descendants;
      counting them would make the total a function of schema shape rather than of
      user activity.
    * Upload-session parents whose rows are already counted — bsp_statements,
      bsp_summary_statements, deal_statements, deal_batches, lcc_detailed_batch.
      Counting the file AND its rows reports 1001 for a 1000-row upload.
    * Derived caches — ticket_calculations (calculation-run history) and
      ticket_reconciliation, whose own docstring calls it "a report/cache, not a
      source of truth".
    * Config / master data — users, customers, entities, login ids, agencies,
      agency_terms, suppliers, corporates, iata_commissions, every *_approvals
      table. A workspace that has only finished onboarding must still read as
      unused.
    * agency_ledger — the agency's running account. Its `invoice` entries are
      posted automatically when a billing is created, and billings is already
      counted, so counting the ledger too would report those twice. (The
      hand-posted topups and receipts are therefore uncounted; revisit if a
      workspace ever runs agency accounts without raising billings.)
    * bsp_parse_errors — has no tenant_id at all, and records failures rather
      than records.
    * The dead legacy tables ``tickets``, ``income_records`` and ``documents``,
      which carry no tenant_id. ``uploaded_tickets`` is the real ticket store.

``tests/test_tenant_usage.py`` fails if a tenant-scoped table appears that is
neither counted here nor named in EXCLUDED_TABLES below — so this docstring stays
true as the schema grows.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airline_adjustment import ADJUSTMENT_MODELS
from app.models.billing import Billing
from app.models.bsp_statement import BspStatementRow
from app.models.bsp_summary import BspSummaryRow
from app.models.customer_statement import CustomerStatement
from app.models.deal import Deal
from app.models.income_summary import IncomeSummary
from app.models.lcc_detailed import LccDetailed
from app.models.series_contract import SeriesContract
from app.models.statement_row import STATEMENT_MODELS
from app.models.ticket_adjustment import TicketAdjustment
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket
from app.services.statement_spec import STATEMENT_SPECS


@dataclass(frozen=True)
class UsageSource:
    """One counted table."""
    key: str      # stable machine key — also the breakdown dict key
    label: str    # what the console shows; matches the product's own navigation
    model: type


# ── The list ─────────────────────────────────────────────────────────────────
# Ordered the way the console reads it: the two headline numbers first, then the
# statement families in nav order.
USAGE_SOURCES: list[UsageSource] = [
    UsageSource("deals",               "Deals",                Deal),
    UsageSource("tickets",             "Tickets",              UploadedTicket),
    UsageSource("ticket_statements",   "Internal Statements",  TicketStatement),
    UsageSource("customer_statements", "Customer Statements",  CustomerStatement),
    UsageSource("bsp",                 "BSP",                  BspStatementRow),
    UsageSource("bsp_summary",         "BSP Summary",          BspSummaryRow),
]

# ADM / ACM / RA — three physical tables sharing one mixin.
USAGE_SOURCES += [
    UsageSource(f"adj_{slug}", slug.upper(), model)
    for slug, model in ADJUSTMENT_MODELS.items()
]

# LCC Detailed keeps its own batch+rows schema and is deliberately absent from
# STATEMENT_MODELS, so it is listed by hand rather than picked up by the loop.
USAGE_SOURCES.append(UsageSource("lcc_detailed", "Detailed Statement", LccDetailed))

# Every spec-driven vendor statement: TGQ HMPR, NDC, DI, Divided PNR, Flown
# Report, CTA/BTA, third-party GDS and LCC. Labels come from STATEMENT_SPECS so
# the console can never drift from the product's own wording — there is no second
# list to keep in sync. Only the two third-party slugs are qualified, because
# their bare labels ("GDS", "LCC") are meaningless out of their nav category.
_LABEL_OVERRIDES = {"tp-gds": "Third Party GDS", "tp-lcc": "Third Party LCC"}

USAGE_SOURCES += [
    UsageSource(
        f"stmt_{slug}",
        _LABEL_OVERRIDES.get(slug) or STATEMENT_SPECS.get(slug, {}).get("label") or slug,
        model,
    )
    for slug, model in STATEMENT_MODELS.items()
]

USAGE_SOURCES += [
    UsageSource("income_summaries",   "Income Summaries",   IncomeSummary),
    UsageSource("billings",           "Billings",           Billing),
    UsageSource("series_contracts",   "Series Contracts",   SeriesContract),
    UsageSource("ticket_adjustments", "Ticket Adjustments", TicketAdjustment),
]

SOURCE_LABELS: dict[str, str] = {s.key: s.label for s in USAGE_SOURCES}

# Tenant-scoped tables that are deliberately NOT counted. Every entry is
# justified in the module docstring; the coverage test reads this set, so adding
# a table here is a decision on the record rather than a silent omission.
EXCLUDED_TABLES: frozenset[str] = frozenset({
    # child rows of a counted record
    "deal_incentives", "deal_incentive_slabs", "deal_incentive_slab_values",
    "deal_rules", "deal_rule_conditions", "bsp_tax_breakups",
    "customer_statement_tickets", "approval_workflow_steps",
    "approval_workflow_step_approvers", "deal_approvals", "deal_approval_steps",
    "user_entity_access",
    # upload-session parents whose rows are counted instead
    "bsp_statements", "bsp_summary_statements", "deal_statements", "deal_batches",
    "lcc_detailed_batch",
    # derived caches, not user data
    "ticket_calculations", "ticket_reconciliation",
    # config / master data owned by the workspace
    "users", "customers", "corporates", "entities", "user_entities",
    "user_login_ids", "login_ids", "agencies", "agency_entities",
    "agency_login_ids", "agency_terms", "iata_commissions", "approval_workflows",
    # the tenant's own subset of the platform airline master, with its ids —
    # master data, like login_ids next to it, not a unit of usage
    "tenant_airlines",
    # the agency's running account. Its `invoice` entries are posted
    # automatically whenever a billing is created, and `billings` is already
    # counted — counting both would report a workspace's agency invoices twice.
    "agency_ledger",
    "airline_approvals", "airport_approvals", "class_approvals",
    "supplier_approvals",
    # no tenant_id: records parse failures, reachable only via bsp_statements
    "bsp_parse_errors",
    # the tenant row itself
    "tenants",
})


async def usage_counts(
    db: AsyncSession, tenant_ids: list[int]
) -> dict[int, dict[str, int]]:
    """``{tenant_id: {source_key: rows}}`` for every counted table — ONE round trip.

    Twenty-plus sequential ``await db.execute(...)`` calls would be twenty-plus
    round trips on every page load, and an AsyncSession cannot run them
    concurrently, so they would serialise. A single UNION ALL keeps this at the
    constant cost the old two-column version had.

    Zero-count entries are omitted: GROUP BY emits no row for a tenant with no
    data, and the caller wants a breakdown of what exists, not a wall of zeros.
    """
    if not tenant_ids:
        return {}

    parts = [
        select(
            # Typed literal, not a bare one: an untyped parameter repeated across
            # a UNION makes Postgres give up on inferring its type.
            literal(src.key, String).label("src"),
            src.model.tenant_id.label("tenant_id"),
            func.count().label("n"),
        )
        .where(src.model.tenant_id.in_(tenant_ids))
        .group_by(src.model.tenant_id)
        for src in USAGE_SOURCES
    ]

    rows = (await db.execute(union_all(*parts))).all()

    out: dict[int, dict[str, int]] = {tid: {} for tid in tenant_ids}
    for key, tenant_id, n in rows:
        if n:
            out.setdefault(tenant_id, {})[key] = n
    return out


def to_breakdown(counts: dict[str, int]) -> dict[str, int]:
    """Machine keys -> the labels the console shows, in USAGE_SOURCES order."""
    return {
        SOURCE_LABELS[s.key]: counts[s.key]
        for s in USAGE_SOURCES
        if counts.get(s.key)
    }
