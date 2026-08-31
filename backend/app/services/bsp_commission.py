"""BSP commission-income engine.

Matches every BSP settlement row against the user's approved **airline** deals and
stores the estimated incentive on the row. The BSP analogue of
``tickets._run_single`` — same deal engine, different source document.

BSP is the airline's own settlement, so only ``deal_type="airline"`` deals may
match (``statement_type="AIRLINE"``).

What a BSP detailed statement actually prints, and what it does not:

    prints  → issue date, STAT (I/D), airline accounting code, fare amount,
              every tax/fee as a component row, tour code, transaction type
    absent  → cabin class, sector (origin/destination), travel date

The absent three are recovered from the **TGQ HMPR** statement when one covering the
same ticket has been uploaded — see ``services/bsp_tgq_enrichment``. With them the deal
engine evaluates the real class filter, the real travel window, and every route-based
inclusion/exclusion rule (which resolve through the Airport and Class masters).

Without them nothing is guessed: passing ``booking_class=None`` into the deal engine
would resolve to ``{"Economy"}`` and silently match Economy-only deals while rejecting
Business ones, so those criteria are **skipped** instead. Because a statement holds a
mix of enriched and unenriched rows, the skip set is computed **per row**
(``BspRowContext.skip_criteria``) and ``skipped_criteria`` records the truth for that
row — ``[]`` when nothing was skipped — rather than a fixed constant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.airline import Airline
from app.models.bsp_statement import BspStatement, BspStatementRow, BspTaxBreakup
from app.models.deal import (
    Deal as UnifiedDeal,
    DealIncentiveConfig,
    DealRule,
    build_rule_dict,
)
from app.services.bsp_reconciliation import INCENTIVE_TYPE_KEYS, norm_tn
from app.services.bsp_tgq_enrichment import SOURCE_TGQ, TgqIndex, load_tgq_index
from app.services.deal_matching import (
    SKIP_CLASS,
    SKIP_TRAVEL_DATE,
    DealMatchingService,
    _calc_base,
    _flight_type_matches,
)
from app.services.exclusion_evaluator import (
    evaluate_exclusion_for_payout_values,
    evaluate_inclusion_for_payout_values,
)

__all__ = [
    "BSP_SKIP_CRITERIA",
    "BspCommissionService",
    "RowCalcResult",
    "build_row_context",
    "load_row_contexts",
]


# ── Transaction-type policy ────────────────────────────────────────────────
# Issues earn commission; refunds reverse the original document's commission;
# memos / cancellations / bulk-cancel carriers are settlement adjustments and
# are not themselves a sale, so they earn nothing.
_ISSUE_TXN  = {"TKTT", "EMD", "EMDA", "EMDS", "EMDT", "TASF"}
_REFUND_TXN = {"RFND", "RFDA"}
_SKIP_TXN   = {"ADM", "ADMA", "ADMD", "ACM", "ACMA", "ACMD",
               "CANX", "CANN", "SPDR", "SPCR", "VOID", "EXCH"}

_SKIP_REASON = {
    "ADM": "Debit memo — settlement adjustment, not a sale",
    "ACM": "Credit memo — settlement adjustment, not a sale",
    "CANX": "Cancellation charge — not a sale",
    "CANN": "Cancellation — not a sale",
    "SPDR": "Bulk-cancel charge carrier — not a sale",
    "SPCR": "Bulk-cancel credit — not a sale",
    "VOID": "Voided document — not a sale",
    "EXCH": "Exchange — settled under the reissued document",
}

# Defaults for an UNENRICHED row — BSP prints none of these, so the matching filters that
# depend on them are bypassed rather than evaluated against fabricated defaults. A row with
# a TGQ HMPR counterpart narrows these per row; see BspRowContext.skip_criteria.
BSP_SKIP_CRITERIA = {SKIP_CLASS, SKIP_TRAVEL_DATE}
# Payout incl/excl rule fields BSP cannot evaluate. Sector-derived fields
# (origin/dest/country/continent/city/soto/domesticCountry) skip themselves when
# `sector` is None; only `class` needs to be named explicitly.
BSP_SKIP_RULE_FIELDS = {"class"}

# BSP is a sales settlement — deals whose trigger_type is "Flown" correctly do
# not match a BSP row.
_BSP_INVOICE_TYPE = "Sales"

_STAT_SEGMENT = {"I": "International", "D": "Domestic"}


def stat_to_segment(stat: str | None) -> str | None:
    """BSP STAT column → Domestic / International.

    Real statements print more than a bare I/D: amended rows carry a suffix
    (``I71``, ``I41``), so the leading letter is what carries the meaning.
    Anything else returns None, which the deal engine treats as "cannot
    determine" and lets through.
    """
    s = (stat or "").strip().upper()
    return _STAT_SEGMENT.get(s[:1]) if s else None


# ── Row context ────────────────────────────────────────────────────────────

@dataclass
class BspRowContext:
    """Everything the deal engine needs, extracted from one BSP row."""
    row:           BspStatementRow
    airline_name:  str | None = None
    issue_date:    date | None = None
    segment_type:  str | None = None
    fare_amount:   float | None = None
    yq:            float | None = None
    yr:            float | None = None
    tour_code:     str | None = None

    # ── From the TGQ HMPR counterpart, when one exists ──────────────────────
    sector:             str | None = None    # whole journey, 'BOM/DEL/MNL/DEL/BOM'
    booking_class:      str | None = None    # distinct across legs, 'L/U'
    travel_date:        date | None = None   # first leg
    travel_date_source: str | None = None    # explicit | inferred
    leg_count:          int | None = None
    enrichment_source:  str | None = None    # None | 'tgq_hmpr'
    enrichment_ref:     str | None = None    # winning tgq_hmpr batch_id

    @property
    def skip_criteria(self) -> set[str]:
        """Matching filters to bypass for THIS row.

        Per row, not per statement: a statement holds a mix of enriched and unenriched
        rows, and skipping `class` on a row whose class we actually know would let an
        Economy-only deal match a Business ticket.
        """
        skips = set(BSP_SKIP_CRITERIA)
        if self.booking_class:
            skips.discard(SKIP_CLASS)
        if self.travel_date:
            skips.discard(SKIP_TRAVEL_DATE)
        return skips

    @property
    def skip_rule_fields(self) -> set[str]:
        """Incl/excl rule fields to bypass. Sector-derived fields skip themselves when
        `sector` is None (exclusion_evaluator), so only `class` needs naming — and only
        while we don't know it."""
        return set() if self.booking_class else set(BSP_SKIP_RULE_FIELDS)

    @property
    def skipped_labels(self) -> list[str]:
        """What this row genuinely could not evaluate. `[]` once fully enriched."""
        out = []
        if not self.booking_class:
            out.append("class")
        if not self.sector:
            out.append("sector")
        if not self.travel_date:
            out.append("travel_date")
        return out


