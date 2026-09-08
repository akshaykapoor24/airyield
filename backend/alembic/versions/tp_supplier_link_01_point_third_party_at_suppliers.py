"""A third-party statement, and the B2B deal that prices it, name a SUPPLIER — not an agency.

Both sides of the B2B match now key off the platform-admin `suppliers` master, which is
where `deals.supplier_name` has always come from (the B2B deal form reads `/suppliers/`).
Before this they did not: the statement was attributed to a row in `agencies` and the deal
named a supplier, so the two could only ever be compared by NAME.

WHY AGENCIES WERE THE WRONG TARGET. `agencies` is a tenant's own onboarding of a vendor and
is SPLIT BY CHANNEL — one supplier becomes two agency rows, GDS and LCC, with the same
name (see models/agency.py). Attributing a statement to one of those attributed it to half
a relationship, and it could not line up with a deal at all. `suppliers` has one row per
branch with a unique `code`, so one id is one counterparty and there is nothing to
disambiguate.

`supplier_name` STAYS on `deals` and is still what an unlinked deal matches on — 141 of the
master's 2,340 names repeat across branches, which is exactly the ambiguity the id removes,
but a deal written before the id existed must keep working.

MIGRATED, NOT DROPPED. `agencies.supplier_id` records which supplier master row an agency
was copied from, so an existing attribution maps straight through. An agency that was typed
in by hand rather than picked from the master has no `supplier_id`; those rows cannot be
mapped and are reported rather than guessed at.

Revision ID: tp_supplier_link_01
Revises: commission_ledger_01
"""
import logging

from alembic import op
import sqlalchemy as sa


