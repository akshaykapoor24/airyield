"""The income board's projection layer.

`income_board_rows` is a projection of every vendor statement line — the ones the
commission engines have priced and the ones nobody has costed yet. Everything public is
here; the arms and the vocabulary mapping live beside it.

See models/income_board.py for the seven invariants the table enforces, and project.py
for why re-projection is delete-and-sweep rather than a plain upsert.

COMMISSION_SOURCES vs PROJECTED_SOURCES is a distinction worth keeping straight. The
first is "has a commission adapter"; the second is "this module knows how to project
it". NDC and Third Party API are in the second and not the first — they carry sale and
no adapter prices them — and conflating the two would have the freshness check hunt for
commission runs that can never exist.
"""
from app.services.income_board.dimensions import (
    classify_txn, counts_in_net_sql, normalise_bsp_segment, normalise_segment,
)
from app.services.income_board.hooks import forget, refresh
from app.services.income_board.overlap import stamp_bsp_ndc_overlap
from app.services.income_board.project import (
    COMMISSION_SOURCES, PROJECTED_SOURCES, clear_batch, project_batch,
)

__all__ = [
    # What an ingest path calls. Prefer these over project_batch/clear_batch: they are
    # best-effort, and they re-run the NDC/BSP overlap when the source can have moved it.
    "refresh",
    "forget",
    "project_batch",
    "clear_batch",
    "stamp_bsp_ndc_overlap",
    "COMMISSION_SOURCES",
    "PROJECTED_SOURCES",
    "classify_txn",
    "counts_in_net_sql",
    "normalise_segment",
    "normalise_bsp_segment",
]
