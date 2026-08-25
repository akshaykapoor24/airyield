"""One agency row per channel, and a stored GST-registered flag

TWO CHANGES, AND THEY BELONG TOGETHER because both come from the same screen.

1. `uq_agencies_user_name_branch` (user_id, name, branch_code) becomes
   `uq_agencies_user_name_branch_channel` (user_id, name, branch_code, channels).

   The Add Agency form used to offer GDS / LCC / Both, and "Both" produced ONE row
   carrying two commercial arrangements. That row then had to be special-cased
   everywhere — one line in the table showing two sets of terms, an account page
   that could not answer "what is the balance" without being told which channel,
   a `_widen`/`_narrow` pair to move between the three states. The form now offers
   GDS or LCC only, and an agency that works both is onboarded twice. Two rows,
   two deposits, two ledgers, two lines in the table, and nothing to disambiguate
   at read time. The old constraint is exactly what blocked that, so it goes.

   WHAT THIS DOES NOT DO is migrate existing "BOTH" rows into pairs. Splitting one
   would mean splitting its terms, its ledger and its billing history across two
   ids, and there is no honest way to decide which of the two new rows an existing
   invoice belonged to. They stay as they are and every reader keeps using
   `scope_covers`; only NEW agencies are one-channel.

   The widened key is strictly more permissive, so no existing row can violate it
   and the upgrade cannot fail on data.

2. `agencies.gst_registered` (bool, default false), backfilled true wherever a GST
   number is already present.

   The form now asks for PAN, then whether the agency is GST registered, and only
   then for the GSTIN — the order the checks in app.core.india_tax need, since a
   GSTIN's first two characters are its state and characters 3-12 are its PAN. The
   flag is stored rather than inferred from `gst_number IS NOT NULL` because
   "not registered" and "nobody has typed it in yet" are different facts and only
   the first means the blank is correct.

Revision ID: agency_channel_03
Revises: agency_channel_02
Create Date: 2026-08-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_channel_03"
down_revision: Union[str, None] = "agency_channel_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agencies",
        sa.Column("gst_registered", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # An agency that already carries a GSTIN is registered by definition — without
    # this every existing row would read "Unregistered" while showing its GSTIN.
    op.execute(
        "UPDATE agencies SET gst_registered = true "
        "WHERE gst_number IS NOT NULL AND btrim(gst_number) <> ''"
    )

    # Widen before dropping is not possible (the old key would reject nothing the
    # new one accepts, but two constraints on overlapping columns is noise), so
    # drop then add. Both statements are in one transaction.
    op.drop_constraint("uq_agencies_user_name_branch", "agencies", type_="unique")
    op.create_unique_constraint(
        "uq_agencies_user_name_branch_channel",
        "agencies",
        ["user_id", "name", "branch_code", "channels"],
    )


def downgrade() -> None:
    # NARROWING CAN FAIL, and that is correct. Once a vendor's branch has been
    # onboarded on GDS and on LCC, two rows share (user_id, name, branch_code) and
    # the old constraint cannot be recreated over them. There is no safe automatic
    # answer — merging them would have to merge two ledgers. Find them first:
    #   SELECT user_id, name, branch_code, count(*), string_agg(channels, ',')
    #     FROM agencies GROUP BY 1,2,3 HAVING count(*) > 1;
    # then decide per pair whether to delete one or rename its branch_code.
    op.drop_constraint("uq_agencies_user_name_branch_channel", "agencies", type_="unique")
    op.create_unique_constraint(
        "uq_agencies_user_name_branch",
        "agencies",
        ["user_id", "name", "branch_code"],
    )
    op.drop_column("agencies", "gst_registered")
