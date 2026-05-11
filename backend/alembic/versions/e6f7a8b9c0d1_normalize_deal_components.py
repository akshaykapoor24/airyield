"""normalize deal row data into deal_components table

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deal_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("row_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("airline_name", sa.String(length=255), nullable=True),
        sa.Column("iata_code", sa.String(length=50), nullable=True),
        sa.Column("variant", sa.String(length=100), nullable=True),
        sa.Column("eco_commission", sa.String(length=50), nullable=True),
        sa.Column("peco_commission", sa.String(length=50), nullable=True),
        sa.Column("bus_commission", sa.String(length=50), nullable=True),
        sa.Column("base_type", sa.String(length=20), nullable=True),
        sa.Column("valid_on", sa.String(length=20), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("validity_raw", sa.String(length=255), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        """
        INSERT INTO deal_components (
            deal_id, row_order, airline_name, iata_code, variant, eco_commission,
            peco_commission, bus_commission, base_type, valid_on, valid_from, valid_to,
            validity_raw, remarks, is_confirmed
        )
        SELECT
            d.id,
            COALESCE((r.elem->>'row_order')::int, 0),
            NULLIF(r.elem->>'airline_name', ''),
            NULLIF(r.elem->>'iata_code', ''),
            NULLIF(r.elem->>'variant', ''),
            NULLIF(r.elem->>'eco_commission', ''),
            NULLIF(r.elem->>'peco_commission', ''),
            NULLIF(r.elem->>'bus_commission', ''),
            NULLIF(r.elem->>'base_type', ''),
            NULLIF(r.elem->>'valid_on', ''),
            NULLIF(r.elem->>'valid_from', '')::date,
            NULLIF(r.elem->>'valid_to', '')::date,
            NULLIF(r.elem->>'validity_raw', ''),
            NULLIF(r.elem->>'remarks', ''),
            true
        FROM deals d
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(d.rows_data, '[]'::jsonb)) AS r(elem)
        """
    )

    op.execute("ALTER TABLE deals DROP COLUMN IF EXISTS rows_data")


def downgrade() -> None:
    op.add_column("deals", sa.Column("rows_data", sa.JSON(), nullable=True))
    op.drop_table("deal_components")