@dataclass
class RowCalcResult:
    row_id:  int
    # calculated | needs_data | excluded | reversed | skipped | unmatched
    #
    # needs_data: a deal matched, but it restricts by a criterion this settlement
    # row does not carry (no TGQ counterpart), so the figure could not be verified.
    # `incentive` is None there — not 0 — see calculate_row.
    status:  str
    incentive: float | None = None
    iata_commission: float = 0.0
    deal_id:   int | None = None
    deal_type: str | None = None
    deal_name: str | None = None
    breakdown: dict[str, float] = field(default_factory=dict)
    reason:    str | None = None


def _f(v) -> float | None:
    return float(v) if v is not None else None


async def _airline_name_map(db: AsyncSession) -> dict[str, str]:
    """{code → airline name} for every code shape a BSP row can carry.

    BSP detailed rows print the 3-digit accounting code (e.g. ``141``) in
    `airline_accounting_code` and sometimes an IATA code in `airline_code`, so
    the map is keyed by numeric (zero-padded and bare), IATA and ICAO.
    """
    rows = (await db.execute(
        select(Airline.iata_numeric_code, Airline.iata_code, Airline.icao_code, Airline.name)
    )).all()
    out: dict[str, str] = {}
    for numeric, iata, icao, name in rows:
        if not name:
            continue
        for raw in (numeric, iata, icao):
            code = (raw or "").strip().upper()
            if not code:
                continue
            out.setdefault(code, name)
            if code.isdigit():
                out.setdefault(code.zfill(3), name)
                out.setdefault(code.lstrip("0") or code, name)
    return out


async def _tax_totals(db: AsyncSession, row_ids: list[int]) -> dict[int, dict[str, float]]:
    """{bsp_row_id: {component_code: amount}} in one grouped query (no N+1)."""
    if not row_ids:
        return {}
    out: dict[int, dict[str, float]] = {}
    CHUNK = 5000
    for i in range(0, len(row_ids), CHUNK):
        q = (
            select(
                BspTaxBreakup.bsp_row_id,
                BspTaxBreakup.component_code,
                func.sum(BspTaxBreakup.amount),
            )
            .where(BspTaxBreakup.bsp_row_id.in_(row_ids[i:i + CHUNK]))
            .group_by(BspTaxBreakup.bsp_row_id, BspTaxBreakup.component_code)
        )
        for rid, code, amt in (await db.execute(q)).all():
            if not code:
                continue
            out.setdefault(rid, {})[code.upper()] = float(amt or 0)
    return out


def build_row_context(
    row: BspStatementRow,
    air_map: dict[str, str],
    taxes: dict[str, float],
    tgq: TgqIndex | None = None,
) -> BspRowContext:
    codes = [
        (row.airline_accounting_code or "").strip().upper(),
        (row.airline_code or "").strip().upper(),
    ]
    airline_name = None
    for c in codes:
        if not c:
            continue
        airline_name = air_map.get(c) or (air_map.get(c.zfill(3)) if c.isdigit() else None)
        if airline_name:
            break

    tour = row.tour or []
    ctx = BspRowContext(
        row=row,
        airline_name=airline_name,
        issue_date=row.issue_date,
        segment_type=stat_to_segment(row.stat),
        fare_amount=_f(row.fare_amount),
        yq=taxes.get("YQ"),
        yr=taxes.get("YR"),
        tour_code=(str(tour[0]).strip() if isinstance(tour, list) and tour else None),
    )

    # Join to TGQ HMPR on the document serial. `document_number`, not `ticket_number` —
    # the latter is deliberately NULL for EMD/ACM/ADM and 00…/40… refunds.
    hit = tgq.lookup(row.airline_accounting_code, row.document_number, row.alt_document_numbers) if tgq else None
    if hit is not None:
        # The travel year is inferred against the BSP issue date, which is the
        # authoritative one — TGQ's own Ticket_Date can arrive as a pandas-mangled
        # timestamp and anchoring on it would shift a trip by a year.
        travel_date, travel_src = hit.resolve_travel(ctx.issue_date)
        ctx.sector = hit.sector
        ctx.booking_class = hit.booking_class
        ctx.travel_date = travel_date
        ctx.travel_date_source = travel_src
        ctx.leg_count = hit.leg_count
        ctx.enrichment_source = SOURCE_TGQ
        ctx.enrichment_ref = hit.batch_id
    return ctx


