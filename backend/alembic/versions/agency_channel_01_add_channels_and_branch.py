"""Split an agency by branch, and its commercial terms by channel

Two facts the old shape could not hold, both of them ordinary in this trade.

BRANCH. A vendor exists as several supplier rows, one per branch — three "Air
India Limited", fourteen "Riya Travel & Tours". Until now `uq_agencies_user_name`
allowed exactly ONE agency per vendor name per user, so onboarding Lords Delhi
and Lords Mumbai as separate commercial relationships was impossible; picking a
branch only chose whose city and contact details to copy. But they ARE separate
relationships: separate deposits, separate limits, separate invoices, separate
people to chase. So one agency row is now one branch, held apart by
`uq_agencies_user_name_branch` on (user_id, name, branch_code). `branch_code` is
a SNAPSHOT of `suppliers.code` (unique across the supplier master) rather than a
foreign key, matching how every other supplier field is copied at add-time —
deleting a supplier can then neither orphan nor collide an agency. `supplier_id`
is kept as nullable provenance only. An agency typed in by hand gets 'MAIN'.

  THE TRAP THIS OPENS, AND WHY ticket_statements.agency_id IS IN THIS MIGRATION.
  Ticket statements record only the bare vendor NAME. With two branches of one
  vendor onboarded, `lower(trim(ticket_statements.agency)) == agencies.name`
  matches BOTH of them, and whichever billed first would silently take the
  other's tickets — `uploaded_tickets.billing_id` is a single FK, so they would
  not come back. Adding the column is therefore not a nicety that can follow
  later; it is the thing that makes the branch split safe. Agency Billing and
  unbilled_exposure resolve by id when it is set and fall back to the name match
  ONLY when that name resolves to exactly one agency. An ambiguous name refuses
  to bill rather than guessing, which is the correct failure.

CHANNEL. An agency is routinely CASH on one channel and CREDIT on the other, and
for a real reason: on GDS the sub-agent books on our IATA stock through a mirror
office, so the BSP liability is ours from the moment of issue and he pays first;
on LCC each airline settles through its own wallet, so exposure is capped per
carrier and a credit line is safe. Lords is cash on GDS (1 crore on deposit,
notify at 90%) and credit on LCC (50 lakh line, fortnightly). `agency_terms` had
one `agency_type` per agency, so storing the second arrangement overwrote the
first.

`channel` is therefore NOT NULL on agency_terms and on agency_ledger, and that
is arithmetic rather than tidiness. Every balance read becomes
SUM(amount) WHERE channel = 'GDS'. A NULL-channel ledger row would be excluded
from that AND from the LCC sum, so the two per-channel balances would stop adding
up to the agency's total — money sitting in the table and in no account.
Deriving it from `terms_id` is not available either: that FK is ON DELETE SET
NULL and is NULL for any entry posted before terms existed.

`uq_agency_terms_current` — UNIQUE (agency_id, channel) WHERE effective_to IS
NULL — is the first partial index in this schema and it earns its place.
`current_terms()` orders by effective_from and takes the first row; it already
assumed there might be more than one open period and quietly picked one. With
channels, "quietly picks one" becomes "reports the wrong channel's limit and
balance". The index turns that into a 23505 at write time.

ENTITIES GET A SCOPE, NOT A DUPLICATE ROW. `agency_entities.channels` is
GDS|LCC|BOTH on ONE entity, and `uq_agency_entities_agency_code` is untouched. A
legal entity does not acquire a second GSTIN because a booking went through a
GDS. Duplicating per channel would have meant widening that constraint, and two
live consumers cannot survive it: the bulk `entity_lookup` in
agency_login_ids.py is keyed (agency_id, code|name) with .setdefault, so
duplicate codes would silently attach every LCC login id to the GDS entity; and
deals/new resolves an entity by NAME, because `Deal.entity` stores a name.

LOGIN IDS GET A STRICT CHANNEL, and no new credential column. `login_id` carries
the mirror id on GDS and the portal login / airline id on LCC, relabelled in the
UI. Splitting it into a `mirror_id` sibling would require making `login_id`
nullable, and it is NOT NULL and indexed, it is the order-by key and primary
display column, it is the option value in the deals form (landing in
`Deal.login_id` / `Deal.login_ids`), and it is snapshotted into
`CustomerStatement.login_ids`. `Deal.entity_lcc` is this repo's own worked
example of that mistake — a per-channel sibling column beside `Deal.entity`,
now dead code.

THE FIVE SNAPSHOT COLUMNS ON `agencies` ARE DROPPED, not made channel-aware.
agency_type / credit_limit / deposit_amount / usage_percent / billing_cycle were
a denormalised copy of the current terms, and they were already provably wrong
in three independent ways before channels entered the picture:
  * two writers disagreed — agencies._normalise_terms stored
    credit_limit = deposit_amount for cash, switch_terms stored NULL for the same
    column (switch_terms was right; account_summary derives a cash limit from
    ledger paid_in and ignores the column);
  * POST posted the opening deposit to the ledger and PATCH's first-time-terms
    branch did not, so the same user action produced different money;
  * from-suppliers and bulk-upload wrote the snapshot and created no terms row at
    all, so the list could read "Cash" while current_terms() returned None.
Under channels there is no longer a single correct value to store — Lords is
cash AND credit — so the columns cannot be repaired, only removed. Reads now go
to agency_terms through one grouped query.

THIS MIGRATION DELETES ALL AGENCY DATA. Confirmed with the owner that agencies,
agency_terms, agency_ledger, agency_entities and agency_login_ids hold test data
only. There is nothing anywhere recording whether an existing agency traded on
GDS or LCC, so a backfill would have to guess, and guessing wrong on a ledger
means a balance filed against an arrangement it was never incurred under. If you
are running this against data you care about, STOP and export first:

    SELECT * FROM agencies         ORDER BY id;
    SELECT * FROM agency_terms     ORDER BY agency_id, effective_from;
    SELECT * FROM agency_ledger    ORDER BY agency_id, entry_date, id;
    SELECT * FROM agency_entities  ORDER BY agency_id, code;
    SELECT * FROM agency_login_ids ORDER BY agency_id, login_id;
    SELECT id, agency_id, billing_name FROM billings WHERE agency_id IS NOT NULL;

Revision ID: agency_channel_01
Revises: agency_account_01
Create Date: 2026-08-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_channel_01"
down_revision: Union[str, None] = "agency_account_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Purge, child-first so the FKs never complain ──────────────────────
    # Every one of the columns added below is NOT NULL with no sensible default,
    # and no data anywhere says which channel an existing row belonged to. See
    # the docstring: this is only correct because the owner confirmed it is test
    # data. `billings` rows are kept but detached — a customer or corporate
    # billing has no agency and must survive.
    op.execute("DELETE FROM agency_ledger")
    op.execute("DELETE FROM agency_terms")
    op.execute("DELETE FROM agency_login_ids")
    op.execute("DELETE FROM agency_entities")
    op.execute("UPDATE billings SET agency_id = NULL WHERE agency_id IS NOT NULL")
    op.execute("DELETE FROM agencies")

    # ── 2. agencies: branch identity + channel declaration ───────────────────
    # server_default carries the NOT NULL past the (now empty) table and past any
    # row a concurrent session might insert mid-migration; dropped immediately so
    # the application is the only writer of these.
    op.add_column("agencies", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_agencies_supplier_id", "agencies", "suppliers",
        ["supplier_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_agencies_supplier_id", "agencies", ["supplier_id"])

    op.add_column("agencies", sa.Column("branch_code", sa.String(length=50), nullable=False, server_default="MAIN"))
    op.add_column("agencies", sa.Column("branch_name", sa.String(length=255), nullable=True))
    op.add_column("agencies", sa.Column("channels", sa.String(length=10), nullable=False, server_default="GDS"))
    op.alter_column("agencies", "branch_code", server_default=None)
    op.alter_column("agencies", "channels", server_default=None)

    # One agency per vendor per BRANCH, instead of one per vendor.
    op.drop_constraint("uq_agencies_user_name", "agencies", type_="unique")
    op.create_unique_constraint(
        "uq_agencies_user_name_branch", "agencies", ["user_id", "name", "branch_code"],
    )

    # The denormalised terms snapshot — see the docstring for why it goes rather
    # than gaining a channel.
    op.drop_column("agencies", "billing_cycle")
    op.drop_column("agencies", "usage_percent")
    op.drop_column("agencies", "deposit_amount")
    op.drop_column("agencies", "credit_limit")
    op.drop_column("agencies", "agency_type")

    # ── 3. agency_terms: one arrangement per channel ─────────────────────────
    op.add_column("agency_terms", sa.Column("channel", sa.String(length=10), nullable=False, server_default="GDS"))
    op.alter_column("agency_terms", "channel", server_default=None)
    op.create_index(
        "uq_agency_terms_current", "agency_terms", ["agency_id", "channel"],
        unique=True, postgresql_where=sa.text("effective_to IS NULL"),
    )

    # ── 4. agency_ledger: one balance per channel ────────────────────────────
    op.add_column("agency_ledger", sa.Column("channel", sa.String(length=10), nullable=False, server_default="GDS"))
    op.alter_column("agency_ledger", "channel", server_default=None)
    # ix_agency_ledger_agency_date stays — list_ledger still reads agency-wide
    # when no channel filter is passed, and a combined statement is meaningful.
    op.create_index(
        "ix_agency_ledger_agency_channel_date", "agency_ledger",
        ["agency_id", "channel", "entry_date", "id"],
    )

    # ── 5. agency_entities: a scope, not a discriminator ─────────────────────
    op.add_column("agency_entities", sa.Column("channels", sa.String(length=10), nullable=False, server_default="BOTH"))
    op.alter_column("agency_entities", "channels", server_default=None)
    op.create_index("ix_agency_entities_agency_channels", "agency_entities", ["agency_id", "channels"])

    # ── 6. agency_login_ids: strictly one channel ────────────────────────────
    op.add_column("agency_login_ids", sa.Column("channel", sa.String(length=10), nullable=False, server_default="GDS"))
    op.alter_column("agency_login_ids", "channel", server_default=None)
    op.create_index("ix_agency_login_ids_agency_channel", "agency_login_ids", ["agency_id", "channel"])

    # ── 7. billings: which channel an agency invoice settles ─────────────────
    # Nullable: customer and corporate billings share this table and have no channel.
    op.add_column("billings", sa.Column("channel", sa.String(length=10), nullable=True))

    # ── 8. ticket_statements: bill the right branch ──────────────────────────
    op.add_column("ticket_statements", sa.Column("agency_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_ticket_statements_agency_id", "ticket_statements", "agencies",
        ["agency_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_ticket_statements_agency_id", "ticket_statements", ["agency_id"])


def downgrade() -> None:
    # THIS DESTROYS THE CHANNEL SPLIT AND THE BRANCH SPLIT, and neither can be
    # reconstructed afterwards:
    #   * every GDS and LCC arrangement collapses into indistinguishable
    #     agency_terms rows, and without uq_agency_terms_current holding them
    #     apart current_terms() returns whichever has the later effective_from —
    #     so the limit shown against one arrangement will be the other's;
    #   * every LCC deposit, receipt and invoice in agency_ledger becomes
    #     unattributable;
    #   * restoring uq_agencies_user_name WILL FAIL if you have onboarded two
    #     branches of one vendor. Delete the surplus branches first, and know
    #     that deleting an agency cascades its terms, ledger, entities and login
    #     ids with it;
    #   * the five snapshot columns come back EMPTY and cannot be repopulated,
    #     because there is no longer one correct value per agency — an agency
    #     that is cash on GDS and credit on LCC has no single agency_type.
    # Export before running (the SELECTs are in the upgrade docstring), plus:
    #   SELECT id, name, branch_code, branch_name, channels FROM agencies ORDER BY id;
    #   SELECT batch_id, agency, agency_id FROM ticket_statements WHERE agency_id IS NOT NULL;

    op.drop_index("ix_ticket_statements_agency_id", table_name="ticket_statements")
    op.drop_constraint("fk_ticket_statements_agency_id", "ticket_statements", type_="foreignkey")
    op.drop_column("ticket_statements", "agency_id")

    op.drop_column("billings", "channel")

    op.drop_index("ix_agency_login_ids_agency_channel", table_name="agency_login_ids")
    op.drop_column("agency_login_ids", "channel")

    op.drop_index("ix_agency_entities_agency_channels", table_name="agency_entities")
    op.drop_column("agency_entities", "channels")

    op.drop_index("ix_agency_ledger_agency_channel_date", table_name="agency_ledger")
    op.drop_column("agency_ledger", "channel")

    # The partial index must go BEFORE its column, or the drop_column fails.
    op.drop_index("uq_agency_terms_current", table_name="agency_terms")
    op.drop_column("agency_terms", "channel")

    op.add_column("agencies", sa.Column("agency_type", sa.String(length=10), nullable=True))
    op.add_column("agencies", sa.Column("credit_limit", sa.Numeric(14, 2), nullable=True))
    op.add_column("agencies", sa.Column("deposit_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("agencies", sa.Column("usage_percent", sa.Numeric(6, 2), nullable=True))
    op.add_column("agencies", sa.Column("billing_cycle", sa.String(length=20), nullable=True))

    op.drop_constraint("uq_agencies_user_name_branch", "agencies", type_="unique")
    op.create_unique_constraint("uq_agencies_user_name", "agencies", ["user_id", "name"])

    op.drop_column("agencies", "channels")
    op.drop_column("agencies", "branch_name")
    op.drop_column("agencies", "branch_code")
    op.drop_index("ix_agencies_supplier_id", table_name="agencies")
    op.drop_constraint("fk_agencies_supplier_id", "agencies", type_="foreignkey")
    op.drop_column("agencies", "supplier_id")
