"""Give an agency branch its postal address

An agency row IS a branch, and a branch has an address — but agency_channel_01
only carried `city` and `region_chapter` across from the master. That left the
Add Entities form asking the user to retype the address, state and city of a
place the system had just onboarded, once per entity. An entity is an office of
its branch and in the ordinary case sits at the same address, so the branch has
to hold one for the entity to inherit it.

WHERE THE VALUES COME FROM. `address` is the supplier master's address_1 /
address_2 / address_3 joined — the three are a single postal address split
across columns, not alternatives. `city` was already being copied.

`state` HAS NO SOURCE AND IS TYPED IN. The master's nearest column is
`region_chapter`, which holds values like "WESTERN REGION" — an IATA chapter,
not a state, and mapping one to the other would be a guess dressed up as data.
So it is left blank on auto-fill and entered on the Add Agency form, once per
branch, after which every entity under it inherits it.

Both columns are nullable: an agency typed in by hand may have neither, and an
entity is free to override both when an office really is somewhere else.

Revision ID: agency_channel_02
Revises: agency_channel_01
Create Date: 2026-08-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_channel_02"
down_revision: Union[str, None] = "agency_channel_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Text rather than String(500) to match the master's address_1..3, which are
    # Text and whose joined value can exceed 500 characters.
    op.add_column("agencies", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("agencies", sa.Column("state", sa.String(length=100), nullable=True))


def downgrade() -> None:
    # Drops each branch's address and state. `city` and `region_chapter` survive,
    # and the address can be re-copied from the supplier master for any agency
    # that still has a `supplier_id` — but a hand-typed `state` cannot be
    # recovered from anywhere. Export first if you care:
    #   SELECT id, name, branch_code, address, state FROM agencies
    #    WHERE address IS NOT NULL OR state IS NOT NULL;
    op.drop_column("agencies", "state")
    op.drop_column("agencies", "address")