async def load_row_contexts(
    db: AsyncSession,
    rows: list[BspStatementRow],
    tenant_id: int | None = None,
    created_by_id: int | None = None,
) -> list[BspRowContext]:
    """Contexts for a batch of rows — three bulk maps, no N+1.

    Scope defaults to the rows' own tenant/user so a single-row call (the diagnosis
    endpoints) gets the same enrichment the run used.
    """
    if not rows:
        return []
    air_map = await _airline_name_map(db)
    tax_map = await _tax_totals(db, [r.id for r in rows])
    tgq = await load_tgq_index(
        db,
        tenant_id if tenant_id is not None else rows[0].tenant_id,
        created_by_id if created_by_id is not None else rows[0].created_by_id,
    )
    return [build_row_context(r, air_map, tax_map.get(r.id, {}), tgq) for r in rows]


# ── Cumulative slab achievement, summed from BSP rows ──────────────────────

class BspCumulativeProvider:
    """Slab band achievement summed over the user's BSP settlement rows.

    Loaded once per run and answered in memory. The uploaded-ticket equivalent
    (`deal_matching._period_cumulative_base`) re-scans the table for every slab
    config on every row; at BSP volumes (~50k rows) that is not viable.
    """

    def __init__(self, sales: list[tuple[str | None, date | None, float, float, float, str | None]]):
        # (airline_name, issue_date, fare, yq, yr, segment_type)
        self._sales = sales
        self._cache: dict[tuple, float] = {}

    @classmethod
    async def build(cls, db: AsyncSession, tenant_id: int, created_by_id: int) -> "BspCumulativeProvider":
        rows = (await db.execute(
            select(
                BspStatementRow.id,
                BspStatementRow.airline_accounting_code,
                BspStatementRow.airline_code,
                BspStatementRow.issue_date,
                BspStatementRow.fare_amount,
                BspStatementRow.stat,
                BspStatementRow.transaction_type,
            ).where(
                BspStatementRow.tenant_id == tenant_id,
                BspStatementRow.created_by_id == created_by_id,
            )
        )).all()
        # Only issues count towards a sales target.
        keep = [r for r in rows if (r.transaction_type or "").upper() in _ISSUE_TXN]
        air_map = await _airline_name_map(db)
        tax_map = await _tax_totals(db, [r.id for r in keep])

        sales = []
        for r in keep:
            name = None
            for c in ((r.airline_accounting_code or "").strip().upper(),
                      (r.airline_code or "").strip().upper()):
                if not c:
                    continue
                name = air_map.get(c) or (air_map.get(c.zfill(3)) if c.isdigit() else None)
                if name:
                    break
            t = tax_map.get(r.id, {})
            sales.append((
                name,
                r.issue_date,
                float(r.fare_amount or 0),
                float(t.get("YQ") or 0),
                float(t.get("YR") or 0),
                stat_to_segment(r.stat),
            ))
        return cls(sales)

    async def __call__(
        self,
        airline_name: str,
        start: date,
        end: date,
        flight_type: str | None,
        target_calc_cols: str | None,
    ) -> float:
        key = (airline_name.lower(), start, end, flight_type, target_calc_cols)
        if key in self._cache:
            return self._cache[key]
        want = airline_name.lower()
        total = 0.0
        for name, d, fare, yq, yr, seg in self._sales:
            if not name or name.lower() != want:
                continue
            if d is None or not (start <= d <= end):
                continue
            if not _flight_type_matches(seg, flight_type):
                continue
            total += _calc_base(fare, yq, yr, target_calc_cols)
        total = round(total, 2)
        self._cache[key] = total
        return total


# ── Per-row calculation ────────────────────────────────────────────────────

def _reset(row: BspStatementRow) -> None:
    row.matched_deal_id = None
    row.matched_deal_type = None
    row.matched_deal_name = None
    row.calculated_incentive = None
    row.iata_commission = None
    row.incentive_breakdown = None
    row.commission_reason = None
    row.skipped_criteria = None
    row.commission_status = "pending"
    row.commission_calculated_at = None
    row.enriched_sector = None
    row.enriched_booking_class = None
    row.enriched_travel_date = None
    row.enriched_travel_date_source = None
    row.enriched_leg_count = None
    row.enrichment_source = None
    row.enrichment_ref = None


