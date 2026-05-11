"""rename uploaded_deals to deals and remove row/draft tables

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure denormalized row storage exists before dropping deal_rows.
    op.execute("ALTER TABLE uploaded_deals ADD COLUMN IF NOT EXISTS rows_data JSONB")

    op.execute(
        """
        UPDATE uploaded_deals d
        SET rows_data = src.rows_json
        FROM (
            SELECT
                uploaded_deal_id,
                jsonb_agg(
                    jsonb_build_object(
                        'row_order', row_order,
                        'airline_name', airline_name,
                        'iata_code', iata_code,
                        'variant', variant,
                        'eco_commission', eco_commission,
                        'peco_commission', peco_commission,
                        'bus_commission', bus_commission,
                        'base_type', base_type,
                        'valid_on', valid_on,
                        'valid_from', valid_from,
                        'valid_to', valid_to,
                        'validity_raw', validity_raw,
                        'remarks', remarks
                    )
                    ORDER BY row_order
                ) AS rows_json
            FROM deal_rows
            GROUP BY uploaded_deal_id
        ) src
        WHERE d.id = src.uploaded_deal_id
          AND (d.rows_data IS NULL OR d.rows_data = '[]'::jsonb)
        """
    )

    # Drop existing constraints to uploaded_deals.
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS fk_tickets_matched_uploaded_deal")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_matched_deal_id_fkey")
    op.execute("ALTER TABLE income_records DROP CONSTRAINT IF EXISTS fk_income_records_uploaded_deal")
    op.execute("ALTER TABLE income_records DROP CONSTRAINT IF EXISTS income_records_deal_id_fkey")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS fk_documents_uploaded_deal")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_deal_id_fkey")

    # Remove obsolete tables.
    op.execute("DROP TABLE IF EXISTS deal_rows")
    op.execute("DROP TABLE IF EXISTS draft_deals")

    # Rename uploaded_deals table to deals.
    op.execute("ALTER TABLE uploaded_deals RENAME TO deals")

    # Recreate foreign keys pointing to deals.
    op.execute(
        """
        ALTER TABLE tickets
        ADD CONSTRAINT fk_tickets_matched_deal
        FOREIGN KEY (matched_deal_id) REFERENCES deals(id)
        ON DELETE SET NULL
        NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE income_records
        ADD CONSTRAINT fk_income_records_deal
        FOREIGN KEY (deal_id) REFERENCES deals(id)
        NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE documents
        ADD CONSTRAINT fk_documents_deal
        FOREIGN KEY (deal_id) REFERENCES deals(id)
        ON DELETE SET NULL
        NOT VALID
        """
    )


def downgrade() -> None:
    # Intentionally no destructive rollback for table rename/drop cleanup.
    pass
