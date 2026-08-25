"""Outgoing deal scope — who a floated deal is for

An outgoing deal used to name its counterparty only through the free-text
`supplier_name`, typed into a SUPPLIER-master search box. That cannot express
"every agency", cannot express a corporate at all, and cannot be joined back to
the party when a ticket is priced. This adds the scope as real foreign keys.

ONE COLUMN, FIVE VALUES, rather than a scope plus a customer-types array:

    agency         → this one agency          (agency_id set)
    agency_all     → every agency
    corporate      → this one corporate       (corporate_id set)
    corporate_all  → every corporate
    all            → every customer, of any kind

The commission engine then asks one indexable question — for a ticket sold to a
party of kind k with id p:

    scope_type IN ('all', k, k || '_all')
    AND (agency_id IS NULL OR agency_id = :p)
    AND (corporate_id IS NULL OR corporate_id = :p)

INBOUND DEALS ARE ALWAYS 'all'. An incoming deal is income received from an
airline or supplier; it has no customer, so the scope is not meaningful there and
the API forces this value.

ON DELETE RESTRICT, NOT SET NULL, and that is not a preference. With SET NULL,
deleting an agency would null `agency_id` and Postgres would then re-evaluate
ck_deals_scope_agency on the mutated row, which fails — so DELETE /agencies/{id}
would abort with a CheckViolation naming `deals`. RESTRICT lets the endpoint
raise a readable 409 instead ("named on N outgoing deals").

`agency_id` / `corporate_id` are Integer, NOT BigInteger: `agencies.id` and
`corporates.id` are bare `mapped_column(primary_key=True)` (Integer), unlike
`deals.id`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cust_scope_01"
down_revision: Union[str, None] = "cust_deal_widen_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCOPE_VALUES = ("agency", "agency_all", "corporate", "corporate_all", "all")


def upgrade() -> None:
    # server_default matters twice over: it keeps every pre-existing row valid the
    # instant the NOT NULL column exists, and it lets this backend deploy ahead of
    # the frontend (and covers /upload/ai-confirm, a writer that sets no scope).
    op.add_column("deals", sa.Column(
        "scope_type", sa.String(20), nullable=False, server_default="all",
    ))
    op.add_column("deals", sa.Column("agency_id", sa.Integer(), nullable=True))
    op.add_column("deals", sa.Column("corporate_id", sa.Integer(), nullable=True))
    op.add_column("deals", sa.Column("agency_entity_id", sa.Integer(), nullable=True))
    # Display snapshot, so the repository still reads correctly after the party is
    # renamed in its master — and so a row remains legible if the party is removed.
    op.add_column("deals", sa.Column("scope_party_name", sa.String(255), nullable=True))

    # Every existing deal predates the scope. 'all' is the only value that can be
    # true of them: outgoing deals so far name a supplier string with no agency row
    # behind it, so 'agency' would fail the check below.
    op.execute("UPDATE deals SET scope_type = 'all' WHERE scope_type IS NULL")

    op.create_foreign_key(
        "fk_deals_agency_id", "deals", "agencies",
        ["agency_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_deals_corporate_id", "deals", "corporates",
        ["corporate_id"], ["id"], ondelete="RESTRICT",
    )
    # SET NULL is safe here: no check depends on agency_entity_id being present.
    op.create_foreign_key(
        "fk_deals_agency_entity_id", "deals", "agency_entities",
        ["agency_entity_id"], ["id"], ondelete="SET NULL",
    )

    op.create_index("ix_deals_agency_id", "deals", ["agency_id"])
    op.create_index("ix_deals_corporate_id", "deals", ["corporate_id"])

    # Created AFTER the backfill. The "=" between two booleans enforces both
    # directions at once: the id is present exactly when the scope calls for it,
    # and absent otherwise.
    vals = ", ".join(f"'{v}'" for v in SCOPE_VALUES)
    op.create_check_constraint("ck_deals_scope_type", "deals", f"scope_type IN ({vals})")
    op.create_check_constraint(
        "ck_deals_scope_agency", "deals",
        "(scope_type = 'agency') = (agency_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_deals_scope_corporate", "deals",
        "(scope_type = 'corporate') = (corporate_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_deals_scope_entity", "deals",
        "agency_entity_id IS NULL OR scope_type = 'agency'",
    )


def downgrade() -> None:
    for name in (
        "ck_deals_scope_entity",
        "ck_deals_scope_corporate",
        "ck_deals_scope_agency",
        "ck_deals_scope_type",
    ):
        op.drop_constraint(name, "deals", type_="check")

    op.drop_index("ix_deals_corporate_id", table_name="deals")
    op.drop_index("ix_deals_agency_id", table_name="deals")

    for name in ("fk_deals_agency_entity_id", "fk_deals_corporate_id", "fk_deals_agency_id"):
        op.drop_constraint(name, "deals", type_="foreignkey")

    for col in ("scope_party_name", "agency_entity_id", "corporate_id", "agency_id", "scope_type"):
        op.drop_column("deals", col)
