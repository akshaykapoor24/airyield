"""Buy-vs-sell reconciliation: what a ticket cost, what it sold for, what was made on it.

The BUY side is one vendor statement row, normalised by an adapter in
`services/reconciliation/`. The SELL side is the workspace's own `uploaded_tickets`.

SIGN CONVENTION: `margin = sell - buy`. Positive means the sale earned money. That is the
OPPOSITE of `bsp_reconciliation`'s `expected - actual` — there the question is who is short,
here it is what was made. The two engines never write the same row.

THE SELL SIDE MUST BE SUMMED, NOT PICKED. A multi-sector ticket is stored as one
`uploaded_tickets` row per leg with every money column divided across the legs
(`services/sector_split.py`, largest-remainder so the parts re-sum exactly). Taking one leg
would report half a ticket. Verified on ticket 2354848358656: two legs of 44,718.50 sum to
the 89,437 the vendor's `net_amount` states. Refund rows are stored as negative legs of the
same ticket number, so summing nets them too — also deliberate.

WHY `tax` IS A TOTAL ON BOTH SIDES. A consolidator lumps the tax bill into `other_taxes`
and leaves `yq` at zero on one row while filling it on the next; the ticket file always
splits the same money across `sell_tax_yq`, `sale_yr` and `other_tax`. Column-to-column
they disagree on nearly every row while the totals agree to the paisa. `yq` and `yr` are
still reported on their own lines, as components.

HOW A TICKET FINDS ITS SALE. On the DOCUMENT SERIAL, which every table now stores on its
own — `third_party_gds` always did, BSP settlement rows carry the bare serial, and
`uploaded_tickets` was split to match (migration tkt_prefix_01). The airline's 3-digit
accounting code sits beside it and is the CHECK, not part of the key: a serial is unique
only within one airline, and this workspace's own data holds Iberia 075-5808758877 and
British Airways 125-5808758877. The serial finds the pair, the codes say whether it is
really one ticket. Where they disagree the row is `possible_match` — visible, named, and
never linked or counted as reconciled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sell_reconciliation import (
    ENGINE_VERSION, STATUS_BUY_ONLY, STATUS_MATCHED, STATUS_MINOR_DIFF, STATUS_MISMATCH,
    STATUS_POSSIBLE, STATUS_SELL_ONLY, SellReconciliation, SellReconciliationRun,
)
from app.models.uploaded_ticket import UploadedTicket
from app.services.markup_categories import CATEGORY_AIR
from app.services.reconciliation import MONEY_FIELDS, BuyRow, get_adapter
from app.services.reconciliation.adapters import _norm

Q = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True)
class FieldSpec:
    """Tolerances per compared field. Same shape as bsp_reconciliation.FieldSpec.

    `abs_tol` absorbs rounding; `pct_tol` absorbs the proportional drift a percentage-based
    charge produces on a large fare. A field over tolerance raises an issue at `severity`,
    and `_status_from_issues` turns the worst severity into the row's verdict.
    """
    key: str
    label: str
    severity: str          # 'critical' | 'warning'
    abs_tol: Decimal
    pct_tol: Decimal


# Display order in the drilldown. `net` is last because it is the headline the margin is
# taken from, and reads as the bottom line of the table.
FIELD_SPECS: list[FieldSpec] = [
    FieldSpec("fare",       "Base fare",   "critical", Decimal("1.00"), Decimal("0.005")),
    FieldSpec("yq",         "YQ",          "warning",  Decimal("1.00"), Decimal("0")),
    FieldSpec("yr",         "YR",          "warning",  Decimal("1.00"), Decimal("0")),
    FieldSpec("tax",        "Total tax",   "warning",  Decimal("1.00"), Decimal("0")),
    FieldSpec("gross",      "Gross",       "critical", Decimal("1.00"), Decimal("0.005")),
    FieldSpec("commission", "Commission",  "warning",  Decimal("1.00"), Decimal("0")),
    FieldSpec("net",        "Net",         "critical", Decimal("1.00"), Decimal("0.005")),
]


def _d(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001 — any unparseable cell is simply not a number
        return None


def _f(v: Decimal | None) -> float | None:
    """To float at the stored scale.

    Quantized because these same numbers go two ways — into NUMERIC(14,2) columns and
    verbatim into the `field_diffs` JSONB the drilldown renders. Without it the grid showed
    2,024,899.81 while the drilldown showed 2,024,899.8144 for the one amount.
    """
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v.quantize(Q))
    return float(v)


def _compare(spec: FieldSpec, buy: Decimal | None, sell: Decimal | None):
    """(variance, match, is_issue). None on BOTH sides → the field is not comparable.

    `variance = sell - buy`, matching the margin's direction so a positive number means the
    same thing everywhere on the screen. One side missing is treated as zero — the other
    side genuinely charged something the counterpart did not.
    """
    if buy is None and sell is None:
        return None, None, False
    b = buy if buy is not None else ZERO
    s = sell if sell is not None else ZERO
    variance = (s - b).quantize(Q)
    tol = spec.abs_tol + spec.pct_tol * abs(b)
    match = abs(variance) <= tol
    return variance, match, (not match)


def _status_from_issues(issues: list[dict]) -> tuple[str, str]:
    if any(i["severity"] == "critical" for i in issues):
        return STATUS_MISMATCH, "critical"
    if any(i["severity"] == "warning" for i in issues):
        return STATUS_MINOR_DIFF, "warning"
    return STATUS_MATCHED, "ok"


@dataclass
class BuySide:
    """One PURCHASED ticket, netted across every vendor row that mentions it.

    A consolidator prints a cancellation as a second row against the same ticket number
    carrying the negative of the original. Comparing each row to the whole sale separately
    produced two enormous, opposite, meaningless variances on the same ticket — so the buy
    side is netted per ticket exactly as the sell side is netted across its legs, and the
    comparison is ticket-to-ticket on both sides.
    """
    group_key: str
    source_row_ids: list[int]
    batch_id: str | None
    amounts: dict[str, Decimal | None]
    ticket_key: str | None
    ticket_prefix: str | None
    projected_ticket_id: int | None
    ticket_number: str | None = None
    airline_name: str | None = None
    airline_code: str | None = None
    issue_date: date | None = None
    pax_name: str | None = None
    sector: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def source_row_id(self) -> int:
        """The representative row. `min` so a re-run picks the same one every time."""
        return min(self.source_row_ids)

    def amount(self, key: str) -> Decimal | None:
        return self.amounts.get(key)


def _group_buy_rows(rows: list[BuyRow]) -> list[BuySide]:
    """Net the vendor's rows per ticket.

    Grouping key, in the same priority the matcher itself uses: the projection FK where the
    source has one, else the exact ticket key. A row with NEITHER cannot be pooled with
    anything — pooling on a blank key would merge unrelated rows into one invented ticket —
    so it stays a group of one, keyed by its own id.
    """
    groups: dict[str, BuySide] = {}
    order: list[str] = []
    for r in rows:
        if r.projected_ticket_id is not None:
            key = f"t:{r.projected_ticket_id}"
        elif r.ticket_key:
            key = f"k:{r.ticket_key}"
        else:
            key = f"r:{r.source_row_id}"

        g = groups.get(key)
        if g is None:
            g = BuySide(
                group_key=key, source_row_ids=[], batch_id=r.batch_id,
                amounts={k: None for k in MONEY_FIELDS},
                ticket_key=r.ticket_key, ticket_prefix=r.ticket_prefix,
                projected_ticket_id=r.projected_ticket_id,
                ticket_number=r.ticket_number, airline_name=r.airline_name,
                airline_code=r.airline_code, issue_date=r.issue_date,
                pax_name=r.pax_name, sector=r.sector, notes=[],
            )
            groups[key] = g
            order.append(key)

        g.source_row_ids.append(r.source_row_id)
        for f_ in MONEY_FIELDS:
            v = r.amount(f_)
            if v is None:
                continue
            g.amounts[f_] = v if g.amounts[f_] is None else g.amounts[f_] + v
        for n in r.notes:
            if n not in g.notes:
                g.notes.append(n)
        # The earliest date is the issue; a later row on the same ticket is the change.
        if g.issue_date is None or (r.issue_date and r.issue_date < g.issue_date):
            g.issue_date = r.issue_date or g.issue_date

    for g in groups.values():
        if len(g.source_row_ids) > 1:
            g.notes.append(
                f"The buy figures are the net of {len(g.source_row_ids)} statement rows for "
                f"this ticket — an issue and its later cancellation or reissue."
            )
    return [groups[k] for k in order]


@dataclass
class SellSide:
    """One sold ticket, summed across its legs."""
    ticket_id: int
    ticket_number: str | None
    ticket_prefix: str | None
    legs: int
    amounts: dict[str, Decimal | None]
    airline_name: str | None = None
    airline_code: str | None = None
    issue_date: date | None = None
    pax_name: str | None = None
    sector: str | None = None


@dataclass
class RunSummary:
    run_id: int
    reconciled_at: datetime
    total: int = 0
    matched: int = 0
    minor_diff: int = 0
    mismatch: int = 0
    buy_only: int = 0
    sell_only: int = 0
    possible_match: int = 0
    total_buy: float = 0.0
    total_sell: float = 0.0
    total_margin: float = 0.0
    counts: dict = field(default_factory=dict)


class SellReconciliationService:
    """Recompute one source's buy-vs-sell answer, wholesale and idempotently."""

    @staticmethod
    async def _load_sell_side(db: AsyncSession, tenant_id: int, user_id: int):
        """Every sold ticket, summed across its legs, indexed by join key.

        Returns `(by_key, by_ticket_id, all_sides)`, keyed on the normalised DOCUMENT
        SERIAL — `uploaded_tickets.ticket_number` holds the serial alone since migration
        tkt_prefix_01, with the airline accounting code in `ticket_prefix` beside it, so
        this is the same key the vendor side builds and the join is exact.
        """
        t = UploadedTicket
        norm = func.upper(func.ltrim(
            func.regexp_replace(t.ticket_number, r"[^0-9A-Za-z]", "", "g"), "0"))

        rows = (await db.execute(
            select(
                norm.label("k"),
                func.min(t.id).label("ticket_id"),
                func.count().label("legs"),
                func.sum(t.sell_fare).label("fare"),
                func.sum(t.sell_tax_yq).label("yq"),
                func.sum(t.sale_yr).label("yr"),
                # sell_tax is NULL on every row of the real ticket files, so the tax total
                # is built from the components that ARE populated. Summing all four is
                # safe: a file that fills sell_tax leaves the components empty and the
                # other way round — they are two spellings of the same money, never both.
                func.sum(func.coalesce(t.sell_tax, 0)).label("tax_total_col"),
                func.sum(func.coalesce(t.other_tax, 0)).label("other_tax"),
                func.sum(t.total_amt).label("total_amt"),
                func.sum(t.comm_sell).label("comm"),
                func.sum(t.net_amt).label("net"),
                func.max(t.airline_name).label("airline_name"),
                func.max(t.airlines_code).label("airline_code"),
                func.max(t.pax_name).label("pax_name"),
                func.max(t.sector).label("sector"),
                func.min(t.ticket_date).label("ticket_date"),
                func.max(t.ticket_number).label("ticket_number"),
                func.max(t.ticket_prefix).label("ticket_prefix"),
            )
            .where(t.tenant_id == tenant_id, t.created_by_id == user_id,
                   t.product_category == CATEGORY_AIR,
                   t.ticket_number.isnot(None), t.ticket_number != "")
            .group_by(norm)
        )).all()

        by_key: dict[str, SellSide] = {}
        all_sides: list[SellSide] = []
        for r in rows:
            yq, yr = _d(r.yq), _d(r.yr)
            tax_col, other = _d(r.tax_total_col), _d(r.other_tax)
            parts = [p for p in (yq, yr, tax_col, other) if p is not None]
            tax_total = sum(parts) if parts else None

            fare = _d(r.fare)
            # `net_amt` is NULL on every row of the real ticket files; `total_amt` is the
            # figure the customer was actually charged and is what the vendor's own
            # `net_amount` should be compared against. Falling back is not a guess — it is
            # the same money under the column the file happens to fill.
            net = _d(r.net) if r.net is not None else _d(r.total_amt)
            gross = None
            if fare is not None or tax_total is not None:
                gross = (fare or ZERO) + (tax_total or ZERO)

            side = SellSide(
                ticket_id=r.ticket_id,
                ticket_number=r.ticket_number,
                ticket_prefix=r.ticket_prefix,
                legs=r.legs or 0,
                amounts={
                    "fare": fare, "yq": yq, "yr": yr, "tax": tax_total,
                    "gross": gross, "commission": _d(r.comm), "net": net,
                },
                airline_name=r.airline_name,
                airline_code=r.airline_code,
                issue_date=r.ticket_date.date() if isinstance(r.ticket_date, datetime) else r.ticket_date,
                pax_name=r.pax_name,
                sector=r.sector,
            )
            by_key[r.k] = side
            all_sides.append(side)

        by_ticket_id = {s.ticket_id: s for s in all_sides}
        return by_key, by_ticket_id, all_sides

    @staticmethod
    def _build_row(buy: BuySide | None, sell: SellSide | None, *,
                   status: str, severity: str, match_method: str,
                   source: str, extra_issues: list[dict] | None = None) -> dict:
        """One `sell_reconciliations` row dict, whichever of the two sides exist."""
        diffs: list[dict] = []
        issues: list[dict] = list(extra_issues or [])
        cols: dict = {}

        for spec in FIELD_SPECS:
            b = buy.amount(spec.key) if buy else None
            s = sell.amounts.get(spec.key) if sell else None
            # Only COMPARE when both sides are present. A one-sided row is a buy_only or
            # sell_only and its "variance" would just restate the amount.
            if buy and sell:
                variance, match, is_issue = _compare(spec, b, s)
            else:
                variance, match, is_issue = None, None, False
            diffs.append({
                "key": spec.key, "label": spec.label,
                "buy": _f(b), "sell": _f(s), "variance": _f(variance),
                "match": match, "severity": spec.severity if is_issue else None,
            })
            if is_issue:
                issues.append({
                    "field": spec.key, "label": spec.label, "severity": spec.severity,
                    "buy": _f(b), "sell": _f(s), "variance": _f(variance),
                    "message": f"{spec.label}: bought at {b}, sold at {s}.",
                })
            cols[f"buy_{spec.key}"] = _f(b)
            cols[f"sell_{spec.key}"] = _f(s)
            cols[f"{spec.key}_variance"] = _f(variance)
            cols[f"{spec.key}_match"] = match

        buy_net = buy.amount("net") if buy else None
        sell_net = sell.amounts.get("net") if sell else None
        # A margin needs BOTH sides. A purchase with no sale has a cost, not a margin, and
        # calling its whole value a negative margin was both wrong and actively harmful:
        # the grid sorts worst-first, so three un-saleable statement footer lines carrying
        # the file's own totals took the top of every page ahead of the real findings.
        # `buy_net` and `sell_net` still show, so nothing is hidden.
        if buy and sell and not (buy_net is None and sell_net is None):
            margin = ((sell_net or ZERO) - (buy_net or ZERO)).quantize(Q)
        else:
            margin = None

        notes = list(buy.notes) if buy else []
        if sell and sell.legs > 1:
            notes.append(
                f"The sell figures are the sum of {sell.legs} sector rows — this ticket was "
                f"split per leg, with the money divided across them."
            )

        return {
            "source": source,
            "batch_id": buy.batch_id if buy else None,
            "source_row_id": buy.source_row_id if buy else None,
            "ticket_id": sell.ticket_id if sell else None,
            "sell_legs": sell.legs if sell else 0,
            "buy_rows": len(buy.source_row_ids) if buy else 0,
            "ticket_number": (buy.ticket_number if buy else None) or (sell.ticket_number if sell else None),
            "ticket_prefix": (buy.ticket_prefix if buy else None) or (sell.ticket_prefix if sell else None),
            "airline_name": (buy.airline_name if buy else None) or (sell.airline_name if sell else None),
            "airline_code": (buy.airline_code if buy else None) or (sell.airline_code if sell else None),
            "issue_date": (buy.issue_date if buy else None) or (sell.issue_date if sell else None),
            "pax_name": (buy.pax_name if buy else None) or (sell.pax_name if sell else None),
            "sector": (buy.sector if buy else None) or (sell.sector if sell else None),
            "match_status": status,
            "severity": severity,
            "match_method": match_method,
            "margin": _f(margin),
            "abs_margin": _f(abs(margin)) if margin is not None else None,
            "field_diffs": diffs,
            "issues": issues,
            "notes": notes,
            **cols,
        }

    @classmethod
    async def run(cls, db: AsyncSession, *, source: str, tenant_id: int, created_by_id: int,
                  batch_id: str | None = None) -> RunSummary:
        adapter = get_adapter(source)
        if adapter is None:
            raise ValueError(f"No reconciliation adapter registered for source '{source}'.")

        run = SellReconciliationRun(
            tenant_id=tenant_id, created_by_id=created_by_id, source=source,
            batch_id=batch_id, engine_version=ENGINE_VERSION, status="processing",
            started_at=datetime.utcnow(), heartbeat_at=datetime.utcnow(),
            params={"source": source, "batch_id": batch_id},
        )
        db.add(run)
        await db.flush()

        raw_rows = await adapter.load_buy_rows(db, tenant_id, created_by_id, batch_id)
        buy_sides = _group_buy_rows(raw_rows)
        by_key, by_ticket_id, all_sides = await cls._load_sell_side(
            db, tenant_id, created_by_id)

        consumed: set[int] = set()
        out: list[dict] = []

        for buy in buy_sides:
            sell = None
            method = "none"
            extra: list[dict] = []
            status_override = None

            # 1. The projection FK — authoritative, because the ticket was created FROM
            #    this row. No matching, so nothing to be wrong about.
            if buy.projected_ticket_id is not None:
                sell = by_ticket_id.get(buy.projected_ticket_id)
                if sell is not None:
                    method = "projection"

            # 2. The document serial. Both sides store it alone, with the airline
            #    accounting code in its own column, so this is an exact join.
            if sell is None and buy.ticket_key:
                sell = by_key.get(buy.ticket_key)
                if sell is not None:
                    method = "ticket_number"

                    # THE PREFIX IS THE CHECK, NOT THE KEY. A serial is unique only WITHIN
                    # an airline, and this workspace's own data proves it: Iberia
                    # 075-5808758877 and British Airways 125-5808758877 are one serial
                    # under two carriers. The serial finds the pair; the accounting codes
                    # are what say whether it is really the same ticket. Folding the prefix
                    # into the key would have hidden the collision instead of surfacing it.
                    bp, sp = buy.ticket_prefix, sell.ticket_prefix
                    if bp and sp and bp.zfill(3) != sp.zfill(3):
                        status_override = STATUS_POSSIBLE
                        extra.append({
                            "field": "ticket_number", "label": "Ticket number",
                            "severity": "critical",
                            "message": (
                                f"Same document serial, different airline: the statement "
                                f"plates it to {bp}"
                                f"{f' ({buy.airline_code})' if buy.airline_code else ''}, "
                                f"the ticket to {sp}"
                                f"{f' ({sell.airline_code})' if sell.airline_code else ''}. "
                                f"A serial is only unique within one airline, so this is a "
                                f"suggestion, not a link — nothing is reconciled from it."),
                            "buy": None, "sell": None, "variance": None,
                        })

            if sell is None:
                extra = []
                if not buy.ticket_key and buy.projected_ticket_id is None:
                    # No ticket number at all. In a real export this is the file's own
                    # footer — a "BALANCE" line carrying the statement total — imported as
                    # though it were a booking. Say so rather than presenting a
                    # seven-figure total as an unsold ticket.
                    extra.append({
                        "field": "ticket_number", "label": "Ticket number",
                        "severity": "warning",
                        "message": ("This statement row carries no ticket number, so it "
                                    "cannot be matched to a sale. Rows like this are "
                                    "usually a total or balance line from the bottom of "
                                    "the file rather than a booking."),
                        "buy": None, "sell": None, "variance": None,
                    })
                out.append(cls._build_row(
                    buy, None, status=STATUS_BUY_ONLY,
                    severity="warning" if extra else "critical",
                    match_method="none", source=source, extra_issues=extra))
                continue

            row = cls._build_row(buy, sell, status=STATUS_MATCHED, severity="ok",
                                 match_method=method, source=source, extra_issues=extra)
            if status_override:
                # A suggestion is not a verdict. The two sides stay visible so the user can
                # judge the near-miss, but the MARGIN is cleared: a figure in the money
                # column reads as money however the status chip is labelled, and this
                # pairing is explicitly not trusted. It is already excluded from the
                # totals; this stops it ranking in a grid sorted worst-first too. The
                # ticket is not consumed either — another row may still match it exactly.
                row["match_status"] = status_override
                row["severity"] = "critical"
                row["margin"] = None
                row["abs_margin"] = None
            else:
                consumed.add(sell.ticket_id)
                status, severity = _status_from_issues(row["issues"])
                row["match_status"] = status
                row["severity"] = severity
            out.append(row)

        # Sales this source's statements do not account for.
        #
        # ONLY WHEN THE SOURCE HAS STATEMENTS AT ALL. The sell side is the workspace's whole
        # ticket file and is shared by every source, so a source with nothing uploaded would
        # otherwise claim every sale ever made as "sold but never bought" — an NDC tab
        # reporting 80 unpaid tickets when no NDC statement exists says the feature is
        # broken, not that the data is. With no buy side there is simply nothing to
        # reconcile, and the empty state says so.
        if buy_sides:
            for sell in all_sides:
                if sell.ticket_id in consumed:
                    continue
                out.append(cls._build_row(
                    None, sell, status=STATUS_SELL_ONLY, severity="warning",
                    match_method="none", source=source, extra_issues=[{
                        "field": None, "label": None, "severity": "warning",
                        "message": ("No purchase for this ticket in the statements loaded "
                                    "for this source. It may have been bought through "
                                    "another one."),
                        "buy": None, "sell": None, "variance": None,
                    }]))

        now = datetime.utcnow()
        for r in out:
            r.update(run_id=run.id, tenant_id=tenant_id, created_by_id=created_by_id,
                     reconciled_at=now, created_at=now)

        # Wholesale recompute, SCOPED BY SOURCE. Without the source predicate this would
        # wipe every other tab's results — the defect that made a second engine necessary
        # rather than a `source` column on `ticket_reconciliation`.
        scope = [
            SellReconciliation.tenant_id == tenant_id,
            SellReconciliation.created_by_id == created_by_id,
            SellReconciliation.source == source,
        ]
        if batch_id:
            scope.append(SellReconciliation.batch_id == batch_id)
        await db.execute(delete(SellReconciliation).where(*scope))
        if out:
            db.add_all([SellReconciliation(**r) for r in out])
        await db.flush()

        summary = cls._tally(run, out, now)
        run.status = "completed"
        run.total_rows = summary.total
        run.processed_rows = summary.total
        run.matched_rows = summary.matched
        run.minor_diff_rows = summary.minor_diff
        run.mismatch_rows = summary.mismatch
        run.buy_only_rows = summary.buy_only
        run.sell_only_rows = summary.sell_only
        run.possible_match_rows = summary.possible_match
        run.total_buy = summary.total_buy
        run.total_sell = summary.total_sell
        run.total_margin = summary.total_margin
        run.completed_at = now
        run.heartbeat_at = now
        await db.commit()
        return summary

    @staticmethod
    def _tally(run: SellReconciliationRun, rows: list[dict], now: datetime) -> RunSummary:
        """Roll-ups recomputed from the rows just written, never accumulated as we go.

        Totals count only the rows that actually pair the two sides. A `buy_only` row has
        no sale to compare and a `possible_match` is explicitly not reconciled, so folding
        either into the margin would make the headline disagree with the grid.
        """
        s = RunSummary(run_id=run.id, reconciled_at=now, total=len(rows))
        paired = (STATUS_MATCHED, STATUS_MINOR_DIFF, STATUS_MISMATCH)
        # Decimal, not float. The list endpoint totals the same rows with a SQL SUM over
        # NUMERIC columns, and accumulating floats here drifted a paisa away from it — two
        # totals for the same money on the same screen.
        buy = sell = margin = ZERO
        for r in rows:
            st = r["match_status"]
            s.counts[st] = s.counts.get(st, 0) + 1
            setattr(s, st, getattr(s, st, 0) + 1)
            if st in paired:
                buy += _d(r.get("buy_net")) or ZERO
                sell += _d(r.get("sell_net")) or ZERO
                margin += _d(r.get("margin")) or ZERO
        s.total_buy = float(buy.quantize(Q))
        s.total_sell = float(sell.quantize(Q))
        s.total_margin = float(margin.quantize(Q))
        return s
