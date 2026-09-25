"""Commission income, for every kind of statement.

`services/bsp_commission.py` remains the BSP engine and is untouched: it is the only
implementation that has ever run against real settlement data, the whole BSP screen reads
its fifteen roll-up columns, and there is no user-visible benefit to moving it. What the
two share now lives in `services/commission_core.py`, imported by both.

This package is the runner for every source that is not BSP: third-party GDS, LCC and API,
LCC Detailed, and NDC. Adding one means writing an adapter and registering it here; nothing
else in the pipeline, the API or the frontend needs to know it exists.

TWO OF THESE PRICE SOMETHING THE OTHERS CANNOT, and both are worth knowing before reading
the adapters:

  * **NDC** is the airline's own sales export, so it is the only source that splits an
    ancillary by sub-type — a paid seat is its own line and says so. Everything else prints
    one combined SSR figure and must claim nothing for it.
  * **Third Party API** is the only MULTI-PRODUCT source. One aggregator file carries
    hotel, flight, train, bus and car bookings, and only the flight rows have an airline
    deal to price against. The rest are returned as skips naming their product rather than
    filtered out, so the grid still reconciles to the file.
"""
from app.models.commission_run import (
    SOURCE_BSP, SOURCE_LCC_DETAILED, SOURCE_NDC, SOURCE_TP_API, SOURCE_TP_GDS,
    SOURCE_TP_LCC,
)
from app.services.commission.calc_row import BatchInfo, CalcRow, DeclaredAmounts
from app.services.commission.lcc_detailed import LccDetailedAdapter
from app.services.commission.ndc import NdcAdapter
from app.services.commission.runner import CommissionRunner
from app.services.commission.third_party import ThirdPartyAdapter
from app.services.commission.tp_api import TpApiAdapter

# Every source the vendor-commission API can run, keyed by the slug that appears in its
# URL. The statement slug wherever one exists, so a reader never has to translate between
# two vocabularies.
ADAPTERS = {
    SOURCE_TP_GDS: ThirdPartyAdapter(SOURCE_TP_GDS, "Third Party · GDS"),
    SOURCE_TP_LCC: ThirdPartyAdapter(SOURCE_TP_LCC, "Third Party · LCC"),
    SOURCE_TP_API: TpApiAdapter(),
    SOURCE_LCC_DETAILED: LccDetailedAdapter(),
    SOURCE_NDC: NdcAdapter(),
}

__all__ = [
    "ADAPTERS",
    "BatchInfo",
    "CalcRow",
    "LccDetailedAdapter",
    "CommissionRunner",
    "DeclaredAmounts",
    "NdcAdapter",
    "ThirdPartyAdapter",
    "TpApiAdapter",
    "get_adapter",
]


def get_adapter(source: str):
    """The adapter for a source slug, or None. Callers 404 on None, like `_resolve` does
    for an unknown statement slug."""
    return ADAPTERS.get((source or "").lower())
