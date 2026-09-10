"""An LCC Detailed upload can carry two source files, merged on PNR at ingest.

Air India Express issues the same statement as an account file (money movements, GST
party, payment method) plus a passenger file (passengers, sectors, fare breakdown),
joined on `PNR` <-> `RecordLocator`. Neither is usable alone. This adds:

  * `lcc_detailed_batch_file` — one row per source file, each with its OWN header row
    and column map, because the two files share no headers. See
    models/lcc_detailed_batch_file.py.
  * Account-statement columns on `lcc_detailed` — the facts an IndiGo detailed export
    has no column for (transaction type, parent PNR, the GST trio, note, fee/SSR
    codes, foreign currency, pax type), plus the two derived discriminators
    `row_kind` and `movement_kind`.
  * Merge bookkeeping on `lcc_detailed_batch` — `source_rows` (lines read, as opposed
    to `total_rows` = rows written, which a merge makes smaller), `merge_stats` and
    `merge_version`.

`lcc_detailed_batch.file_url / header_row / column_map` are deliberately NOT dropped:
they stay pointed at the primary file, so every batch uploaded before this, plus
/file-url, /viewer-url and the batches list, keep working untouched. The backfill below
gives each of those batches a one-file set so nothing reads as fileless.

Every added column is nullable with no default, so on PostgreSQL 11+ each ALTER is a
catalogue-only change — no table rewrite even on a large `lcc_detailed`.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this uses a
descriptive one, matching the `<feature>_<NN>` convention the recent migrations use.

Revision ID: lcc_ix_merge_01
Revises: ndc_billing_01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "lcc_ix_merge_01"
down_revision = "ndc_billing_01"
branch_labels = None
depends_on = None


# (name, type) — the account-statement columns added to `lcc_detailed`.
# Widths are sized against real AIX values and matter: services/lcc_detailed_spec.py
# `_coerce` TRUNCATES silently rather than raising, so a short column loses data
# without a word. `gst_number` holds a 15-char GSTIN; `fee_code` / `ssr_code` hold
# comma-joined lists such as "SEAT,VFPF"; `transaction_type` holds
# "PPAccountDebitForPayment" (24).
_ROW_COLUMNS = [
    ("transaction_type",       sa.String(length=60)),
    ("parent_pnr",             sa.String(length=20)),
    ("account_transaction_id", sa.String(length=40)),
    ("note",                   sa.String(length=500)),
    ("gst_company_name",       sa.String(length=255)),
    ("gst_number",             sa.String(length=20)),
    ("gst_email",              sa.String(length=255)),
    ("fee_code",               sa.String(length=120)),
    ("ssr_code",               sa.String(length=120)),
    ("foreign_currency_code",  sa.String(length=8)),
    ("pax_type",               sa.String(length=8)),
    ("row_kind",               sa.String(length=12)),
    ("movement_kind",          sa.String(length=24)),
]

_BATCH_COLUMNS = [
    ("source_rows",   sa.Integer()),
    ("merge_stats",   postgresql.JSONB(astext_type=sa.Text())),
    ("merge_version", sa.SmallInteger()),
]


def upgrade() -> None:
    op.create_table(
        "lcc_detailed_batch_file",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id", sa.String(length=100),
            sa.ForeignKey("lcc_detailed_batch.batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # single | account | pax
        sa.Column("role", sa.String(length=12), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("file_url", sa.String(length=1000), nullable=True),
        sa.Column("header_row", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("column_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("xls_columns", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        # At most one file per role per batch — this is what turns "the user dropped
        # two account files" into a 400 rather than a half-ingested batch.
        sa.UniqueConstraint("batch_id", "role", name="uq_lcc_detailed_batch_file_role"),
    )
    op.create_index(
        "ix_lcc_detailed_batch_file_batch_id", "lcc_detailed_batch_file", ["batch_id"]
    )

    for name, type_ in _ROW_COLUMNS:
        op.add_column("lcc_detailed", sa.Column(name, type_, nullable=True))
    for name, type_ in _BATCH_COLUMNS:
        op.add_column("lcc_detailed_batch", sa.Column(name, type_, nullable=True))

    # Indexed because the billing resolver looks a party up by GSTIN per row, and the
    # drill-in offers both as filters. Partial: the columns are NULL on every
    # single-file (IndiGo) batch, and there is no point indexing those.
    op.create_index(
        "ix_lcc_detailed_gst_number", "lcc_detailed", ["gst_number"],
        postgresql_where=sa.text("gst_number IS NOT NULL"),
    )
    op.create_index(
        "ix_lcc_detailed_parent_pnr", "lcc_detailed", ["parent_pnr"],
        postgresql_where=sa.text("parent_pnr IS NOT NULL"),
    )

    # Every batch uploaded before this becomes a one-file set, so the new table is
    # never emptier than the columns it supersedes. `header_row` is NOT NULL on the
    # batch, but COALESCE anyway — the target column is NOT NULL too.
    op.execute(
        """
        INSERT INTO lcc_detailed_batch_file
            (batch_id, role, source_file, file_url, header_row, column_map)
        SELECT batch_id, 'single', source_file, file_url,
               COALESCE(header_row, 0), column_map
        FROM lcc_detailed_batch
        ON CONFLICT DO NOTHING
        """
    )
    # Rows written == lines read for every pre-existing single-file batch, so the
    # wizard's "expected records" check keeps comparing against the same number it
    # always did.
    op.execute("UPDATE lcc_detailed_batch SET source_rows = total_rows")


def downgrade() -> None:
    op.drop_index("ix_lcc_detailed_parent_pnr", table_name="lcc_detailed")
    op.drop_index("ix_lcc_detailed_gst_number", table_name="lcc_detailed")
    for name, _ in reversed(_BATCH_COLUMNS):
        op.drop_column("lcc_detailed_batch", name)
    for name, _ in reversed(_ROW_COLUMNS):
        op.drop_column("lcc_detailed", name)
    op.drop_index("ix_lcc_detailed_batch_file_batch_id", table_name="lcc_detailed_batch_file")
    op.drop_table("lcc_detailed_batch_file")
