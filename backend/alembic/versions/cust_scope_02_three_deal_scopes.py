"""Collapse the outgoing-deal scope to three values

The form originally asked two questions — a Deal Type (B2B / Corporate / Common)
and, for the first two, a breadth (this one party, or all of them). That produced
five scopes. The breadth question is gone: "B2B" now MEANS agency-specific and
"Corporate" means corporate-specific, and a deal meant to reach everyone is a
Common Deal. Three choices, three scopes, no sub-questions.

    agency      one named agency      (agency_id set)
    corporate   one named corporate   (corporate_id set)
    all         every customer

`agency_all` and `corporate_all` are therefore no longer reachable from any form.
They are removed rather than left in the CHECK, so nobody writes and tests a code
path in the commission engine that can never run.

MIGRATING THE TWO RETIRED VALUES. Both meant "every party of this type, none in
particular", and neither carried a party id. The only surviving scope that means
"no particular party" is `all`, so they map there. That WIDENS such a deal from
one customer type to every customer type — a real semantic change, and the reason
this migration reports what it touched instead of doing it quietly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cust_scope_02"
down_revision: Union[str, None] = "cust_scope_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    affected = conn.execute(sa.text(
        "SELECT id, scope_type, airline_name FROM deals "
        "WHERE scope_type IN ('agency_all','corporate_all') ORDER BY id"
    )).all()
    for row in affected:
        print(f"  cust_scope_02: deal {row[0]} ({row[2]}) {row[1]} -> all")

    # Backfill BEFORE swapping the constraint, or the new CHECK rejects these rows.
    # The display labels move with the scope: leaving "All Corporates" on a row that
    # now reaches every customer would misreport it in the repository.
    op.execute("""
        UPDATE deals
           SET scope_type = 'all',
               scope_party_name = 'All Customers',
               supplier_name = CASE
                   WHEN supplier_name IN ('All Agencies','All Corporates') THEN 'All Customers'
                   ELSE supplier_name
               END
         WHERE scope_type IN ('agency_all','corporate_all')
    """)

    # The batch and statement carry their own copy of the label, and the repository's
    # "Supplier / Source" column reads the BATCH one — so leaving these behind makes a
    # converted deal read "All Corporates" in the list and "All Customers" on the deal.
    for table in ("deal_batches", "deal_statements"):
        op.execute(f"""
            UPDATE {table} SET supplier_name = 'All Customers'
             WHERE supplier_name IN ('All Agencies','All Corporates')
        """)

    op.drop_constraint("ck_deals_scope_type", "deals", type_="check")
    op.create_check_constraint(
        "ck_deals_scope_type", "deals",
        "scope_type IN ('agency','corporate','all')",
    )


def downgrade() -> None:
    # Widening the constraint back is safe; the rows that were collapsed into
    # 'all' cannot be told apart from genuine 'all' deals afterwards, so they
    # stay as they are.
    op.drop_constraint("ck_deals_scope_type", "deals", type_="check")
    op.create_check_constraint(
        "ck_deals_scope_type", "deals",
        "scope_type IN ('agency','agency_all','corporate','corporate_all','all')",
    )
