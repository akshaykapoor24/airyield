"""Link an employee to the corporate they work for

Employee Master (the customer master) asked for the employer as free text, so
"Acme Pvt Ltd", "Acme pvt ltd" and "ACME" were three different employers and none
of them was the corporate of that name sitting in Corporate Master. Corporate
Billing therefore had no way to find a corporate's people, which is exactly what
it needs to bill: an organisation buys no tickets, its staff do.

    customers.corporate_id -> corporates.id   ON DELETE SET NULL

NULL IS A REAL ANSWER, not a missing one: it means individual / direct — someone
billed in their own right, with no employer behind them. That is why the column
is nullable and why deleting a corporate SETs its people NULL rather than
cascading. Losing an employer does not delete a person.

`customers.company` STAYS, as a mirror of the linked corporate's name. The
billing PDF, the counterparty directory, the search filter and the statement
panels all read a party's company as a string and none of them can join;
api/v1/customers.py rewrites it on every link/unlink and api/v1/corporates.py
rewrites it for every employee when a corporate is renamed.

THE BACKFILL links what can be matched with certainty: an existing free-text
company that equals a corporate's name exactly, ignoring case and surrounding
whitespace, within the same workspace AND the same owner (both tables are scoped
by tenant_id + created_by_id, so a name is only unique inside that pair).
Anything fuzzier is left unlinked and stays free text — a wrong link here would
silently move someone's tickets onto another company's invoice, which is worse
than an unlinked row a human can fix in the form.

Revision ID: corp_link_01
Revises: corp_entity_01
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "corp_link_01"
down_revision: Union[str, None] = "corp_entity_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("corporate_id", sa.Integer(), nullable=True))
    op.create_index("ix_customers_corporate_id", "customers", ["corporate_id"])
    op.create_foreign_key(
        "fk_customers_corporate_id_corporates",
        "customers", "corporates",
        ["corporate_id"], ["id"],
        ondelete="SET NULL",
    )

    # Exact, case-insensitive name match within one owner's scope. The subquery
    # picks MIN(id) so a workspace that somehow holds two corporates of the same
    # name resolves to one deterministically instead of failing the UPDATE.
    op.execute(
        """
        UPDATE customers c
           SET corporate_id = (
                 SELECT MIN(k.id) FROM corporates k
                  WHERE LOWER(TRIM(k.company)) = LOWER(TRIM(c.company))
                    AND k.created_by_id = c.created_by_id
                    AND (k.tenant_id = c.tenant_id
                         OR (k.tenant_id IS NULL AND c.tenant_id IS NULL))
               )
         WHERE c.company IS NOT NULL AND TRIM(c.company) <> ''
        """
    )

    # Where a link was made, the corporate's spelling of its own name is the one
    # that counts — that is what the mirror means.
    op.execute(
        """
        UPDATE customers c
           SET company = k.company
          FROM corporates k
         WHERE c.corporate_id = k.id
        """
    )


def downgrade() -> None:
    # `company` already holds the corporate's name for every linked row, so
    # dropping the link loses the id, not the employer.
    op.drop_constraint("fk_customers_corporate_id_corporates", "customers", type_="foreignkey")
    op.drop_index("ix_customers_corporate_id", table_name="customers")
    op.drop_column("customers", "corporate_id")
