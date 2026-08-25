"""Tag every internal statement and ticket with WHO it was sold to

An internal statement records only `agency` — a bare vendor NAME — plus an
optional `agency_id`. That answers "which agency", never "is this an agency at
all", so a corporate or a walk-in customer has nowhere to live. The customer-side
commission run needs the opposite question answered: for this ticket, which party
do I owe, and of what kind?

    customer_type        agency | corporate | direct
    customer_agency_id   -> agencies.id      (when customer_type = 'agency')
    corporate_id         -> corporates.id    (when customer_type = 'corporate')
    customer_id          -> customers.id     (when customer_type = 'direct')

BOTH TABLES CARRY IT, and that is deliberate. The statement's copy is the default
chosen at upload; the TICKET's copy is what the commission engine reads, because
Create Tickets can file one ticket at a time and a single uploaded file can hold
rows sold to different customers.

WHY NOT REUSE `agency` / `agency_id`. `ticket_statements.agency` is NOT NULL and
is read by Agency Billing, agency_account, reports, uploaded_documents, the income
summary and the customer-facing PDF/XLSX export. It keeps holding the party's
DISPLAY NAME so every one of those keeps working, and `agency_id` stays set only
for an agency-typed statement, so Agency Billing behaves exactly as before.

THE TRAP THIS OPENS, and why agency_account.py changes in the same commit.
`agency_statement_scope` falls back to matching on the agency NAME whenever
`agency_id IS NULL`. Once a corporate statement can carry a corporate's name in
that column, an agency with the same name silently claims its tickets — and
`uploaded_tickets.billing_id` is a single FK that does not come back. The name
fallback is therefore narrowed to statements that are not tagged to some other
customer type.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cust_party_01"
down_revision: Union[str, None] = "cust_scope_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ("ticket_statements", "uploaded_tickets")


def upgrade() -> None:
    # A corporate's company name can reach 255 and a person's first+last 400,
    # while this column was sized for a vendor name.
    op.alter_column(
        "ticket_statements", "agency",
        existing_type=sa.String(200), type_=sa.String(300), existing_nullable=False,
    )

    for t in TABLES:
        op.add_column(t, sa.Column("customer_type", sa.String(12), nullable=True))
        op.add_column(t, sa.Column("customer_agency_id", sa.Integer(), nullable=True))
        op.add_column(t, sa.Column("corporate_id", sa.Integer(), nullable=True))
        op.add_column(t, sa.Column("customer_id", sa.Integer(), nullable=True))
        # SET NULL, not RESTRICT: unlike a deal's scope, a ticket's tag is history.
        # Deleting the party should not be blocked by, nor erase, tickets already
        # sold — the display name survives in `agency` / `customer_name`.
        op.create_foreign_key(
            f"fk_{t}_customer_agency_id", t, "agencies",
            ["customer_agency_id"], ["id"], ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{t}_corporate_id", t, "corporates",
            ["corporate_id"], ["id"], ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{t}_customer_id", t, "customers",
            ["customer_id"], ["id"], ondelete="SET NULL",
        )
        op.create_check_constraint(
            f"ck_{t}_customer_type", t,
            "customer_type IS NULL OR customer_type IN ('agency','corporate','direct')",
        )

    # Every existing statement was filed against an onboarded agency, so that is
    # what they are. Rows with no agency_id stay untagged rather than being
    # guessed at — an untagged row is visibly incomplete, a wrongly-tagged one is
    # not, and the name fallback in agency_account depends on the difference.
    op.execute("""
        UPDATE ticket_statements
           SET customer_type = 'agency', customer_agency_id = agency_id
         WHERE agency_id IS NOT NULL
    """)
    op.execute("""
        UPDATE uploaded_tickets t
           SET customer_type = s.customer_type, customer_agency_id = s.customer_agency_id
          FROM ticket_statements s
         WHERE s.batch_id = t.batch_id AND s.customer_type IS NOT NULL
    """)

    op.create_index(
        "ix_uploaded_tickets_party", "uploaded_tickets",
        ["tenant_id", "customer_type", "customer_agency_id", "corporate_id", "customer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_uploaded_tickets_party", table_name="uploaded_tickets")
    for t in TABLES:
        op.drop_constraint(f"ck_{t}_customer_type", t, type_="check")
        for col in ("customer_id", "corporate_id", "customer_agency_id"):
            op.drop_constraint(f"fk_{t}_{col}", t, type_="foreignkey")
        for col in ("customer_id", "corporate_id", "customer_agency_id", "customer_type"):
            op.drop_column(t, col)
    op.alter_column(
        "ticket_statements", "agency",
        existing_type=sa.String(300), type_=sa.String(200), existing_nullable=False,
    )
