"""The income board's projection layer.

`income_board_rows` is a projection of work the commission engines have already done.
Everything public is here; the arms and the vocabulary mapping live beside it.

See models/income_board.py for the five invariants the table enforces, and
project.py for why re-projection is delete-and-sweep rather than a plain upsert.
"""
from app.services.income_board.dimensions import (
    classify_txn, normalise_bsp_segment, normalise_segment,
)
from app.services.income_board.project import (
    COMMISSION_SOURCES, clear_batch, project_batch,
)

__all__ = [
    "project_batch",
    "clear_batch",
    "COMMISSION_SOURCES",
    "classify_txn",
    "normalise_segment",
    "normalise_bsp_segment",
]
