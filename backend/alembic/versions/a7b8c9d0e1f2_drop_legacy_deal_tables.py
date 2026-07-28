"""drop legacy deal tables

Removes the five empty legacy deal tables that have been fully superseded by the
unified deal schema (deal_statements → deals → deal_incentives → …):
    - legacy_deals            (old UploadedDeal)
    - legacy_deal_incentives  (child of legacy_deals)
    - deal_incl_excl_rules    (child of legacy_deals)
    - airline_deals           (old polymorphic AirlineDeal)
    - b2b_deals               (old polymorphic B2BDeal)

Steps:
  1. Drop the three external FK constraints that point at legacy_deals from tables
     we KEEP (documents, income_records, tickets — all empty). Their id columns are
     retained as plain integers (no FK) for backwards compatibility of those models.
  2. Delete orphaned non-unified DealApproval rows (deal_type != 'unified') and their
     steps — they reference now-removed legacy deals, so the approval code only ever
     handles unified deals after this.
  3. Drop the five tables, children first.

All five tables and every dependent legacy table are empty, so no live data is lost.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop external FK constraints pointing at legacy_deals (kept tables → dropped table)
    op.drop_constraint('fk_documents_deal', 'documents', type_='foreignkey')
    op.drop_constraint('fk_income_records_deal', 'income_records', type_='foreignkey')
    op.drop_constraint('fk_tickets_matched_deal', 'tickets', type_='foreignkey')

    # 2. Remove orphaned legacy approvals (they referenced airline_deals/b2b_deals/legacy_deals)
    op.execute(
        "DELETE FROM deal_approval_steps WHERE deal_approval_id IN "
        "(SELECT id FROM deal_approvals WHERE deal_type <> 'unified')"
    )
    op.execute("DELETE FROM deal_approvals WHERE deal_type <> 'unified'")

    # 3. Drop the five legacy tables, children before parents
    op.drop_table('legacy_deal_incentives')
    op.drop_table('deal_incl_excl_rules')
    op.drop_table('legacy_deals')
    op.drop_table('airline_deals')
    op.drop_table('b2b_deals')


def downgrade() -> None:
    # Irreversible: the five tables were empty legacy artifacts and their ORM models
    # have been removed, so they are intentionally not recreated. The FK columns on
    # documents/income_records/tickets remain as plain integers.
    pass