def _apply_enrichment(row: BspStatementRow, ctx: BspRowContext) -> None:
    """Persist what the TGQ join resolved, so the grid can show what the match used.

    Applied before the transaction-type and refund early-returns, so even a skipped or
    reversed row still displays its sector and class.
    """
    row.enriched_sector = ctx.sector
    row.enriched_booking_class = ctx.booking_class
    row.enriched_travel_date = ctx.travel_date
    row.enriched_travel_date_source = ctx.travel_date_source
    row.enriched_leg_count = ctx.leg_count
    row.enrichment_source = ctx.enrichment_source
    row.enrichment_ref = ctx.enrichment_ref


def _finish(row: BspStatementRow, result: RowCalcResult) -> RowCalcResult:
    row.commission_status = result.status
    row.commission_reason = result.reason
    row.commission_calculated_at = datetime.utcnow()
    return result


def _refund_lookup_keys(row: BspStatementRow) -> list[str]:
    """Normalised document numbers a refund row could be reversing.

    Preferred link is the printed +RTDN related document; otherwise the refund's
    own document number. Normalised via `norm_tn` so stock prefixes and leading
    zeros do not break the join (same key the BSP↔ticket matcher uses).
    """
    raw: list[str] = []
    if row.rtdn:
        raw.append(row.rtdn)
    assoc = row.associated_docs or {}
    rtdn = assoc.get("rtdn") if isinstance(assoc, dict) else None
    if isinstance(rtdn, dict):
        for k in ("doc", "ref"):
            if rtdn.get(k):
                raw.append(str(rtdn[k]))
    for n in (row.document_number, row.ticket_number):
        if n:
            raw.append(n)

    out: list[str] = []
    for r in raw:
        key = norm_tn(r)
        if key and key not in out:
            out.append(key)
    return out


async def build_original_index(
    db: AsyncSession,
    tenant_id: int,
    created_by_id: int,
) -> dict[str, BspStatementRow]:
    """{normalised document number → already-calculated issue row}.

    Built once per run from every statement the user owns, so a refund settled in
    a later period still finds the issue it reverses. Rows calculated during the
    run are added to it as they complete.
    """
    rows = (await db.execute(
        select(BspStatementRow).where(
            BspStatementRow.tenant_id == tenant_id,
            BspStatementRow.created_by_id == created_by_id,
            BspStatementRow.calculated_incentive.is_not(None),
            BspStatementRow.commission_status.in_(["calculated", "excluded"]),
        ).order_by(BspStatementRow.issue_date.asc().nulls_last(), BspStatementRow.id.asc())
    )).scalars().all()
    index: dict[str, BspStatementRow] = {}
    for r in rows:
        key = norm_tn(r.document_number or r.ticket_number)
        if key:
            index[key] = r        # later settlement wins
    return index


# Rule condition fields that can only be answered from a SECTOR, and from a
# TRAVEL DATE. A BSP row prints neither, so a rule built on one of these is not
# evaluated at all — exclusion_evaluator self-skips a field it cannot resolve.
# Silently passing such a rule is how an unenriched row gets paid on terms nobody
# checked, so the caller is told which ones went unchecked instead.
_SECTOR_RULE_FIELDS = {
    "continent", "originAirport", "destAirport", "originCountry", "destCountry",
    "domesticCountry", "city", "soto", "route", "sector",
}
_TRAVEL_RULE_FIELDS = {"departure", "departureFrom", "departureTo", "travelDate"}


async def _apply_payout_rules(
    db: AsyncSession,
    deal_id: int,
    breakdown: dict[str, float],
    ctx: BspRowContext,
) -> tuple[bool, bool, str | None, set[str]]:
    """Run the matched deal's payout inclusion/exclusion rules.

    Returns (blocked, had_inclusion_rule, reason, unconfirmed).

    `unconfirmed` names the criteria a rule DEPENDS ON that this row could not
    supply. A rule keyed on route cannot be judged against a settlement row with
    no sector; reporting that is the difference between "these terms were met"
    and "these terms were never looked at".
    """
    res = await db.execute(
        select(UnifiedDeal)
        .options(
            selectinload(UnifiedDeal.incentives)
            .selectinload(DealIncentiveConfig.rules)
            .selectinload(DealRule.conditions)
        )
        .where(UnifiedDeal.id == deal_id)
    )
    deal = res.scalar_one_or_none()
    if deal is None:
        return False, False, None

    issue_raw = ctx.issue_date.isoformat() if ctx.issue_date else None
    # ISO, never the bare '14MAY' — exclusion_evaluator parses with dayfirst=True, which is
    # inert on YYYY-MM-DD, and a year-less token would silently assume the current year.
    travel_raw = ctx.travel_date.isoformat() if ctx.travel_date else None
    skip_fields = ctx.skip_rule_fields
    had_inclusion = False
    unconfirmed: set[str] = set()

    for config in deal.incentives:
        if config.incentive_type not in breakdown:
            continue
        for rule in config.rules:
            rule_dict = build_rule_dict(rule.conditions)
            if not rule_dict:
                continue
            # Note what this rule needed and the row could not give it, before
            # running it — the evaluator answers "not blocked" either way.
            fields = set(rule_dict)
            if ctx.sector is None and (fields & _SECTOR_RULE_FIELDS):
                unconfirmed.add("sector")
            if ctx.travel_date is None and (fields & _TRAVEL_RULE_FIELDS):
                unconfirmed.add(SKIP_TRAVEL_DATE)
            if ctx.booking_class is None and "class" in fields:
                unconfirmed.add(SKIP_CLASS)

            if rule.rule_category == "payout_inclusion":
                had_inclusion = True
                ok, reason = await evaluate_inclusion_for_payout_values(
                    db, rule_dict,
                    sector=ctx.sector, booking_class=ctx.booking_class,
                    ticket_date_raw=issue_raw, departure_raw=travel_raw,
                    airline_name=ctx.airline_name, tour_code=ctx.tour_code,
                    skip_fields=skip_fields,
                )
                if not ok:
                    return True, had_inclusion, reason, unconfirmed
            elif rule.rule_category == "payout_exclusion":
                excluded, reason = await evaluate_exclusion_for_payout_values(
                    db, rule_dict,
                    sector=ctx.sector, booking_class=ctx.booking_class,
                    ticket_date_raw=issue_raw, departure_raw=travel_raw,
                    airline_name=ctx.airline_name, tour_code=ctx.tour_code,
                    skip_fields=skip_fields,
                )
                if excluded:
                    return True, had_inclusion, reason, unconfirmed
    return False, had_inclusion, None, unconfirmed


