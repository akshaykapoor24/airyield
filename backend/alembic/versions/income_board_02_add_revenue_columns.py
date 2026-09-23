"""Widen income_board_rows from "every priced line" to "every statement line"

WHY. `/dashboard/revenue` has to answer "how much did we sell", and the answer lives in
twelve statement types of which this table held four — and held those four only where a
commission run had already priced them. A statement uploaded and never costed read as
zero sale, which on a dashboard looks like no business rather than like no pricing.

Rather than fork a second projection over the same source rows, this migration widens
the one that exists. Two projections would mean two hook sets, two freshness stories and
two definitions of `gross_amount` for the identical row — and the first time a
carrier-resolution rule is fixed in one and not the other, the two tabs disagree about
an airline and nobody can say which is right. That split is precisely what this table
was created to remove; recreating it one level up would be the same mistake.

WHAT THE NEW COLUMNS ARE FOR

  priced               Has the commission engine seen this row? A third state, distinct
                       from 'unmatched' (ran, matched nothing) and from a confirmed
                       zero. DEFAULT FALSE on purpose — an arm that forgets to set it
                       fails closed, staying out of the Commission income tab rather
                       than silently entering it.
  counts_in_net        May this row enter a sale total? Per row, not per source: an LCC
                       payment movement, a cancelled aggregator booking and the
                       statement's own footer line sit beside real sales in one table.
  counts_in_net_reason Which rule excluded it — the NET_* vocabulary from
                       services/report_download/columns.py, so this board and the
                       downloadable report say the same words for the same row.
  incentive_breakdown  {incentive_type: amount}, so PLB-per-airline is a GROUP BY.
  product              Air | Hotel | Train | Bus | Car. Third Party API is the only
                       multi-product source and a hotel night has no carrier.
  currency             Totals are per currency and are never converted or added across
                       them (services/report_download/summary.py). Without the column a
                       board cannot honour that, and the failure is silent.
  doc_code/doc_serial  The document identity WITH leading zeros kept, for the
                       NDC-settled-through-BSP test. `ticket_key` strips them, which is
                       harmless for the BSP-to-internal-ticket join it was built for and
                       wrong here: "098 0123456789" and "098 123456789" are different
                       documents.

THE INDEXES BECOME PARTIAL, and that is the point of doing it now rather than later.
The table roughly doubles once unpriced statements land in it. Every existing index
exists for /dashboard/income, and every read there now carries `priced = TRUE`, so each
one is rebuilt `WHERE priced` rather than growing to cover rows it will never return.
The two new revenue indexes are the mirror image, `WHERE counts_in_net`, and carry no
`created_by_id` because that board defaults to agency scope.

THE TABLE IS TRUNCATED. `source_row_id` changes meaning in the same release — it now
points at the STATEMENT row rather than the calculation row for tp-gds / tp-lcc /
lcc-detailed — so the old rows' conflict keys are meaningless against the new arms.
Every row here is derived and rebuildable, which is the property that makes this cheap:
the cost is one POST /dashboard/income/rebuild, and until someone runs it the freshness
banner says so in as many words. TRUNCATE rather than DELETE because this is a pure
projection with no triggers and no dependents — a DELETE over a multi-million-row table
inside a migration is a long lock and a bloated heap for no benefit.

DOWNGRADE IS LOSSLESS for the same reason. It drops the columns and restores the
non-partial indexes; a rebuild reconstructs everything it discarded.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "income_board_02"
down_revision: Union[str, None] = "income_board_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "income_board_rows"

# (name, columns, postgresql_where). Mirrors models/income_board.py's __table_args__;
# the model is the readable copy and this is the one that runs.
_OLD_INDEXES = (
    ("ix_income_board_airline",
     ["tenant_id", "created_by_id", "direction", "issue_ym", "airline_id"]),
    ("ix_income_board_supplier",
     ["tenant_id", "created_by_id", "direction", "issue_ym", "supplier_id"]),
    ("ix_income_board_travel",
     ["tenant_id", "created_by_id", "direction", "travel_ym"]),
    ("ix_income_board_status",
     ["tenant_id", "created_by_id", "direction", "status"]),
    ("ix_income_board_tenant_airline",
     ["tenant_id", "direction", "issue_ym", "airline_id"]),
    ("ix_income_board_tenant_supplier",
     ["tenant_id", "direction", "issue_ym", "supplier_id"]),
)

_NEW_INDEXES = (
    ("ix_income_board_sale",
     ["tenant_id", "direction", "issue_ym", "source"], "counts_in_net"),
    ("ix_income_board_sale_airline",
     ["tenant_id", "direction", "airline_id", "issue_ym"], "counts_in_net"),
    # Both columns are NULL on a document that cannot be linked, and Postgres leaves
    # NULLs out of the scan, so this is only as big as the rows that can actually match.
    ("ix_income_board_doc", ["tenant_id", "doc_code", "doc_serial"], None),
)

_COLUMNS = (
    sa.Column("priced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("counts_in_net", sa.Boolean(), nullable=False,
              server_default=sa.text("true")),
    sa.Column("counts_in_net_reason", sa.String(60), nullable=True),
    sa.Column("incentive_breakdown", postgresql.JSONB(astext_type=sa.Text()),
              nullable=True),
    sa.Column("product", sa.String(12), nullable=True),
    sa.Column("currency", sa.String(8), nullable=True),
    sa.Column("doc_code", sa.String(3), nullable=True),
    sa.Column("doc_serial", sa.String(10), nullable=True),
)


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column(TABLE, col)

    # Before the indexes are rebuilt: an empty table makes every CREATE INDEX instant,
    # and the rows are about to become unaddressable anyway (see the header on
    # source_row_id). RESTART IDENTITY so a rebuilt board does not start its ids in the
    # millions; CASCADE is deliberately absent — nothing references this table, and if
    # something ever does, the migration should fail rather than empty it too.
    op.execute(f"TRUNCATE TABLE {TABLE} RESTART IDENTITY")

    for name, cols in _OLD_INDEXES:
        op.drop_index(name, table_name=TABLE)
        op.create_index(name, TABLE, cols, postgresql_where=sa.text("priced"))

    for name, cols, where in _NEW_INDEXES:
        op.create_index(name, TABLE, cols,
                        postgresql_where=sa.text(where) if where else None)


def downgrade() -> None:
    for name, _cols, _where in reversed(_NEW_INDEXES):
        op.drop_index(name, table_name=TABLE)

    for name, cols in _OLD_INDEXES:
        op.drop_index(name, table_name=TABLE)
        op.create_index(name, TABLE, cols)

    for col in reversed(_COLUMNS):
        op.drop_column(TABLE, col.name)

    # The 1.0 arms key on the calculation row, so the 2.0 rows cannot be read back.
    # Emptying is the honest end state: a rebuild on the downgraded code refills it.
    op.execute(f"TRUNCATE TABLE {TABLE} RESTART IDENTITY")
