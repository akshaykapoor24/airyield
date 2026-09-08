"""One statement row, reduced to what the deal engine actually needs.

Every source document says the same handful of things in a different vocabulary: a BSP
settlement prints STAT and an accounting code, an LCC export prints an `international`
flag and a product class, a consolidator prints "Airline Category" and a ticket prefix.
The engine cares about none of that — it wants an airline, two dates, a segment type, a
class, a fare and a YQ, plus an honest list of what the document could NOT say.

Field names deliberately mirror `services/bsp_commission.BspRowContext` so that
`commission_core.apply_payout_rules` takes either without adaptation, and so anyone who
knows one file can read the other.

THE SKIP SETS ARE PER ROW, NOT PER SOURCE, and that is the whole reason this is a
dataclass rather than a dict of columns. One statement holds a mix — a consolidator prints
Class on some lines and not others — and skipping `class` on a row whose class we actually
know would let an Economy-only deal match a Business ticket. See deal_matching's comment
on SKIP_CLASS: skipping is not passing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# What a row IS, for the transaction-type policy. Named rather than boolean because
# "skip" is a third answer: a cancelled booking is not a sale that earned zero, it is
# not a sale.
KIND_ISSUE = "issue"
KIND_REFUND = "refund"
KIND_SKIP = "skip"


@dataclass
class DeclaredAmounts:
    """What the vendor's own statement says it already paid. Third-party only.

    GROSS OF TDS. The Etihad row of the real export proves it: TDS 5.7144 is exactly 2% of
    commission 285.72, and the statement's Net Amount only reconciles if the commission is
    subtracted and the TDS added back. A deal's rates are gross too, so the variance
    compares like with like — netting the TDS off first would print a phantom 2% shortfall
    on every commission-bearing row.
    """
    commission: float | None = None
    incentive: float | None = None
    tds: float | None = None
    net: float | None = None
    # Did the vendor's own components add up to its own Net Amount?
    #   True  — they did, so a variance against them means something.
    #   False — they did not, and every component needed to check that was present.
    #   None  — they did not, but a column whose SIGN we have never seen in real data was
    #           non-zero. Claiming False there would raise false alarms across a whole file.
    net_ok: bool | None = None

    def any_declared(self) -> bool:
        return any(v is not None for v in (self.commission, self.incentive, self.tds, self.net))


@dataclass
class CalcRow:
    """A normalized statement row. Satisfies commission_core.RowContext structurally."""

    source_row_id: int

    # ── Identity, for the grid, the export and refund matching ───────────────
    document_number: str | None = None
    ticket_number: str | None = None
    pnr: str | None = None
    passenger_name: str | None = None
    transaction_type: str | None = None

    # ── What the deal engine matches on ──────────────────────────────────────
    # The MASTER's spelling of the carrier, never the file's: `deals.airline_name` holds
    # the master's, and the match is a lowercase equality.
    airline_name: str | None = None
    airline_id: int | None = None
    issue_date: date | None = None
    travel_date: date | None = None
    segment_type: str | None = None
    booking_class: str | None = None
    sector: str | None = None
    tour_code: str | None = None

    fare_amount: float | None = None
    yq: float | None = None
    yr: float | None = None
    # Ancillary sub-types, kept SEPARATE because that is how a deal pays them
    # (deal_matching._compute_ancillary_from_items maps Baggage / Meals / Seat Fees
    # individually). A source that only has one combined figure must leave all three None
    # rather than guess a split — see `ancillary_amount`.
    seat_selection: float | None = None
    excess_baggage: float | None = None
    meals: float | None = None
    # The combined ancillary figure, for display and for the audit snapshot. NOT fed to the
    # engine: a deal pays per sub-type and this cannot be split.
    ancillary_amount: float | None = None

    # ── How the row behaves ──────────────────────────────────────────────────
    kind: str = KIND_ISSUE
    kind_reason: str | None = None
    # 'AIRLINE' | 'B2B' — which pool of deals may match. Third party is B2B: the statement
    # comes from a consolidator, not from the carrier.
    statement_type: str = "AIRLINE"
    invoice_type: str | None = "Sales"
    supplier_agency: str | None = None
    supplier_agency_id: int | None = None

    # ── Honesty ──────────────────────────────────────────────────────────────
    skip_criteria: set[str] = field(default_factory=set)
    _skip_rule_fields: set[str] = field(default_factory=set)
    # What this row genuinely could not supply, for display. `[]` once nothing is missing.
    skipped_labels: list[str] = field(default_factory=list)
    # Per-row remarks worth showing rather than swallowing: a missing YR column, an
    # ancillary the deal pays per sub-type, a carrier resolved against a disagreeing name.
    notes: list[str] = field(default_factory=list)

    declared: DeclaredAmounts | None = None

    @property
    def skip_rule_fields(self) -> set[str]:
        """Payout incl/excl rule fields to bypass. Sector-derived fields skip themselves
        when `sector` is None (exclusion_evaluator), so only `class` needs naming."""
        return set(self._skip_rule_fields)

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


@dataclass
class BatchInfo:
    """One upload of one source, in the one shape the API renders.

    Every source stores its batches differently — the spec-driven types derive one with a
    GROUP BY over their rows table because they keep no header, while LCC Detailed has a
    real `lcc_detailed_batch` row. Normalising here is what keeps api/v1/commission.py from
    growing a branch per source.
    """
    batch_id: str
    source_file: str | None = None
    uploaded_at: object | None = None
    row_count: int = 0
    period_from: date | None = None
    period_to: date | None = None
    airline_name: str | None = None
    airline_code: str | None = None
    # Whether the statement's own rows are ready. Always "completed" for a synchronous
    # upload; LCC Detailed ingests in the background and can be listed mid-parse.
    parse_status: str = "completed"
