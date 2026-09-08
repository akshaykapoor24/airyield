"""A third-party statement upload declares which consolidator sent it.

A consolidator's GDS/LCC export never names its sender — the sample export's "Customer
Name" column is the tenant's OWN name, as the consolidator's customer — so the uploader
declares it from their Agency Master, exactly as an LCC upload declares its carrier. This
is what `services/deal_matching.py`'s B2B supplier guard matches against; without it every
third-party row comes back unmatched.

UNIQUE ON (slug, batch_id), unlike `statement_batch_airline_ids`' triple: one upload can
cover several airline ids, but a statement comes from exactly one consolidator, and
"several" would mean the commission run had to guess which deal applied.

The `agency_name` / `agency_branch` / `agency_channel` snapshot is deliberate. With
ON DELETE CASCADE on agency_id, deleting an agency would otherwise erase who every
commission figure from its statements was earned from — the batch would silently become
un-attributed rather than say who it used to belong to. The channel is part of the
snapshot because one vendor working both channels is TWO agency rows with the SAME name
(see models/agency.py), so the name alone does not identify the row.

Nothing is backfilled: third-party uploads made before this exist without a declared
consolidator, and guessing one would be inventing data — the file offers no candidate.
They read as "—" until re-uploaded.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this uses a
descriptive one, matching the `<feature>_<NN>` convention the recent migrations use.

Revision ID: stmt_batch_agency_01
Revises: stmt_batch_airlines_01
"""
from alembic import op
import sqlalchemy as sa


revision = "stmt_batch_agency_01"
down_revision = "stmt_batch_airlines_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_batch_agencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        ),
        # The statement type; batch_id has no FK because these types keep no batch header
        # row — a batch is a shared batch_id across the type's rows table.
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        # CASCADE, not RESTRICT — a RESTRICT here would let these rows block the
        # workspace-deletion group that owns `agencies`. The in-use guard on
        # DELETE /agencies/{id} is what actually protects the user, and the snapshot
        # columns below are what keep the provenance readable if it ever does cascade.
        sa.Column(
            "agency_id", sa.Integer(),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("agency_name", sa.String(length=255), nullable=True),
        sa.Column("agency_channel", sa.String(length=10), nullable=True),
        sa.Column("agency_branch", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("slug", "batch_id", name="uq_statement_batch_agencies_batch"),
    )
    op.create_index("ix_statement_batch_agencies_tenant_id", "statement_batch_agencies", ["tenant_id"])
    op.create_index("ix_statement_batch_agencies_agency_id", "statement_batch_agencies", ["agency_id"])
    op.create_index("ix_statement_batch_agencies_batch", "statement_batch_agencies", ["slug", "batch_id"])


def downgrade() -> None:
    op.drop_index("ix_statement_batch_agencies_batch", table_name="statement_batch_agencies")
    op.drop_index("ix_statement_batch_agencies_agency_id", table_name="statement_batch_agencies")
    op.drop_index("ix_statement_batch_agencies_tenant_id", table_name="statement_batch_agencies")
    op.drop_table("statement_batch_agencies")
