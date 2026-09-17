"""Every source the buy-vs-sell reconciliation can run, keyed by the slug in its URL.

Shaped like `services/commission/__init__.py` on purpose — the statement slug wherever one
exists, so a reader never has to translate between two vocabularies, and `get_adapter`
returns None so the router can 404 exactly as `statements._resolve` does for an unknown
statement slug.

BSP IS DELIBERATELY ABSENT. `/bsp-reconciliation` is a different router with different
storage, asking a different question ("did BSP settle what we expected"), and it is the only
reconciliation engine ever run against real settlement data. It keeps its own API and the
frontend picks a base URL per source tab — the same arrangement `/bsp-commission` has with
`/commission/vendor`, and for the same reasons.
"""
from app.services.reconciliation.adapters import (
    LCC_DETAILED_ADAPTER, NDC_ADAPTER, TP_GDS_ADAPTER, TP_LCC_ADAPTER,
)
from app.services.reconciliation.buy_row import BuyRow, BuySideAdapter, MONEY_FIELDS

ADAPTERS: dict[str, BuySideAdapter] = {
    TP_GDS_ADAPTER.source: TP_GDS_ADAPTER,
    TP_LCC_ADAPTER.source: TP_LCC_ADAPTER,
    NDC_ADAPTER.source: NDC_ADAPTER,
    LCC_DETAILED_ADAPTER.source: LCC_DETAILED_ADAPTER,
}


def get_adapter(source: str):
    """The adapter for a source slug, or None. Callers 404 on None."""
    return ADAPTERS.get((source or "").lower())


__all__ = ["ADAPTERS", "get_adapter", "BuyRow", "BuySideAdapter", "MONEY_FIELDS"]
