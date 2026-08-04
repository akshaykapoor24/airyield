"""Per-entity GST + PAN on user_entities

An entity is a billing/legal unit, so each one carries its own GSTIN (which is
state-specific) and PAN. These are captured in the Add Entity form — manual and
XLS upload — during onboarding and later from My Profile.

Revision ID: user_entity_tax_01
Revises: bsp_commission_02
Create Date: 2026-07-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "user_entity_tax_01"
down_revision: Union[str, None] = "bsp_commission_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_entities", sa.Column("gst_number", sa.String(length=15), nullable=True))
    op.add_column("user_entities", sa.Column("pan_number", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("user_entities", "pan_number")
    op.drop_column("user_entities", "gst_number")
