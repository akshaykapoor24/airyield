"""Commission income, for every kind of statement.

`services/bsp_commission.py` remains the BSP engine and is untouched: it is the only
implementation that has ever run against real settlement data, the whole BSP screen reads
its fifteen roll-up columns, and there is no user-visible benefit to moving it. What the
two share now lives in `services/commission_core.py`, imported by both.

This package is the runner for the sources that had none — third-party GDS/LCC today, LCC
Detailed next. Adding one means writing an adapter and registering it here; nothing else
in the pipeline, the API or the frontend needs to know it exists.
"""
from app.models.commission_run import (
    SOURCE_BSP, SOURCE_LCC_DETAILED, SOURCE_TP_GDS, SOURCE_TP_LCC,
)
from app.services.commission.calc_row import BatchInfo, CalcRow, DeclaredAmounts
from app.services.commission.lcc_detailed import LccDetailedAdapter
from app.services.commission.runner import CommissionRunner
from app.services.commission.third_party import ThirdPartyAdapter

# Every source the vendor-commission API can run, keyed by the slug that appears in its
# URL. The statement slug wherever one exists, so a reader never has to translate between
# two vocabularies.
ADAPTERS = {
    SOURCE_TP_GDS: ThirdPartyAdapter(SOURCE_TP_GDS, "Third Party · GDS"),
    SOURCE_TP_LCC: ThirdPartyAdapter(SOURCE_TP_LCC, "Third Party · LCC"),
    SOURCE_LCC_DETAILED: LccDetailedAdapter(),
}

__all__ = [
    "ADAPTERS",
    "BatchInfo",
    "CalcRow",
    "LccDetailedAdapter",
    "CommissionRunner",
    "DeclaredAmounts",
    "ThirdPartyAdapter",
    "get_adapter",
]


def get_adapter(source: str):
    """The adapter for a source slug, or None. Callers 404 on None, like `_resolve` does
    for an unknown statement slug."""
    return ADAPTERS.get((source or "").lower())
