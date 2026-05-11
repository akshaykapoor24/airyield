"""cleanup legacy deals tables and repoint foreign keys

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove old foreign keys pointing at legacy deals table.
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_matched_deal_id_fkey")
    op.execute("ALTER TABLE income_records DROP CONSTRAINT IF EXISTS income_records_deal_id_fkey")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_deal_id_fkey")

    # Repoint linking columns to uploaded_deals.
    # NOT VALID prevents migration failure on legacy rows; new writes still enforce FK.
    op.execute(
        """
        ALTER TABLE tickets
        ADD CONSTRAINT fk_tickets_matched_uploaded_deal
        FOREIGN KEY (matched_deal_id) REFERENCES uploaded_deals(id)
        ON DELETE SET NULL
        NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE income_records
        ADD CONSTRAINT fk_income_records_uploaded_deal
        FOREIGN KEY (deal_id) REFERENCES uploaded_deals(id)
        NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE documents
        ADD CONSTRAINT fk_documents_uploaded_deal
        FOREIGN KEY (deal_id) REFERENCES uploaded_deals(id)
        ON DELETE SET NULL
        NOT VALID
        """
    )

    # Drop legacy tables no longer used by current manual/upload workflow.
    op.execute("DROP TABLE IF EXISTS deal_class_commercials")
    op.execute("DROP TABLE IF EXISTS deal_versions")
    op.execute("DROP TABLE IF EXISTS deals")


def downgrade() -> None:
    # Best-effort rollback for foreign keys only; legacy deal tables are not recreated here.
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS fk_tickets_matched_uploaded_deal")
    op.execute("ALTER TABLE income_records DROP CONSTRAINT IF EXISTS fk_income_records_uploaded_deal")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS fk_documents_uploaded_deal")