_NEEDS_DATA_LABEL = {
    SKIP_CLASS: "cabin class",
    SKIP_TRAVEL_DATE: "travel date",
    "sector": "sector",
}


def _needs_data_reason(deal_no: str, unconfirmed: list[str]) -> str:
    """Say what is missing, why it matters, and what to do about it.

    DELIBERATELY IDENTICAL FOR EVERY ROW WITH THE SAME GAP. The "Unmatched &
    skipped" tab groups rows by (status, reason), so naming the ticket here — as
    an earlier version did — gave 9,021 rows 9,021 distinct reasons and turned one
    actionable bucket into 12,088 groups and a 959 KB response. The tab already
    carries sample document numbers per bucket; that is where the specifics live.
    """
    missing = ", ".join(_NEEDS_DATA_LABEL.get(c, c) for c in unconfirmed)
    return (
        f"{missing.capitalize()} not known — deal {deal_no} pays only on specific "
        f"{missing}. Upload the TGQ HMPR covering this period and re-run."
    )[:500]


async def calculate_row(
    db: AsyncSession,
    ctx: BspRowContext,
    tenant_id: int,
    created_by_id: int,
    cumulative_provider: BspCumulativeProvider | None = None,
    original_index: dict[str, BspStatementRow] | None = None,
) -> RowCalcResult:
    """Match one BSP row to an airline deal and write the estimated commission."""
    row = ctx.row
    _reset(row)
    # Before the early returns below, so a skipped or reversed row still shows its sector.
    _apply_enrichment(row, ctx)
    txn = (row.transaction_type or "").strip().upper()

    # 1. Settlement adjustments never earn.
    if txn in _SKIP_TXN:
        row.calculated_incentive = 0
        return _finish(row, RowCalcResult(
            row_id=row.id, status="skipped", incentive=0,
            reason=_SKIP_REASON.get(txn, f"{txn or 'Unknown'} — not a sale"),
        ))

    # 2. Refund → reverse the original document's commission.
    if txn in _REFUND_TXN:
        index = original_index or {}
        original = next(
            (index[k] for k in _refund_lookup_keys(row) if k in index and index[k].id != row.id),
            None,
        )
        if original is not None and original.calculated_incentive is not None:
            reversal = -float(original.calculated_incentive)
            row.matched_deal_id   = original.matched_deal_id
            row.matched_deal_type = original.matched_deal_type
            row.matched_deal_name = original.matched_deal_name
            row.calculated_incentive = reversal
            row.incentive_breakdown = {
                k: -float(v) for k, v in (original.incentive_breakdown or {}).items()
            }
            row.iata_commission = (
                -float(original.iata_commission) if original.iata_commission is not None else 0
            )
            return _finish(row, RowCalcResult(
                row_id=row.id, status="reversed", incentive=reversal,
                iata_commission=float(row.iata_commission or 0),
                deal_id=original.matched_deal_id,
                deal_type=original.matched_deal_type,
                deal_name=original.matched_deal_name,
                breakdown=row.incentive_breakdown,
                reason=(
                    f"Reversal of document {original.document_number or '—'} — "
                    f"original incentive {original.calculated_incentive}"
                ),
            ))
        row.calculated_incentive = 0
        return _finish(row, RowCalcResult(
            row_id=row.id, status="skipped", incentive=0,
            reason=(
                f"Refund: no previously calculated issue found for document "
                f"{row.document_number or 'unknown'}."
            ),
        ))

    # 3. Issues (and anything else that behaves like one) need an airline + a date.
    if not ctx.airline_name:
        return _finish(row, RowCalcResult(
            row_id=row.id, status="unmatched",
            reason=(
                f"Airline code '{row.airline_accounting_code or row.airline_code or '—'}' "
                f"is not in the airline master."
            ),
        ))
    if ctx.issue_date is None:
        return _finish(row, RowCalcResult(
            row_id=row.id, status="unmatched", reason="Row has no issue date.",
        ))

    # 4. Deal search. BSP is the airline settlement → airline deals only. Travel date and
    #    cabin class come from the TGQ HMPR counterpart when there is one; without it the
    #    issue date stands in and those criteria stay skipped.
    #
    #    `issue_date` is unchanged either way — deal validity and the candidate query still
    #    key off it (deal_matching: contract_date = issue_date or travel_date). Only the
    #    per-incentive travel window and the slab period see the real travel date.
    match = await DealMatchingService.find_best_deal(
        db=db,
        airline_name=ctx.airline_name,
        travel_date=ctx.travel_date or ctx.issue_date,
        tenant_id=tenant_id,
        created_by_id=created_by_id,
        issue_date=ctx.issue_date,
        segment_type=ctx.segment_type,
        booking_class=ctx.booking_class,
        invoice_type=_BSP_INVOICE_TYPE,
        sell_fare=ctx.fare_amount,
        sell_tax_yq=ctx.yq,
        sale_yr=ctx.yr,
        statement_type="AIRLINE",
        skip_criteria=ctx.skip_criteria,
        cumulative_provider=cumulative_provider,
    )

    if match is None:
        row.skipped_criteria = ctx.skipped_labels
        return _finish(row, RowCalcResult(
            row_id=row.id, status="unmatched", reason="No matching approved airline deal found.",
        ))

    breakdown = match.incentive_breakdown or {}
    total = round(sum(breakdown.values()), 2) if breakdown else match.calculated_incentive

    row.matched_deal_id   = match.deal_id
    row.matched_deal_type = match.deal_type
    row.matched_deal_name = match.deal_name
    row.incentive_breakdown = breakdown
    row.calculated_incentive = total
    row.skipped_criteria = ctx.skipped_labels

    # IATA commission — the deal's own % applied to the settled fare. Its own
    # column, deliberately NOT part of the incentive total.
    iata_pct = 0.0
    if match.iata_commission:
        try:
            iata_pct = float(str(match.iata_commission).strip().rstrip("%").strip())
        except (TypeError, ValueError):
            iata_pct = 0.0
    row.iata_commission = round(iata_pct / 100.0 * float(ctx.fare_amount or 0), 2)

    blocked, had_inclusion, reason, rule_unconfirmed = await _apply_payout_rules(
        db, match.deal_id, breakdown, ctx,
    )
    if blocked:
        row.calculated_incentive = 0
        row.incentive_breakdown = {}
        return _finish(row, RowCalcResult(
            row_id=row.id, status="excluded", incentive=0,
            iata_commission=float(row.iata_commission or 0),
            deal_id=match.deal_id, deal_type=match.deal_type, deal_name=match.deal_name,
            reason=reason,
        ))

    # ── Did we actually check everything this deal pays on? ─────────────────
    # A criterion the source does not print is skipped by the matcher, not
    # satisfied by it. Where the deal RESTRICTS by such a criterion, the figure
    # above is a guess: this deal pays Economy only, and nobody knows what class
    # this ticket was. NOTHING IS EARNED, so nothing is reported: the deal, the
    # breakdown and the amount are all cleared, and the row reads exactly like an
    # unmatched one — which is what it is. An earlier version kept the figures
    # visible "for information" and that was wrong: a column showing ₹245.40 on a
    # row that pays nothing is read as money, however the status is labelled.
    #
    # The STATUS stays `needs_data` even though the screen calls it Unmatched.
    # That is the one thing worth keeping apart, and it costs nothing: 9,021 rows
    # that only need a TGQ HMPR upload are a different job from 2,986 rows with no
    # deal at all, and the count, the filter and the gaps bucket all depend on
    # being able to tell them apart.
    unconfirmed = sorted(set(match.unconfirmed_criteria) | rule_unconfirmed)
    if unconfirmed:
        row.calculated_incentive = None
        row.incentive_breakdown = {}
        row.matched_deal_id = None
        row.matched_deal_type = None
        row.matched_deal_name = None
        # The IATA commission goes too. It is the unconfirmed deal's own
        # percentage applied to the fare — leaving it behind would keep one number
        # on the row sourced from a deal we just declined to apply.
        row.iata_commission = None
        return _finish(row, RowCalcResult(
            row_id=row.id, status="needs_data", incentive=None,
            reason=_needs_data_reason(match.deal_no, unconfirmed),
        ))

    return _finish(row, RowCalcResult(
        row_id=row.id, status="calculated", incentive=total,
        iata_commission=float(row.iata_commission or 0),
        deal_id=match.deal_id, deal_type=match.deal_type, deal_name=match.deal_name,
        breakdown=breakdown,
        reason=(
            f"Matched airline deal {match.deal_no}"
            + (" (inclusion rule passed)" if had_inclusion else "")
        ),
    ))


