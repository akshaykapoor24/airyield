"""Split an agency's contract and its money out of the agency row

agency_terms_01 put agency_type / credit_limit / deposit_amount / usage_percent /
billing_cycle directly on `agencies`. That works for "what is true now" and fails
for everything else, because both of the things the business actually does to an
agency are EVENTS, not field edits:

  top-up   — he deposits 10L, burns it in a week, pays another 5L. Overwriting
             deposit_amount with 15L cannot say when either payment arrived, how
             it was paid, or what the balance was on any past date.
  switch   — cash in week 1, credit in week 2. Overwriting agency_type rewrites
             history: the week-1 invoice can no longer be explained under the
             terms it was raised on. Worse, the PATCH handler NULLs deposit and
             usage on the way through, so the old arrangement is simply gone.

So the contract becomes effective-dated rows (`agency_terms`) and the money
becomes an append-only ledger (`agency_ledger`). The columns on `agencies` stay
as a denormalised snapshot of the CURRENT terms so Agency Master and Agency
Billing keep reading one row; agency_terms is the source of truth and both are
written in the same transaction.

THE INVARIANT THAT MAKES THIS SIMPLE. A type switch is only legal at a cycle
boundary with a zero balance — settle first, in both directions. So every terms
period opens at zero and closes at zero, and no ledger period ever straddles a
type change. A cash period and a credit period are therefore separate,
self-contained accounts and no entry is ever ambiguous about which arrangement
it belongs to. Reconciling a closed period is just SUM(amount) = 0.

SIGN CONVENTION, once, because getting this wrong is expensive. `amount` is
signed from the AGENCY'S point of view against us:
    +  money in from the agency      (topup, receipt, opening credit)
    −  value billed to the agency    (invoice, refund paid back out)
    balance = SUM(amount)
    balance > 0  he has credit with us  (unused cash deposit)
    balance < 0  he owes us             (credit outstanding)
The type only sets the floor: cash may not go below 0, credit may not go below
−credit_limit. One convention, both arrangements.

Note `deposit_amount` changes meaning and is left on `agencies` only as a cached
figure — under a ledger a cash agency's limit IS its balance, so "deposit equals
limit" stops being a rule anyone enforces and becomes arithmetic.

Cycles are deliberately NOT a table. They are computed from
agency_terms.cycle_anchor_date plus the cycle length, and a cycle counts as
billed when a `billings` row covers it. A table would need generating, back-
filling and keeping in sync for information that is already derivable.

NO ledger rows are created here. Existing agencies get a terms row only if they
already have an agency_type (nobody has one at the time of writing), and their
opening balance is whatever the first posted entry says — see the opening_balance
entry type, which exists so an agency already trading can be brought on without
inventing a fake top-up.

Revision ID: agency_account_01
Revises: agency_terms_01
Create Date: 2026-08-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_account_01"
down_revision: Union[str, None] = "agency_terms_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agency_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        # effective_to NULL == the arrangement in force right now.
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("agency_type", sa.String(length=10), nullable=False),
        sa.Column("credit_limit", sa.Numeric(14, 2), nullable=True),
        sa.Column("usage_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("billing_cycle", sa.String(length=20), nullable=False),
        # Without an anchor, "monthly" cannot say WHEN a month starts, and
        # "the cycle is complete" is unanswerable — which is the precondition
        # the whole switch rule rests on.
        sa.Column("cycle_anchor_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_agency_terms_agency_from", "agency_terms", ["agency_id", "effective_from"])

    op.create_table(
        "agency_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("terms_id", sa.Integer(), sa.ForeignKey("agency_terms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        # opening_balance | topup | invoice | receipt | refund | adjustment | reversal
        sa.Column("entry_type", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),   # signed, see docstring
        sa.Column("billing_id", sa.Integer(), sa.ForeignKey("billings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payment_mode", sa.String(length=20), nullable=True),
        sa.Column("reference_no", sa.String(length=100), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        # Entries are never edited or deleted — a mistake is corrected by posting
        # the opposite entry pointing back here.
        sa.Column("reversal_of_id", sa.Integer(), sa.ForeignKey("agency_ledger.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    # The statement view and every balance read order by exactly this.
    op.create_index("ix_agency_ledger_agency_date", "agency_ledger", ["agency_id", "entry_date", "id"])
    op.create_index("ix_agency_ledger_billing", "agency_ledger", ["billing_id"])

    # Agencies already configured with a type get an opening terms period so the
    # switch guard has something to close. Their cycle anchor is the day the
    # agency was created — the best available approximation, and editable after.
    op.execute(
        """
        INSERT INTO agency_terms (
            agency_id, user_id, tenant_id, effective_from, effective_to,
            agency_type, credit_limit, usage_percent, billing_cycle,
            cycle_anchor_date, note, created_by_id, created_at
        )
        SELECT id, user_id, tenant_id, created_at::date, NULL,
               agency_type, credit_limit, usage_percent,
               COALESCE(billing_cycle, 'monthly'),
               created_at::date,
               'Opening terms recorded when payment tracking was introduced',
               user_id, CURRENT_TIMESTAMP
        FROM agencies
        WHERE agency_type IS NOT NULL
        """
    )

    # A cash agency onboarded before this existed has its deposit sitting in
    # agencies.deposit_amount with nothing behind it. Left alone its account
    # would read as empty — no money in, no limit, nothing to spend — because
    # under the ledger a cash limit IS the balance. Seed the deposit as an
    # opening balance so the figure the user already entered survives.
    op.execute(
        """
        INSERT INTO agency_ledger (
            agency_id, user_id, tenant_id, terms_id, entry_date,
            entry_type, amount, note, created_by_id, created_at
        )
        SELECT a.id, a.user_id, a.tenant_id, t.id,
               COALESCE(t.effective_from, a.created_at::date),
               'opening_balance', a.deposit_amount,
               'Deposit carried over when payment tracking was introduced',
               a.user_id, CURRENT_TIMESTAMP
        FROM agencies a
        JOIN agency_terms t ON t.agency_id = a.id AND t.effective_to IS NULL
        WHERE a.agency_type = 'cash'
          AND a.deposit_amount IS NOT NULL
          AND a.deposit_amount > 0
        """
    )


def downgrade() -> None:
    # This DELETES the entire payment history: every top-up, receipt, refund and
    # invoice entry, plus the record of which arrangement was in force when. The
    # snapshot columns on `agencies` survive, so the CURRENT terms remain — but
    # everything before them is gone and cannot be reconstructed from `billings`
    # alone (billings never recorded money coming IN). Export first:
    #   SELECT * FROM agency_ledger ORDER BY agency_id, entry_date, id;
    #   SELECT * FROM agency_terms  ORDER BY agency_id, effective_from;
    op.drop_index("ix_agency_ledger_billing", table_name="agency_ledger")
    op.drop_index("ix_agency_ledger_agency_date", table_name="agency_ledger")
    op.drop_table("agency_ledger")
    op.drop_index("ix_agency_terms_agency_from", table_name="agency_terms")
    op.drop_table("agency_terms")