revision = "tp_supplier_link_01"
down_revision = "commission_ledger_01"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. The batch → counterparty link ────────────────────────────────────
    op.create_table(
        "statement_batch_suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        # RESTRICT: `suppliers` is global master data with no delete endpoint, so this is a
        # backstop against direct SQL rather than a workflow.
        sa.Column("supplier_id", sa.Integer(),
                  sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("supplier_code", sa.String(length=50), nullable=True),
        sa.Column("supplier_branch", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("slug", "batch_id", name="uq_statement_batch_suppliers_batch"),
    )
    op.create_index("ix_statement_batch_suppliers_tenant_id", "statement_batch_suppliers", ["tenant_id"])
    op.create_index("ix_statement_batch_suppliers_supplier_id", "statement_batch_suppliers", ["supplier_id"])
    op.create_index("ix_statement_batch_suppliers_batch", "statement_batch_suppliers", ["slug", "batch_id"])

    moved = bind.execute(sa.text("""
        INSERT INTO statement_batch_suppliers
              (tenant_id, slug, batch_id, supplier_id, supplier_name, supplier_code, supplier_branch)
        SELECT l.tenant_id, l.slug, l.batch_id, a.supplier_id, s.name, s.code,
               COALESCE(s.branch, s.city)
          FROM statement_batch_agencies l
          JOIN agencies  a ON a.id = l.agency_id
          JOIN suppliers s ON s.id = a.supplier_id
    """)).rowcount
    orphan = bind.execute(sa.text("""
        SELECT COUNT(*) FROM statement_batch_agencies l
          JOIN agencies a ON a.id = l.agency_id
         WHERE a.supplier_id IS NULL
    """)).scalar() or 0
    logger.info(
        "tp_supplier_link_01: %s statement attribution(s) re-pointed at the supplier master; "
        "%s could not be mapped because their agency was typed in by hand rather than picked "
        "from it — those uploads read as un-attributed and must be re-uploaded to be priced.",
        moved, orphan,
    )

    op.drop_index("ix_statement_batch_agencies_batch", table_name="statement_batch_agencies")
    op.drop_index("ix_statement_batch_agencies_agency_id", table_name="statement_batch_agencies")
    op.drop_index("ix_statement_batch_agencies_tenant_id", table_name="statement_batch_agencies")
    op.drop_table("statement_batch_agencies")

    # ── 2. The deal's own counterparty id ───────────────────────────────────
    op.drop_constraint("ck_deals_supplier_agency", "deals", type_="check")
    op.drop_constraint("fk_deals_supplier_agency_id", "deals", type_="foreignkey")
    op.drop_index("ix_deals_supplier_agency_id", table_name="deals")
    op.alter_column("deals", "supplier_agency_id", new_column_name="supplier_id")

    # Carry an existing link across the same way, then clear anything that could not be
    # mapped — an id that used to mean `agencies.id` would silently mean a DIFFERENT
    # supplier if it were left in place.
    op.execute(sa.text("""
        UPDATE deals d SET supplier_id = a.supplier_id
          FROM agencies a
         WHERE a.id = d.supplier_id AND a.supplier_id IS NOT NULL
    """))
    op.execute(sa.text("""
        UPDATE deals d SET supplier_id = NULL
         WHERE d.supplier_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM suppliers s WHERE s.id = d.supplier_id)
    """))

    op.create_foreign_key("fk_deals_supplier_id", "deals", "suppliers",
                          ["supplier_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_deals_supplier_id", "deals", ["supplier_id"])
    op.create_check_constraint(
        "ck_deals_supplier", "deals",
        "supplier_id IS NULL OR (deal_type = 'b2b' AND direction = 'inbound')",
    )

    # Link every inbound B2B deal whose supplier name matches EXACTLY ONE master row.
    # Zero matches (never onboarded) and two or more (a multi-branch vendor — the very
    # ambiguity this column removes) are both left NULL and keep matching by name.
    counts = bind.execute(sa.text("""
        SELECT CASE WHEN n = 1 THEN 'one' WHEN n = 0 THEN 'none' ELSE 'many' END AS bucket,
               COUNT(*) AS deals
        FROM (
            SELECT d.id,
                   (SELECT COUNT(*) FROM suppliers s
                     WHERE lower(trim(s.name)) = lower(trim(d.supplier_name))) AS n
            FROM deals d
            WHERE d.direction = 'inbound' AND d.deal_type = 'b2b'
              AND d.supplier_id IS NULL
              AND d.supplier_name IS NOT NULL AND trim(d.supplier_name) <> ''
        ) t GROUP BY 1
    """)).mappings().all()
    summary = {r["bucket"]: r["deals"] for r in counts}

    op.execute(sa.text("""
        UPDATE deals d
           SET supplier_id = (SELECT s.id FROM suppliers s
                               WHERE lower(trim(s.name)) = lower(trim(d.supplier_name)))
         WHERE d.direction = 'inbound' AND d.deal_type = 'b2b'
           AND d.supplier_id IS NULL
           AND d.supplier_name IS NOT NULL AND trim(d.supplier_name) <> ''
           AND (SELECT COUNT(*) FROM suppliers s
                 WHERE lower(trim(s.name)) = lower(trim(d.supplier_name))) = 1
    """))
    logger.info(
        "tp_supplier_link_01 deal backfill: %s linked, %s name not in the supplier master, "
        "%s ambiguous across branches and left unlinked — those keep matching by supplier "
        "NAME until a branch is picked on the deal.",
        summary.get("one", 0), summary.get("none", 0), summary.get("many", 0),
    )


def downgrade() -> None:
    op.drop_constraint("ck_deals_supplier", "deals", type_="check")
    op.drop_index("ix_deals_supplier_id", table_name="deals")
    op.drop_constraint("fk_deals_supplier_id", "deals", type_="foreignkey")
    op.alter_column("deals", "supplier_id", new_column_name="supplier_agency_id")
    # The ids meant suppliers, not agencies; carrying them back would be worse than
    # dropping them, so the column returns empty.
    op.execute(sa.text("UPDATE deals SET supplier_agency_id = NULL"))
    op.create_foreign_key("fk_deals_supplier_agency_id", "deals", "agencies",
                          ["supplier_agency_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_deals_supplier_agency_id", "deals", ["supplier_agency_id"])
    op.create_check_constraint(
        "ck_deals_supplier_agency", "deals",
        "supplier_agency_id IS NULL OR (deal_type = 'b2b' AND direction = 'inbound')",
    )

    op.create_table(
        "statement_batch_agencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        sa.Column("agency_id", sa.Integer(),
                  sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agency_name", sa.String(length=255), nullable=True),
        sa.Column("agency_channel", sa.String(length=10), nullable=True),
        sa.Column("agency_branch", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("slug", "batch_id", name="uq_statement_batch_agencies_batch"),
    )
    op.create_index("ix_statement_batch_agencies_tenant_id", "statement_batch_agencies", ["tenant_id"])
    op.create_index("ix_statement_batch_agencies_agency_id", "statement_batch_agencies", ["agency_id"])
    op.create_index("ix_statement_batch_agencies_batch", "statement_batch_agencies", ["slug", "batch_id"])

    op.drop_index("ix_statement_batch_suppliers_batch", table_name="statement_batch_suppliers")
    op.drop_index("ix_statement_batch_suppliers_supplier_id", table_name="statement_batch_suppliers")
    op.drop_index("ix_statement_batch_suppliers_tenant_id", table_name="statement_batch_suppliers")
    op.drop_table("statement_batch_suppliers")
