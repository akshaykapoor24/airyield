"""A corporate is an organisation, not a person

`corporates` was created as a byte-for-byte copy of `customers`, and a customer
IS a person: first_name / last_name / title, with `company` an optional aside.
That is the wrong shape for a corporate. An organisation has a legal form
(proprietorship, private limited, LLP…) and a registered address, and it has no
first name at all.

WHAT CHANGES

    company          becomes THE name — required by the API from here on
    corporate_type   new; the legal form, one of the slugs in
                     api/v1/corporates.py:_CORPORATE_TYPES
    address / city / state / pincode / country
                     new; the registered address. Named to match
                     agencies.address / state / city so the two read alike.
    first_name       becomes NULLABLE, and nothing writes it any more

THE BACKFILL. Existing rows keep their name: wherever `company` is blank, the
person name it was stored under moves into it, so no corporate loses its label
in the directory, on a deal, or on a billing PDF. Rows that already had a
`company` are left exactly as they are — their person columns stay put and are
still read as the contact name.

first_name / last_name / title ARE NOT DROPPED. The sold-tickets endpoint matches
a corporate to its tickets by passenger name, and for pre-split rows that match is
the only one there is; dropping the columns would silently empty those billings.
They are legacy-read-only from here, and the customer↔corporate link is what
replaces them.

Revision ID: corp_entity_01
Revises: iata_commission_approvals_01
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "corp_entity_01"
down_revision: Union[str, None] = "iata_commission_approvals_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("corporates", sa.Column("corporate_type", sa.String(length=50), nullable=True))
    op.add_column("corporates", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("corporates", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("corporates", sa.Column("state", sa.String(length=100), nullable=True))
    op.add_column("corporates", sa.Column("pincode", sa.String(length=20), nullable=True))
    op.add_column("corporates", sa.Column("country", sa.String(length=100), nullable=True))

    # Give every row a name in `company` before the API starts requiring one.
    op.execute(
        """
        UPDATE corporates
           SET company = NULLIF(TRIM(CONCAT_WS(' ', first_name, last_name)), '')
         WHERE company IS NULL OR TRIM(company) = ''
        """
    )

    op.alter_column("corporates", "first_name", existing_type=sa.String(length=200), nullable=True)


def downgrade() -> None:
    # first_name goes back to NOT NULL, so anything added since the split — which
    # has no person name — needs one. The company name is the only truthful
    # value available.
    op.execute("UPDATE corporates SET first_name = company WHERE first_name IS NULL OR TRIM(first_name) = ''")
    op.execute("UPDATE corporates SET first_name = 'Corporate' WHERE first_name IS NULL OR TRIM(first_name) = ''")
    op.alter_column("corporates", "first_name", existing_type=sa.String(length=200), nullable=False)

    op.drop_column("corporates", "country")
    op.drop_column("corporates", "pincode")
    op.drop_column("corporates", "state")
    op.drop_column("corporates", "city")
    op.drop_column("corporates", "address")
    op.drop_column("corporates", "corporate_type")
