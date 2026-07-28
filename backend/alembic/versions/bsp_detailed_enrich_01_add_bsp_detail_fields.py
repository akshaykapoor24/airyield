"""Enrich BSP detailed rows + airline IATA numeric code

Adds:
  * airlines.iata_numeric_code (3-digit BSP/IATA numeric code) — backfilled from icao_code
    (where the bulk-upload historically stored the numeric code).
  * bsp_statement_rows: airline_name, tour (JSONB), alt_document_numbers (JSONB), rtdn, esac, wavr.

Revision ID: bsp_detailed_enrich_01
Revises: lcc_detailed_v2_01
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "bsp_detailed_enrich_01"
down_revision: Union[str, None] = "lcc_detailed_v2_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── airlines: dedicated 3-digit IATA numeric code ────────────────────────
    op.add_column("airlines", sa.Column("iata_numeric_code", sa.String(length=3), nullable=True))
    op.create_index("ix_airlines_iata_numeric_code", "airlines", ["iata_numeric_code"])
    # Backfill from icao_code where it currently holds a 2-3 digit numeric code.
    op.execute(
        "UPDATE airlines SET iata_numeric_code = lpad(icao_code, 3, '0') "
        "WHERE icao_code ~ '^[0-9]{2,3}$'"
    )

    # ── bsp_statement_rows: detailed-PDF enrichment columns ──────────────────
    op.add_column("bsp_statement_rows", sa.Column("airline_name", sa.String(length=200), nullable=True))
    op.add_column("bsp_statement_rows", sa.Column("tour", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("bsp_statement_rows", sa.Column("alt_document_numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("bsp_statement_rows", sa.Column("rtdn", sa.String(length=100), nullable=True))
    op.add_column("bsp_statement_rows", sa.Column("esac", sa.String(length=50), nullable=True))
    op.add_column("bsp_statement_rows", sa.Column("wavr", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("bsp_statement_rows", "wavr")
    op.drop_column("bsp_statement_rows", "esac")
    op.drop_column("bsp_statement_rows", "rtdn")
    op.drop_column("bsp_statement_rows", "alt_document_numbers")
    op.drop_column("bsp_statement_rows", "tour")
    op.drop_column("bsp_statement_rows", "airline_name")

    op.drop_index("ix_airlines_iata_numeric_code", table_name="airlines")
    op.drop_column("airlines", "iata_numeric_code")