# ── Run orchestration ──────────────────────────────────────────────────────

def _set_progress(stmt: BspStatement, processed: int) -> None:
    """Advance the progress bar and prove the run is still alive."""
    stmt.commission_processed_rows = processed
    stmt.commission_heartbeat_at = datetime.utcnow()


@dataclass
class RunSummary:
    total:      int = 0
    calculated: int = 0
    needs_data: int = 0
    excluded:   int = 0
    reversed_:  int = 0
    skipped:    int = 0
    unmatched:  int = 0
    errors:     int = 0
    total_incentive: float = 0.0
    total_iata:      float = 0.0


class BspCommissionService:

    CHUNK = 200   # rows between progress flushes

    @staticmethod
    async def run(
        db: AsyncSession,
        *,
        batch_id: str,
        tenant_id: int,
        created_by_id: int,
        progress_every: int | None = None,
    ) -> RunSummary:
        """Calculate commission for every row of one BSP detailed statement.

        Idempotent — each run resets and recomputes the whole statement.
        """
        chunk = progress_every or BspCommissionService.CHUNK

        stmt = (await db.execute(
            select(BspStatement).where(
                BspStatement.batch_id == batch_id,
                BspStatement.tenant_id == tenant_id,
                BspStatement.created_by_id == created_by_id,
            )
        )).scalar_one_or_none()
        if stmt is None:
            raise ValueError(f"BSP statement {batch_id} not found")

        rows = (await db.execute(
            select(BspStatementRow)
            .where(
                BspStatementRow.statement_id == batch_id,
                BspStatementRow.tenant_id == tenant_id,
                BspStatementRow.created_by_id == created_by_id,
            )
            # Issues before refunds so a refund can find the issue it reverses
            # even when both settle in the same statement.
            .order_by(BspStatementRow.issue_date.asc().nulls_last(), BspStatementRow.id.asc())
        )).scalars().all()

        stmt.commission_status = "processing"
        stmt.commission_total_rows = len(rows)
        stmt.commission_processed_rows = 0
        stmt.commission_error = None
        stmt.commission_heartbeat_at = datetime.utcnow()
        await db.commit()

        summary = await BspCommissionService._process(
            db, rows, tenant_id, created_by_id,
            on_progress=lambda i: _set_progress(stmt, i), progress_every=chunk,
        )

        stmt.commission_processed_rows = len(rows)
        stmt.commission_status = "completed"
        await BspCommissionService.refresh_totals(db, stmt)
        await db.commit()
        return summary

    @staticmethod
    async def run_rows(
        db: AsyncSession,
        *,
        batch_id: str,
        tenant_id: int,
        created_by_id: int,
        row_ids: list[int],
    ) -> RunSummary:
        """Calculate just the selected rows, synchronously.

        A hand-picked selection is small, so it runs inside the request instead of
        going through the worker — which also means checking a few tickets works
        even when no Celery worker is up.
        """
        stmt = (await db.execute(
            select(BspStatement).where(
                BspStatement.batch_id == batch_id,
                BspStatement.tenant_id == tenant_id,
                BspStatement.created_by_id == created_by_id,
            )
        )).scalar_one_or_none()
        if stmt is None:
            raise ValueError(f"BSP statement {batch_id} not found")

        rows = (await db.execute(
            select(BspStatementRow)
            .where(
                BspStatementRow.id.in_(row_ids),
                BspStatementRow.statement_id == batch_id,
                BspStatementRow.tenant_id == tenant_id,
                BspStatementRow.created_by_id == created_by_id,
            )
            .order_by(BspStatementRow.issue_date.asc().nulls_last(), BspStatementRow.id.asc())
        )).scalars().all()

        summary = await BspCommissionService._process(db, rows, tenant_id, created_by_id)
        await BspCommissionService.refresh_totals(db, stmt)
        await db.commit()
        return summary

    @staticmethod
    async def _process(
        db: AsyncSession,
        rows: list[BspStatementRow],
        tenant_id: int,
        created_by_id: int,
        on_progress=None,
        progress_every: int = 0,
    ) -> RunSummary:
        """Calculate a list of rows. Shared by the full run and a selected-rows run."""
        provider = await BspCumulativeProvider.build(db, tenant_id, created_by_id)
        originals = await build_original_index(db, tenant_id, created_by_id)
        contexts = await load_row_contexts(db, rows, tenant_id, created_by_id)
        summary = RunSummary(total=len(rows))

        # Refunds run last so an issue settled in the same batch is already
        # calculated by the time its refund looks for it.
        ordered = [c for c in contexts if (c.row.transaction_type or "").upper() not in _REFUND_TXN]
        ordered += [c for c in contexts if (c.row.transaction_type or "").upper() in _REFUND_TXN]

        for i, ctx in enumerate(ordered, start=1):
            try:
                result = await calculate_row(
                    db, ctx, tenant_id, created_by_id, provider, originals,
                )
                if result.status in ("calculated", "excluded"):
                    key = norm_tn(ctx.row.document_number or ctx.row.ticket_number)
                    if key:
                        originals[key] = ctx.row
                if result.status == "calculated":
                    summary.calculated += 1
                elif result.status == "needs_data":
                    summary.needs_data += 1
                elif result.status == "excluded":
                    summary.excluded += 1
                elif result.status == "reversed":
                    summary.reversed_ += 1
                elif result.status == "skipped":
                    summary.skipped += 1
                else:
                    # Anything unrecognised lands here deliberately, so a status
                    # added without touching this chain is visible as unmatched
                    # rather than silently dropped from the tally.
                    summary.unmatched += 1
                summary.total_incentive += float(result.incentive or 0)
                summary.total_iata += float(result.iata_commission or 0)
            except Exception as exc:   # one bad row must not fail the whole run
                summary.errors += 1
                ctx.row.commission_status = "unmatched"
                ctx.row.commission_reason = f"Calculation error: {exc}"[:500]

            if on_progress and progress_every and i % progress_every == 0:
                on_progress(i)
                await db.commit()

        return summary

    @staticmethod
    async def refresh_totals(db: AsyncSession, stmt: BspStatement) -> None:
        """Recompute the statement roll-ups from its rows.

        Derived from the rows rather than accumulated in the loop, so a run over a
        hand-picked selection leaves the headline numbers consistent with the whole
        statement instead of reflecting only what was just recalculated.
        """
        agg = (await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(BspStatementRow.calculated_incentive), 0),
                func.coalesce(func.sum(BspStatementRow.iata_commission), 0),
                func.count().filter(BspStatementRow.commission_status.in_(["calculated", "reversed"])),
                func.count().filter(BspStatementRow.commission_status == "unmatched"),
                func.count().filter(BspStatementRow.commission_status == "excluded"),
                func.count().filter(BspStatementRow.commission_status == "skipped"),
                func.count().filter(BspStatementRow.commission_status == "needs_data"),
                # Rows nobody has calculated yet. Counted because they used to fall
                # into no bucket at all: a statement where the run never happened
                # showed 8 matched / 0 / 0 / 0 and looked calculated but poor,
                # rather than 15,196 rows untouched.
                func.count().filter(BspStatementRow.commission_status == "pending"),
                # "Enriched" means a criterion was actually RECOVERED, not merely
                # that a TGQ row was found. A counterpart whose sector and travel
                # date both failed to parse still sets enrichment_source, so
                # counting that column overstated coverage against rows the grid
                # renders blank.
                func.count().filter(
                    BspStatementRow.enrichment_source.is_not(None)
                    & (
                        BspStatementRow.enriched_sector.is_not(None)
                        | BspStatementRow.enriched_booking_class.is_not(None)
                        | BspStatementRow.enriched_travel_date.is_not(None)
                    )
                ),
            ).where(
                BspStatementRow.statement_id == stmt.batch_id,
                # Scoped like every other query in this file. statement_id is a
                # uuid so this changes nothing today, but an unscoped aggregate in
                # a per-user product is a bug waiting for its first collision.
                BspStatementRow.tenant_id == stmt.tenant_id,
                BspStatementRow.created_by_id == stmt.created_by_id,
            )
        )).one()

        rows, total, iata, matched, unmatched, excluded, skipped, needs_data, pending, enriched = agg
        stmt.commission_total_incentive = round(float(total or 0), 2)
        stmt.commission_iata_total = round(float(iata or 0), 2)
        stmt.commission_matched_rows = matched or 0
        stmt.commission_unmatched_rows = unmatched or 0
        stmt.commission_excluded_rows = excluded or 0
        stmt.commission_skipped_rows = skipped or 0
        stmt.commission_needs_data_rows = needs_data or 0
        stmt.commission_pending_rows = pending or 0
        stmt.commission_enriched_rows = enriched or 0
        # Set here, not only in run(). It was written in exactly one place — the
        # start of a queued whole-statement run — so a statement only ever touched
        # by the inline per-row path kept the column at its 0 default, and the UI
        # divided by it: "Enriched from TGQ — 5 of 0".
        stmt.commission_total_rows = rows or 0
        stmt.commission_calculated_at = datetime.utcnow()

    @staticmethod
    def summarise(rows: Iterable[BspStatementRow]) -> dict:
        """Per-airline × incentive-type totals for the Summary tab."""
        by_airline: dict[str, dict] = {}
        grand = {k: 0.0 for k in INCENTIVE_TYPE_KEYS}
        grand_total = 0.0
        grand_iata = 0.0

        for r in rows:
            key = r.airline_name or r.airline_code or r.airline_accounting_code or "—"
            bucket = by_airline.setdefault(key, {
                "airline": key,
                "rows": 0,
                "incentives": {k: 0.0 for k in INCENTIVE_TYPE_KEYS},
                "total_incentive": 0.0,
                "iata_commission": 0.0,
            })
            bucket["rows"] += 1
            for k, v in (r.incentive_breakdown or {}).items():
                if k in bucket["incentives"]:
                    bucket["incentives"][k] += float(v or 0)
                    grand[k] += float(v or 0)
            inc = float(r.calculated_incentive or 0)
            iata = float(r.iata_commission or 0)
            bucket["total_incentive"] += inc
            bucket["iata_commission"] += iata
            grand_total += inc
            grand_iata += iata

        for bucket in by_airline.values():
            bucket["incentives"] = {k: round(v, 2) for k, v in bucket["incentives"].items()}
            bucket["total_incentive"] = round(bucket["total_incentive"], 2)
            bucket["iata_commission"] = round(bucket["iata_commission"], 2)

        return {
            "airlines": sorted(by_airline.values(), key=lambda b: b["airline"]),
            "totals": {
                "incentives": {k: round(v, 2) for k, v in grand.items()},
                "total_incentive": round(grand_total, 2),
                "iata_commission": round(grand_iata, 2),
            },
        }
