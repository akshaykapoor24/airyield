"""split deals metadata tables and drop deal_components

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add row-mapped scalar columns to deals.
    op.add_column("deals", sa.Column("variant", sa.String(length=100), nullable=True))
    op.add_column("deals", sa.Column("eco_commission", sa.String(length=50), nullable=True))
    op.add_column("deals", sa.Column("peco_commission", sa.String(length=50), nullable=True))
    op.add_column("deals", sa.Column("bus_commission", sa.String(length=50), nullable=True))
    op.add_column("deals", sa.Column("base_type", sa.String(length=20), nullable=True))
    op.add_column("deals", sa.Column("valid_on", sa.String(length=20), nullable=True))
    op.add_column("deals", sa.Column("validity_raw", sa.String(length=255), nullable=True))

    # Build normalized child tables.
    op.create_table(
        "deal_incentives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("incentive_type", sa.String(length=100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "deal_incl_excl_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(length=100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("vice_versa", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Backfill row values from deal_components (first row per deal).
    op.execute(
        """
        UPDATE deals d
        SET
          variant = c.variant,
          eco_commission = c.eco_commission,
          peco_commission = c.peco_commission,
          bus_commission = c.bus_commission,
          base_type = c.base_type,
          valid_on = c.valid_on,
          validity_raw = c.validity_raw
        FROM (
          SELECT DISTINCT ON (deal_id)
            deal_id, variant, eco_commission, peco_commission, bus_commission, base_type, valid_on, validity_raw
          FROM deal_components
          ORDER BY deal_id, row_order, id
        ) c
        WHERE d.id = c.deal_id
        """
    )

    # Backfill incentives.
    op.execute(
        """
        INSERT INTO deal_incentives (deal_id, incentive_type, data)
        SELECT d.id, t.value, COALESCE(d.incentive_data -> t.value, '{}'::json)
        FROM deals d
        CROSS JOIN LATERAL json_array_elements_text(
            CASE
                WHEN json_typeof(COALESCE(d.incentive_types, '[]'::json)) = 'array'
                THEN COALESCE(d.incentive_types, '[]'::json)
                ELSE '[]'::json
            END
        ) AS t(value)
        """
    )

    # Backfill inclusion/exclusion rules.
    op.execute(
        """
        INSERT INTO deal_incl_excl_rules (deal_id, rule_type, data, vice_versa)
        SELECT
          d.id,
          t.value,
          COALESCE(d.incl_excl_data -> t.value, '{}'::json),
          COALESCE((d.vice_versa ->> t.value)::boolean, false)
        FROM deals d
        CROSS JOIN LATERAL json_array_elements_text(
            CASE
                WHEN json_typeof(COALESCE(d.incl_excl_types, '[]'::json)) = 'array'
                THEN COALESCE(d.incl_excl_types, '[]'::json)
                ELSE '[]'::json
            END
        ) AS t(value)
        """
    )

    # Remove old complex JSON columns from deals.
    op.drop_column("deals", "incentive_types")
    op.drop_column("deals", "incentive_data")
    op.drop_column("deals", "incl_excl_types")
    op.drop_column("deals", "incl_excl_data")
    op.drop_column("deals", "vice_versa")

    # Drop unused per-document component table.
    op.drop_table("deal_components")


def downgrade() -> None:
    # No destructive downgrade for this refactor migration.
    pass
