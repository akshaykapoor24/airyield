"""Give an agency a branch and commercial terms

Two gaps closed at once, both surfacing in the Add Agency modal.

BRANCH. A vendor can exist as several rows in the global suppliers master, one
per branch: "Air India Limited" is three rows (Delhi / Mumbai / Kolkata) and
"Riya Travel & Tours (India) Private Limited" is fourteen. Until now the picker
showed them as identical-looking options and copied neither city nor region, so
which branch you onboarded was unrecoverable. `city` and `region_chapter` are
copied at add-time like every other supplier field — still no foreign key back
to suppliers, so editing a supplier later does not rewrite an agency.

Note what this migration deliberately does NOT do: it leaves
`uq_agencies_user_name` alone. A branch selects WHOSE DETAILS TO COPY; it does
not create a second agency. That matters more than it looks. Agency Billing
resolves an agency's tickets with
`lower(trim(ticket_statements.agency)) == agencies.name`, and ticket statements
record only the bare vendor name — so three agencies all named "Air India
Limited" would every one of them match the same tickets, and whichever billed
first would silently steal them (uploaded_tickets.billing_id is a single FK).
The same trap sits in the `agency_lookup` dicts in agency_entities.py and
agency_login_ids.py, which key by lower-cased name. Keep names unique per user
and none of it can fire.

TERMS. `agency_type` is how the agency pays:
  cash   — pays first. `deposit_amount` is the money in, and `credit_limit` is
           forced equal to it by the API (the "deposit == limit" rule lives in
           agencies._normalise_terms, not just in the form). `usage_percent` is
           the notification threshold and MAY EXCEED 100 — 110 means "warn once
           they are 10% past the deposit", so no CHECK constraint caps it at 100.
  credit — invoiced on `billing_cycle`. `deposit_amount` and `usage_percent` are
           forced NULL; the limit stands on its own.
Nothing consumes these yet: no job measures usage and none generates invoices.
They are the configuration a later notification/invoicing job will read.

`credit_limit` carries the usable limit for BOTH types precisely so that job can
read one column and ignore the type.

WIDENING contact_phone AND contact_email IS NOT COSMETIC. The supplier columns
that actually hold contact data are `telephone_mobile` and `email_address` —
`suppliers.contact_phone`/`contact_email` are empty on all 2,480 rows, which is
why the old copy silently filled nothing. Of the real phone strings, 1,132 (46%)
are longer than 50 characters and the longest is 134 ("(T)+91-80-23225538 /
23220031 / ... (M)+91-9972200550"). Copying those into String(50) raises
`value too long for type character varying(50)`, so the auto-fill fix in
agencies._from_supplier is unusable without this. Three emails exceed 255, hence
Text rather than a bigger String.

DROPPING vendor_type DESTROYS DATA. It was free text copied from a supplier
column that is empty everywhere, so in practice it only ever held hand-entered
values. At the time of writing that was four rows, all
'Travel Agency / Sub-agent*' (agencies 5, 6, 7, 8; agency 9 was NULL). It is
replaced by the structured `agency_type`. The two are not convertible — a
sub-agent may pay cash or credit — so there is no backfill.

Revision ID: agency_terms_01
Revises: tenant_subscription_01
Create Date: 2026-08-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_terms_01"
down_revision: Union[str, None] = "tenant_subscription_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Branch snapshot, copied from the picked supplier row.
    op.add_column("agencies", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("agencies", sa.Column("region_chapter", sa.Text(), nullable=True))

    # Commercial terms. All nullable — existing agencies simply have none yet.
    op.add_column("agencies", sa.Column("agency_type", sa.String(length=10), nullable=True))
    op.add_column("agencies", sa.Column("credit_limit", sa.Numeric(14, 2), nullable=True))
    op.add_column("agencies", sa.Column("deposit_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("agencies", sa.Column("usage_percent", sa.Numeric(6, 2), nullable=True))
    op.add_column("agencies", sa.Column("billing_cycle", sa.String(length=20), nullable=True))

    # See the note above — 46% of supplier phone strings overflow String(50).
    op.alter_column(
        "agencies", "contact_phone",
        existing_type=sa.String(length=50), type_=sa.String(length=255), existing_nullable=True,
    )
    op.alter_column(
        "agencies", "contact_email",
        existing_type=sa.String(length=255), type_=sa.Text(), existing_nullable=True,
    )

    op.drop_column("agencies", "vendor_type")


def downgrade() -> None:
    # This DELETES every agency's commercial terms and its branch city/region.
    # Export them first if you intend to upgrade again:
    #   SELECT id, name, city, region_chapter, agency_type, credit_limit,
    #          deposit_amount, usage_percent, billing_cycle FROM agencies;
    # Re-adding vendor_type below restores the COLUMN, never its values — those
    # were dropped on upgrade and are listed in the docstring above.
    op.add_column("agencies", sa.Column("vendor_type", sa.String(length=100), nullable=True))

    # Narrowing these back TRUNCATES: any contact_phone over 50 chars or
    # contact_email over 255 will fail the cast rather than silently cut, so
    # clear or shorten those rows before running this.
    op.alter_column(
        "agencies", "contact_email",
        existing_type=sa.Text(), type_=sa.String(length=255), existing_nullable=True,
    )
    op.alter_column(
        "agencies", "contact_phone",
        existing_type=sa.String(length=255), type_=sa.String(length=50), existing_nullable=True,
    )

    op.drop_column("agencies", "billing_cycle")
    op.drop_column("agencies", "usage_percent")
    op.drop_column("agencies", "deposit_amount")
    op.drop_column("agencies", "credit_limit")
    op.drop_column("agencies", "agency_type")
    op.drop_column("agencies", "region_chapter")
    op.drop_column("agencies", "city")
