"""An incoming B2B deal names WHICH BRANCH ON WHICH CHANNEL it was signed with.

Until now the counterparty of an inbound B2B deal was `deals.supplier_name`, a free-text
copy of a supplier-master name, and `services/deal_matching.py` matched it with a
case-insensitive compare. `agencies.name` is a verbatim copy of that same master name, and
a vendor working both channels is onboarded TWICE under it (models/agency.py) — so the
name cannot tell the GDS relationship from the LCC one. With third-party statements now
attributed to a specific agency row at upload, that ambiguity would decide which deal
prices the statement. The id removes it.

NOT `deals.agency_id`: that column is pinned to `scope_type='agency'` by
ck_deals_scope_agency, and api/v1/deals.py::_resolve_scope forces every inbound deal to
scope_type=ALL, so an inbound deal cannot legally carry it. It also means the opposite
thing — "we sell TO them" rather than "we buy FROM them".

BACKFILL — deliberately conservative. A deal is linked only when EXACTLY ONE of its
creator's agencies bears its supplier name. Zero matches (the supplier was never
onboarded) and two or more (the vendor works both channels, which is the very ambiguity
this column exists to end) are both left NULL, and the matcher falls back to the old name
compare for them. Guessing on the two-or-more case would silently pick a channel.

Revision ID: deal_supplier_agency_01
Revises: stmt_batch_agency_01
"""
import logging

from alembic import op
import sqlalchemy as sa


revision = "deal_supplier_agency_01"
down_revision = "stmt_batch_agency_01"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.add_column("deals", sa.Column("supplier_agency_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_deals_supplier_agency_id", "deals", "agencies",
        ["supplier_agency_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_deals_supplier_agency_id", "deals", ["supplier_agency_id"])
    op.create_check_constraint(
        "ck_deals_supplier_agency", "deals",
        "supplier_agency_id IS NULL OR (deal_type = 'b2b' AND direction = 'inbound')",
    )

    bind = op.get_bind()

    # Candidate deals, and how many of the creator's agencies bear that supplier name.
    # Agencies are user-scoped (agencies.user_id), so the join is on the deal's CREATOR,
    # not on its tenant — a tenant-wide match could link a colleague's agency.
    counts = bind.execute(sa.text("""
        SELECT CASE WHEN n = 1 THEN 'one' WHEN n = 0 THEN 'none' ELSE 'many' END AS bucket,
               COUNT(*) AS deals
        FROM (
            SELECT d.id,
                   (SELECT COUNT(*) FROM agencies a
                     WHERE a.user_id = d.created_by_id
                       AND lower(trim(a.name)) = lower(trim(d.supplier_name))) AS n
            FROM deals d
            WHERE d.direction = 'inbound' AND d.deal_type = 'b2b'
              AND d.supplier_name IS NOT NULL AND trim(d.supplier_name) <> ''
        ) t
        GROUP BY 1
    """)).mappings().all()
    summary = {r["bucket"]: r["deals"] for r in counts}

    op.execute(sa.text("""
        UPDATE deals d
           SET supplier_agency_id = (
               SELECT a.id FROM agencies a
                WHERE a.user_id = d.created_by_id
                  AND lower(trim(a.name)) = lower(trim(d.supplier_name))
           )
         WHERE d.direction = 'inbound'
           AND d.deal_type = 'b2b'
           AND d.supplier_agency_id IS NULL
           AND d.supplier_name IS NOT NULL
           AND trim(d.supplier_name) <> ''
           AND (SELECT COUNT(*) FROM agencies a
                 WHERE a.user_id = d.created_by_id
                   AND lower(trim(a.name)) = lower(trim(d.supplier_name))) = 1
    """))

    logger.info(
        "deal_supplier_agency_01 backfill: %s linked, %s had no onboarded agency, "
        "%s were ambiguous (vendor onboarded more than once) and were left unlinked — "
        "those keep matching by supplier NAME until a branch is picked on the deal.",
        summary.get("one", 0), summary.get("none", 0), summary.get("many", 0),
    )


def downgrade() -> None:
    op.drop_constraint("ck_deals_supplier_agency", "deals", type_="check")
    op.drop_index("ix_deals_supplier_agency_id", table_name="deals")
    op.drop_constraint("fk_deals_supplier_agency_id", "deals", type_="foreignkey")
    op.drop_column("deals", "supplier_agency_id")
