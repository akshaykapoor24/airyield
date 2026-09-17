"""The one shape every vendor statement is reduced to before it meets the sell side.

Every source says the same handful of things in a different vocabulary — a consolidator's
GDS export prints `base_fare` as a string inside a JSONB blob, an LCC Detailed row has a
typed `base_fare` column, an NDC line calls it `basic_fare`. Normalising here is what keeps
`services/sell_reconciliation.py` from growing a branch per source, and it is the same
discipline `commission/calc_row.CalcRow` applies to the pricing engine.

HOW A ROW FINDS ITS SALE, in priority order. The adapter decides which of these it can
offer; the engine decides what to do with them:

  1. `projected_ticket_id` — an actual foreign key to `uploaded_tickets`. NDC and LCC
     Detailed have one because their rows were PROJECTED into tickets for billing
     (services/ndc_billing_projection.py). Authoritative: no matching required, and no
     chance of being wrong.
  2. `ticket_key` — the normalised DOCUMENT SERIAL, and `ticket_prefix` beside it.

THE SERIAL AND THE PREFIX ARE SEPARATE, AND BOTH MATTER. Every table that holds a ticket
now stores the airline's 3-digit IATA accounting code apart from the 10-digit serial —
`third_party_gds` always did, BSP settlement rows carry the bare serial, and
`uploaded_tickets` was split to match (migration tkt_prefix_01). So the join is
serial-to-serial and exact.

The prefix is then the DISAMBIGUATOR, not part of the key. A serial is unique only WITHIN
an airline: this workspace's own data contains Iberia 075-5808758877 and British Airways
125-5808758877, one serial under two carriers. Matching on the serial finds the pair;
comparing the prefixes is what stops it being reported as the same ticket. Folding the
prefix into the key instead would hide that collision rather than surface it, and would
also miss every row where one of the two documents omits the code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

# Every money field the engine compares. A source that does not print one leaves it None,
# which the engine reports as "not comparable" rather than as zero — see `_compare`.
MONEY_FIELDS = ("fare", "yq", "yr", "tax", "gross", "commission", "net")


def to_decimal(v) -> Decimal | None:
    """A statement cell to Decimal, or None when it is not a number.

    Never float: `flat_statement.to_number_str` deliberately stores amounts as STRINGS
    because "a float round-trip loses paise", and parsing them back through float here
    would undo exactly that.
    """
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass
class BuyRow:
    """One vendor statement row, normalised. What the agency PAID for this ticket."""

    source_row_id: int
    batch_id: str | None = None

    # ── how it finds its sale (see the module docstring) ─────────────────────
    projected_ticket_id: int | None = None
    # The normalised document serial. The join key.
    ticket_key: str | None = None
    # The airline accounting code, or None when the document omits it. NOT part of the
    # key — it is what a match is checked AGAINST once the serial has found one.
    ticket_prefix: str | None = None

    # ── identity, for the grid and the drilldown ─────────────────────────────
    ticket_number: str | None = None
    airline_name: str | None = None
    airline_code: str | None = None
    issue_date: date | None = None
    pax_name: str | None = None
    sector: str | None = None

    # ── money ────────────────────────────────────────────────────────────────
    amounts: dict[str, Decimal | None] = field(default_factory=dict)

    # Anything the adapter wants the drilldown to say about this row — a missing column,
    # an unparseable amount. Surfaced verbatim, never swallowed.
    notes: list[str] = field(default_factory=list)

    def amount(self, key: str) -> Decimal | None:
        return self.amounts.get(key)


@runtime_checkable
class BuySideAdapter(Protocol):
    """What a source must provide to be reconcilable.

    A real Protocol rather than the duck-typing `services/commission/__init__.py` settled
    for: that contract is discovered only by reading two implementations plus every
    `getattr(adapter, ..., default)` in the router, and a fifth source added next year
    would find out what it must implement by crashing.
    """

    source: str          # the statement slug — 'tp-gds' | 'tp-lcc' | 'ndc' | 'lcc-detailed'
    label: str           # human name, used in 404 copy and empty states
    # False when the source prints no ticket number at all, so the screen can say WHY a
    # tab is empty instead of implying nothing was bought.
    joins_by_ticket: bool

    async def load_buy_rows(
        self, db: AsyncSession, tenant_id: int, user_id: int,
        batch_id: str | None = None,
    ) -> list[BuyRow]:
        ...

    async def list_batches(
        self, db: AsyncSession, tenant_id: int, user_id: int,
    ) -> list[dict]:
        """`[{batch_id, source_file, row_count}]` — the statement filter's options."""
        ...
