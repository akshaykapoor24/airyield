"""Deleting a workspace's data, in whole or in part, from the platform-admin console.

The console at ``/admin/subscriptions`` can already freeze a workspace. This is
the other half: removing what it holds, down to the individual kind of record.

THE UNIT OF CHOICE IS A GROUP
    The operator ticks "Deals" or "BSP statements", not ``deal_incentive_slabs``.
    A group is one thing a person would think of deleting, and it owns every
    table that only exists to serve it — a deal's incentives, slabs, rules and
    approval trail go when the deal does, because keeping them would leave rows
    that describe nothing.

SOME TICKS FORCE OTHERS, AND THAT IS NOT A UI DETAIL
    ``deals.agency_id`` is ON DELETE RESTRICT, so deleting Agencies while
    keeping Deals is not a choice the database will honour — it aborts. And
    ``billings.agency_id`` is ON DELETE CASCADE, so that same delete would take
    the billings with it whether or not the operator ticked them.

    Both cases are the same problem: a selection that does not say what will
    actually happen. GROUP_REQUIREMENTS is therefore derived from the foreign
    keys themselves rather than hand-written — any FK into a group that is not
    ON DELETE SET NULL pulls the referencing group in, whether it would block
    the delete or silently widen it. The API expands the selection before it
    counts anything, so the preview the operator confirms against already
    includes everything their tick implies.

WHY THIS DOES NOT SIMPLY ``DELETE FROM tenants``
    13 of the 49 tenant-scoped tables declare ``ondelete="SET NULL"`` — users,
    agencies, agency_terms, agency_ledger and every ``*_approvals`` table among
    them. Deleting the tenant row and trusting the database would leave those
    behind with a NULL tenant_id: accounts that no longer belong anywhere but
    still hold their email against the unique index, so the owner could never
    sign up again. Every table is emptied explicitly instead.

ORDER
    ``Base.metadata.sorted_tables`` is dependency-ordered, parents first; this
    walks it in reverse, so a child is always gone before the row it points at.
    No foreign key can fire mid-delete whatever the database's ON DELETE says.

COVERAGE
    ``tests/test_tenant_deletion.py`` fails if a table appears that no group
    claims, if a table with no tenant_id has no route back to one, or if any
    foreign key outside the delete set could block it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import String, delete, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base


class GroupCategory(str, Enum):
    """Which of the two lists a group appears under in the dialog."""
    RECORDS = "records"   # produced by using the product
    SETUP = "setup"       # who the workspace is and how it is configured


@dataclass(frozen=True)
class DeletionGroup:
    key: str
    label: str
    blurb: str
    category: GroupCategory
    # Every table this group owns. The first is the one a person would name;
    # the rest are its upload sessions, caches and child rows.
    tables: tuple[str, ...]
    # Groups this one cannot be deleted without. Derived from the schema below
    # except where noted on the group itself.
    extra_requires: tuple[str, ...] = field(default=())


DELETION_GROUPS: tuple[DeletionGroup, ...] = (
    # ── records ──────────────────────────────────────────────────────────────
    DeletionGroup(
        "deals", "Deals", "Deal sheets with their incentives, slabs, rules and approval trail.",
        GroupCategory.RECORDS,
        ("deals", "deal_statements", "deal_batches", "deal_incentives",
         "deal_incentive_slabs", "deal_incentive_slab_values", "deal_rules",
         "deal_rule_conditions", "deal_approvals", "deal_approval_steps"),
    ),
    DeletionGroup(
        "tickets", "Tickets", "Uploaded tickets, their calculation runs and reconciliation cache.",
        GroupCategory.RECORDS,
        ("uploaded_tickets", "ticket_calculations", "ticket_reconciliation", "ticket_adjustments"),
    ),
    DeletionGroup(
        "bsp", "BSP statements", "BSP settlement and summary uploads with every row and tax breakup.",
        GroupCategory.RECORDS,
        ("bsp_statements", "bsp_statement_rows", "bsp_tax_breakups", "bsp_parse_errors",
         "bsp_summary_statements", "bsp_summary_rows"),
    ),
    DeletionGroup(
        "adjustments", "ADM / ACM / RA", "Airline debit, credit and refund application notes.",
        GroupCategory.RECORDS,
        ("airline_adm", "airline_acm", "airline_ra"),
    ),
    DeletionGroup(
        "vendor_statements", "Vendor statements",
        "TGQ HMPR, NDC, DI, Divided PNR, Flown Report, CTA/BTA, third-party GDS/LCC and Detailed.",
        GroupCategory.RECORDS,
        ("tgq_hmpr", "ndc", "lcc_di", "lcc_divided_pnr", "lcc_flown_report",
         "lcc_cta_bta", "third_party_gds", "third_party_lcc",
         "lcc_detailed", "lcc_detailed_batch", "lcc_batch_airline_ids",
         "statement_batch_airline_ids"),
    ),
    DeletionGroup(
        "internal_statements", "Internal statements", "The workspace's own ticket statements.",
        GroupCategory.RECORDS, ("ticket_statements",),
    ),
    DeletionGroup(
        "customer_statements", "Customer statements", "Statements issued to customers.",
        GroupCategory.RECORDS, ("customer_statements", "customer_statement_tickets"),
    ),
    DeletionGroup(
        "income", "Income summaries", "Saved income summary runs.",
        GroupCategory.RECORDS, ("income_summaries",),
    ),
    DeletionGroup(
        "billing", "Billings", "Invoices raised to customers, agencies and corporates.",
        GroupCategory.RECORDS, ("billings",),
    ),
    DeletionGroup(
        "series", "Series / SIT / MICE", "Series contracts.",
        GroupCategory.RECORDS, ("series_contracts",),
    ),
    DeletionGroup(
        "legacy", "Legacy records",
        "Rows in the three pre-tenant tables. Nothing in the product writes these any more.",
        GroupCategory.RECORDS, ("tickets", "income_records", "documents"),
    ),

    # ── setup ────────────────────────────────────────────────────────────────
    DeletionGroup(
        "customers", "Customers", "The customer master this workspace maintains.",
        GroupCategory.SETUP, ("customers",),
    ),
    DeletionGroup(
        "corporates", "Corporates", "The corporate master this workspace maintains.",
        GroupCategory.SETUP, ("corporates",),
    ),
    DeletionGroup(
        "agencies", "Agencies", "Onboarded agencies with their entities, login IDs, terms and ledger.",
        GroupCategory.SETUP,
        ("agencies", "agency_entities", "agency_login_ids", "agency_terms", "agency_ledger"),
    ),
    DeletionGroup(
        "entities", "Entities & login IDs",
        "Company entities, airline login IDs, the airlines this workspace registered, "
        "and per-user access grants.",
        GroupCategory.SETUP,
        ("entities", "login_ids", "tenant_airlines", "user_entities", "user_login_ids",
         "user_entity_access"),
    ),
    DeletionGroup(
        "iata_commissions", "IATA commissions",
        "Rows this workspace created before IATA Commission became a global master. "
        "The global master is untouched.",
        GroupCategory.SETUP, ("iata_commissions",),
    ),
    DeletionGroup(
        "workflows", "Approval workflows", "Approval workflow definitions, their steps and approvers.",
        GroupCategory.SETUP,
        ("approval_workflows", "approval_workflow_steps", "approval_workflow_step_approvers"),
    ),
    DeletionGroup(
        "master_requests", "Pending master requests",
        "Airline, airport, class and supplier changes this workspace submitted and nobody has actioned.",
        GroupCategory.SETUP,
        ("airline_approvals", "airport_approvals", "class_approvals", "supplier_approvals"),
    ),
    DeletionGroup(
        "users", "User accounts",
        "Every member of the workspace. Frees their email addresses to sign up again.",
        GroupCategory.SETUP, ("users",),
    ),
    DeletionGroup(
        "workspace", "The workspace itself",
        "The workspace row. Removing it takes everything else with it.",
        GroupCategory.SETUP, ("tenants",),
        # tenant_id is ON DELETE CASCADE on 36 tables and SET NULL on 13, so
        # dropping this row alone would silently delete most of the workspace
        # and orphan the rest. It only ever means "all of it".
        extra_requires=("__all__",),
    ),
)

GROUPS_BY_KEY: dict[str, DeletionGroup] = {g.key: g for g in DELETION_GROUPS}
ALL_GROUP_KEYS: tuple[str, ...] = tuple(g.key for g in DELETION_GROUPS)
_OWNER: dict[str, str] = {t: g.key for g in DELETION_GROUPS for t in g.tables}


# ── tables with no tenant_id, reached through one that has ───────────────────

@dataclass(frozen=True)
class ParentLink:
    """``child.fk_column`` points at ``parent_table.parent_column``."""
    fk_column: str
    parent_table: str
    parent_column: str = "id"


@dataclass(frozen=True)
class ChildTable:
    """A table with no tenant_id of its own.

    ``links`` are OR-ed: a row goes if ANY of its parents belongs to the
    workspace. All but the legacy tables have exactly one link; those three
    hang off users by several columns at once and would otherwise survive to
    block the users delete.
    """
    links: tuple[ParentLink, ...]


CHILD_TABLES: dict[str, ChildTable] = {
    # deal tree: deals -> incentives -> slabs -> values, and -> rules -> conditions
    "deal_incentives": ChildTable((ParentLink("deal_id", "deals"),)),
    "deal_incentive_slabs": ChildTable((ParentLink("incentive_id", "deal_incentives"),)),
    "deal_incentive_slab_values": ChildTable((ParentLink("slab_id", "deal_incentive_slabs"),)),
    "deal_rules": ChildTable((ParentLink("incentive_id", "deal_incentives"),)),
    "deal_rule_conditions": ChildTable((ParentLink("rule_id", "deal_rules"),)),
    "deal_approvals": ChildTable((ParentLink("unified_deal_id", "deals"),)),
    "deal_approval_steps": ChildTable((ParentLink("deal_approval_id", "deal_approvals"),)),
    # BSP parse failures hang off the upload session by its batch_id, not its pk
    "bsp_parse_errors": ChildTable((ParentLink("statement_id", "bsp_statements", "batch_id"),)),
    # Which airline ids an LCC upload covers. Reached through the batch, not through
    # tenant_airlines: the batch is what belongs to the workspace's statement data,
    # and linking it the other way would tie this table to the Setup groups.
    "lcc_batch_airline_ids": ChildTable(
        (ParentLink("batch_id", "lcc_detailed_batch", "batch_id"),)),
    "approval_workflow_steps": ChildTable((ParentLink("workflow_id", "approval_workflows"),)),
    "approval_workflow_step_approvers": ChildTable(
        (ParentLink("workflow_step_id", "approval_workflow_steps"),)),
    "user_entity_access": ChildTable((ParentLink("user_id", "users"),)),
    # Dead pre-tenant tables. They carry no tenant_id and their FKs to users
    # declare no ON DELETE, so any surviving row would abort the users delete
    # with a foreign-key violation. Cleared by the user who owns them.
    "income_records": ChildTable((ParentLink("ticket_id", "tickets"),
                                  ParentLink("override_by_id", "users"),
                                  ParentLink("approved_by_id", "users"))),
    "tickets": ChildTable((ParentLink("created_by_id", "users"),)),
    "documents": ChildTable((ParentLink("uploaded_by_id", "users"),)),
}


# ── which ticks force which ──────────────────────────────────────────────────

def _derive_requirements() -> dict[str, frozenset[str]]:
    """``{group: groups that must go with it}``, read off the foreign keys.

    A row pointing at something being deleted has exactly three fates, and only
    one of them is safe to leave alone:

        SET NULL   the row survives, detached. Fine — not pulled in.
        RESTRICT   the database refuses the delete. Must be pulled in.
        CASCADE    the database deletes it too, ticked or not. Must be pulled
                   in, or the preview would understate what happens.

    Hand-listing this would rot the first time someone adds a column. Reading
    it from the schema cannot.
    """
    out: dict[str, set[str]] = {g.key: set() for g in DELETION_GROUPS}
    for table_name, owner in _OWNER.items():
        for col in Base.metadata.tables[table_name].c:
            for fk in col.foreign_keys:
                target = fk.column.table.name
                target_owner = _OWNER.get(target)
                if target_owner is None or target_owner == owner:
                    continue
                if fk.ondelete == "SET NULL":
                    continue
                out[target_owner].add(owner)

    for group in DELETION_GROUPS:
        for extra in group.extra_requires:
            if extra == "__all__":
                out[group.key] |= {k for k in ALL_GROUP_KEYS if k != group.key}
            else:
                out[group.key].add(extra)

    return {k: frozenset(v) for k, v in out.items()}


GROUP_REQUIREMENTS: dict[str, frozenset[str]] = _derive_requirements()


def expand_groups(selected: set[str] | list[str]) -> set[str]:
    """Close a selection over GROUP_REQUIREMENTS.

    Ticking Agencies also deletes Deals (RESTRICT) and Billings (CASCADE);
    ticking User accounts deletes everything they created. The caller counts
    and deletes the expanded set, so what is previewed is what happens.
    """
    out = set(selected)
    while True:
        grown = set(out)
        for key in out:
            grown |= GROUP_REQUIREMENTS.get(key, frozenset())
        if grown == out:
            return out
        out = grown


def validate_groups(selected: list[str]) -> set[str]:
    """Reject unknown keys loudly rather than silently deleting a smaller set."""
    unknown = sorted(set(selected) - set(GROUPS_BY_KEY))
    if unknown:
        raise ValueError(
            f"Unknown group(s): {', '.join(unknown)}. "
            f"Valid groups: {', '.join(ALL_GROUP_KEYS)}"
        )
    if not selected:
        raise ValueError("Select at least one thing to delete.")
    return expand_groups(selected)


def tables_for_groups(keys: set[str] | list[str]) -> list[str]:
    """Tables these groups own, children before parents.

    sorted_tables is parents-first; reversing it means every row is gone before
    the row it references, so no foreign key can fire part-way through.
    """
    wanted = {t for k in keys for t in GROUPS_BY_KEY[k].tables}
    return [t.name for t in reversed(Base.metadata.sorted_tables) if t.name in wanted]


# ── what the console shows ───────────────────────────────────────────────────

def tenant_predicate(table_name: str, tenant_id: int):
    """A WHERE clause selecting exactly this workspace's rows in one table.

    Recurses through CHILD_TABLES for the tables that have no tenant_id, so a
    deal_incentive_slab_value is matched via its slab, its incentive and its
    deal. Children are always deleted before their parents, so the parent rows
    the subquery reads are still there when it runs.
    """
    table = Base.metadata.tables[table_name]
    if "tenant_id" in table.c:
        return table.c.tenant_id == tenant_id

    child = CHILD_TABLES[table_name]
    clauses = []
    for link in child.links:
        parent = Base.metadata.tables[link.parent_table]
        clauses.append(
            table.c[link.fk_column].in_(
                select(parent.c[link.parent_column])
                .where(tenant_predicate(link.parent_table, tenant_id))
            )
        )
    return or_(*clauses) if len(clauses) > 1 else clauses[0]


async def group_counts(db: AsyncSession, tenant_id: int) -> dict[str, int]:
    """``{group_key: rows}`` for every group — ONE round trip.

    The tenant row is excluded from its group's count: "the workspace itself"
    is not a record, and adding 1 to the headline would misreport what the
    workspace loses.
    """
    names = [t for t in tables_for_groups(ALL_GROUP_KEYS) if t != "tenants"]
    parts = [
        select(
            # Typed literal: an untyped parameter repeated across a UNION makes
            # Postgres give up on inferring its type (same as usage_counts).
            literal(name, String).label("tbl"),
            func.count().label("n"),
        )
        .select_from(Base.metadata.tables[name])
        .where(tenant_predicate(name, tenant_id))
        for name in names
    ]
    rows = (await db.execute(union_all(*parts))).all()

    out: dict[str, int] = {g.key: 0 for g in DELETION_GROUPS}
    for table_name, n in rows:
        out[_OWNER[table_name]] += n
    return out


async def delete_groups(
    db: AsyncSession, tenant_id: int, keys: set[str]
) -> dict[str, int]:
    """Empty every table the given groups own. Returns ``{group_key: rows}``.

    One transaction: a delete that stopped half way would leave the workspace in
    a state no screen can describe, so either all of it goes or none does.
    """
    deleted: dict[str, int] = {}
    for name in tables_for_groups(keys):
        if name == "tenants":
            continue
        result = await db.execute(
            delete(Base.metadata.tables[name]).where(tenant_predicate(name, tenant_id))
        )
        if result.rowcount:
            deleted[_OWNER[name]] = deleted.get(_OWNER[name], 0) + result.rowcount

    # Last, and only once everything pointing at it is gone.
    if "workspace" in keys:
        tenants = Base.metadata.tables["tenants"]
        await db.execute(delete(tenants).where(tenants.c.id == tenant_id))
        deleted["workspace"] = 1

    await db.commit()
    return deleted
