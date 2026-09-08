"""Turning a consolidator's statement row into something the deal engine can price.

A third-party statement is a B2B document: the consolidator sold to us, so the deal that
covers it is an INCOMING B2B deal, matched against the Supplier master row declared at
upload (`statement_batch_suppliers`) — the same list the deal picks its own supplier from.
That is the one structural difference from BSP, whose rows can only match
`deal_type='airline'`.

What this file decides, and why each is a judgement rather than a lookup:

  * **Issue date.** The real export has no ticketing-date column. Deal validity keys off
    the issue date, so the booked date stands in — recorded as `issue_date_source` at
    ingest so the diagnosis popup can say which date the contract window was tested
    against. A consolidator who books and issues on different days shifts window edges.

  * **Class.** Blank on every row of the real sample, so SKIP_CLASS applies — per row, not
    per statement, because another consolidator prints it.

  * **Travel date is NOT skipped.** The export prints "Date of Travel", so travel windows
    are genuinely evaluable. So is `Sector`, which means every route-based inclusion and
    exclusion rule can be judged — something an unenriched BSP row can never do. A
    third-party row is BETTER evidence than a BSP one, and only class-restricted deals
    withhold.

  * **YR.** There is no YR column; it is folded into "Other Taxes". `yr` is therefore None,
    which UNDER-STATES the base for a deal calculating on Basic+YQ+YR. Under-stating is
    conservative — you claim less than you might be owed — and withholding instead would
    zero every YR-based deal on every third-party statement. But the row says so.

  * **SSR.** One undifferentiated "SSR Amount", while a deal pays Ancillary per sub-type
    (baggage / meals / seat). There is no honest split, so NOTHING is claimed for it: the
    amount is stored for display and the row says why. This is the repo's own "skipping is
    not passing" applied consistently, and the variance column makes the gap visible
    instead of hiding it.

  * **Declared vs computed.** The statement already prints what the consolidator actually
    paid. Comparing it to what the deal says is the whole point of the exercise, and the
    self-check below is what stops that comparison being made against arithmetic that does
    not close.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import STATEMENT_MODELS
from app.services.commission.calc_row import (
    KIND_ISSUE, KIND_REFUND, KIND_SKIP, BatchInfo, CalcRow, DeclaredAmounts,
)
from app.services.deal_matching import SKIP_CLASS

# ── Transaction-type policy ──────────────────────────────────────────────────
# Shaped like bsp_commission's _SKIP_TXN/_REFUND_TXN, INCLUDING the fall-through: anything
# unrecognised behaves like an issue and says so. Consolidator status vocabularies vary,
# and a whitelist-only issue rule would silently zero a whole file the first time one of
# them wrote "TICKETED" instead of "CONFIRMED".
_REFUND_STATUS = {"REFUNDED", "REFUND", "RFND", "REFUND PROCESSED", "REFUNDED-FULL",
                  "REFUNDED-PARTIAL"}
_SKIP_STATUS = {"CANCELLED", "CANCELED", "CANCEL", "VOID", "VOIDED", "FAILED",
                "PENDING", "HOLD", "ON HOLD", "EXPIRED", "REJECTED"}
_SKIP_REASON = {
    "CANCELLED": "Cancelled booking — not a sale",
    "CANCELED": "Cancelled booking — not a sale",
    "CANCEL": "Cancelled booking — not a sale",
    "VOID": "Voided ticket — not a sale",
    "VOIDED": "Voided ticket — not a sale",
    "FAILED": "Failed booking — not a sale",
    "PENDING": "Booking not ticketed — nothing has been sold yet",
    "HOLD": "Booking on hold — nothing has been sold yet",
    "ON HOLD": "Booking on hold — nothing has been sold yet",
    "EXPIRED": "Booking expired — not a sale",
    "REJECTED": "Booking rejected — not a sale",
}

# A consolidator sells to us, so its statement is priced against a B2B deal, and its
# incentives are earned on the sale — never on a Flown trigger.
STATEMENT_TYPE = "B2B"
INVOICE_TYPE = "Sales"

# What the user can actually do about a withheld third-party row. BSP's advice ("upload the
# TGQ HMPR") is meaningless here: there is no second document to join, only the vendor.
NEEDS_DATA_REMEDY = (
    "This consolidator's statement does not print it. Ask them to include the column, or "
    "narrow the deal so it does not depend on it."
)

# Rounding slack on the vendor's own arithmetic. Paise-level; anything wider would hide a
# real short-payment.
NET_TOLERANCE = 0.05


def _f(data: dict, key: str) -> float | None:
    v = data.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _f0(data: dict, key: str) -> float:
    return _f(data, key) or 0.0


def _iso(v) -> date | None:
    """`data->>'issue_date'` is ISO text after ingest; anything else is not a date."""
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _d(data: dict, key: str) -> date | None:
    """The ingest normalizer writes ISO into `data`; anything else is not a date we trust."""
    raw = (data.get(key) or "").strip() if isinstance(data.get(key), str) else None
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _s(data: dict, key: str) -> str | None:
    v = data.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def net_from_components(data: dict) -> float:
    """Recompute the vendor's Net Amount from the columns it printed.

        Net = Basic + YQ + Other Taxes + SSR + Reschedule
              - Agent Commission - Incentive + TDS
              + Service Charge + SF + GST On SF + Agent Penalty + Cancellation Markup

    Verified against both rows of the real export: 66250 + 23069 + 100 + 18 = 89437, and
    31670 + 21544 - 285.72 + 5.7144 = 52933.9944.
    """
    return (
        _f0(data, "base_fare") + _f0(data, "yq") + _f0(data, "other_taxes")
        + _f0(data, "ssr_amount") + _f0(data, "reschedule_charges")
        - _f0(data, "commission_amount") - _f0(data, "incentive_amount")
        + _f0(data, "tds")
        + _f0(data, "service_charge") + _f0(data, "service_fee") + _f0(data, "gst_on_sf")
        + _f0(data, "agent_penalty") + _f0(data, "cancellation_markup")
    )


# Columns whose SIGN in the Net Amount identity has never been seen against real data —
# every one of them is blank in both sample rows. When the arithmetic fails AND one of
# these is non-zero, the honest answer is "cannot judge", not "the vendor is wrong".
_UNVERIFIED_SIGN_FIELDS = ("reschedule_charges", "agent_penalty", "cancellation_markup")


def build_declared(data: dict) -> DeclaredAmounts:
    """The vendor's own figures, plus whether its arithmetic closes."""
    net = _f(data, "net_amount")
    declared = DeclaredAmounts(
        commission=_f(data, "commission_amount"),
        incentive=_f(data, "incentive_amount"),
        tds=_f(data, "tds"),
        net=net,
    )
    if net is None:
        declared.net_ok = None
        return declared

    computed = net_from_components(data)
    if abs(computed - net) <= NET_TOLERANCE:
        declared.net_ok = True
    elif any(_f0(data, f) for f in _UNVERIFIED_SIGN_FIELDS):
        declared.net_ok = None
    else:
        declared.net_ok = False
    return declared


def classify(data: dict) -> tuple[str, str | None]:
    """(kind, reason) from the statement's own Status column."""
    status = (_s(data, "ticket_status") or "").upper()
    if status in _SKIP_STATUS:
        return KIND_SKIP, _SKIP_REASON.get(status, f"{status} — not a sale")
    if status in _REFUND_STATUS:
        return KIND_REFUND, None
    if not status:
        return KIND_ISSUE, None
    if status not in ("CONFIRMED", "TICKETED", "ISSUED", "OK", "ACTIVE", "COMPLETED"):
        # Treated as a sale, but flagged — see the module note on fall-through.
        return KIND_ISSUE, f"Unrecognised status '{status}' — treated as an issue."
    return KIND_ISSUE, None


def build_calc_row(row, supplier_name: str | None, supplier_id: int | None) -> CalcRow:
    """One `third_party_gds` / `third_party_lcc` row → a CalcRow."""
    data = dict(row.data or {})
    kind, kind_reason = classify(data)

    booking_class = _s(data, "booking_class")
    # The master's spelling, stamped at ingest by services/tp_airline_resolution. The file's
    # own `airline_name` is kept for display but must never reach the matcher: the deal
    # holds the master's spelling and the compare is an equality.
    airline_name = _s(data, "airline_master_name")

    ctx = CalcRow(
        source_row_id=row.id,
        ticket_number=_s(data, "ticket_number"),
        document_number=_s(data, "ticket_number"),
        pnr=_s(data, "pnr") or _s(data, "gds_pnr") or _s(data, "airline_pnr"),
        passenger_name=_s(data, "passenger_name"),
        transaction_type=_s(data, "ticket_status"),
        airline_name=airline_name,
        airline_id=int(data["airline_id"]) if str(data.get("airline_id") or "").isdigit() else None,
        issue_date=_d(data, "issue_date") or _d(data, "booking_date") or _d(data, "transaction_date"),
        travel_date=_d(data, "travel_date"),
        segment_type=_s(data, "segment_type"),
        booking_class=booking_class,
        sector=_s(data, "sector"),
        tour_code=_s(data, "tour_code"),
        fare_amount=_f(data, "base_fare"),
        yq=_f(data, "yq"),
        # No YR column on this export — see the module docstring. Deliberately None, never
        # a share of Other Taxes.
        yr=None,
        # All three None on purpose: the statement gives one combined SSR figure and a deal
        # pays Ancillary per sub-type, so there is no honest split to feed the engine.
        seat_selection=None, excess_baggage=None, meals=None,
        ancillary_amount=_f(data, "ssr_amount"),
        kind=kind,
        kind_reason=kind_reason,
        statement_type=STATEMENT_TYPE,
        invoice_type=INVOICE_TYPE,
        supplier_agency=supplier_name,
        supplier_agency_id=supplier_id,
        declared=build_declared(data),
    )

    if kind_reason:
        ctx.note(kind_reason)

    # Per row, never per statement: another consolidator prints Class, and this one may
    # print it on some lines.
    if not booking_class:
        ctx.skip_criteria.add(SKIP_CLASS)
        ctx._skip_rule_fields.add("class")
        ctx.skipped_labels.append("class")
    if not ctx.sector:
        ctx.skipped_labels.append("sector")
    if not ctx.travel_date:
        ctx.skipped_labels.append("travel_date")

    if data.get("issue_date_source"):
        ctx.note("No ticketing-date column — the Booked Date was used as the issue date, "
                 "so deal validity was tested against that.")
    if data.get("airline_conflict"):
        ctx.note(str(data["airline_conflict"]))
    if ctx.declared and ctx.declared.net_ok is False:
        ctx.note("The statement's own components do not add up to its Net Amount, so the "
                 "variance against it is not meaningful.")

    return ctx


class ThirdPartyAdapter:
    """Loads one third-party batch and normalizes it. One instance per slug."""

    statement_type = STATEMENT_TYPE
    has_declared_amounts = True
    requires_supplier = True
    needs_data_remedy = NEEDS_DATA_REMEDY

    def __init__(self, slug: str, label: str):
        self.source = slug
        self.label = label
        self.model = STATEMENT_MODELS[slug]

    async def list_batches(self, db: AsyncSession, tenant_id: int, user_id: int) -> list[BatchInfo]:
        """One entry per upload, derived with a GROUP BY — these types keep no batch header.

        The period comes from the rows' own `issue_date`, which ingest normalised to ISO
        text; a value that is not a date sorts harmlessly and is dropped on the way out.
        """
        from sqlalchemy import func

        m = self.model
        rows = (await db.execute(
            select(
                m.batch_id, m.source_file,
                func.max(m.uploaded_at).label("uploaded_at"),
                func.count().label("row_count"),
                func.min(m.data["issue_date"].astext).label("period_from"),
                func.max(m.data["issue_date"].astext).label("period_to"),
            )
            .where(m.tenant_id == tenant_id, m.created_by_id == user_id)
            .group_by(m.batch_id, m.source_file)
            .order_by(func.max(m.uploaded_at).desc())
        )).all()
        return [
            BatchInfo(
                batch_id=r.batch_id, source_file=r.source_file, uploaded_at=r.uploaded_at,
                row_count=r.row_count or 0,
                period_from=_iso(r.period_from), period_to=_iso(r.period_to),
            )
            for r in rows
        ]

    async def supplier_for_batch(self, db: AsyncSession, tenant_id: int, batch_id: str):
        """The consolidator declared at upload, or None for a batch that predates it.

        Read off the link row's SNAPSHOT rather than joined to `suppliers`, so a renamed
        vendor cannot silently re-label a run that already happened.
        """
        return (await db.execute(
            select(StatementBatchSupplier).where(
                StatementBatchSupplier.slug == self.source,
                StatementBatchSupplier.tenant_id == tenant_id,
                StatementBatchSupplier.batch_id == batch_id,
            )
        )).scalar_one_or_none()


    async def load_rows(self, db: AsyncSession, tenant_id: int, user_id: int,
                        batch_id: str, row_ids: list[int] | None = None) -> list:
        m = self.model
        conds = [m.batch_id == batch_id, m.tenant_id == tenant_id, m.created_by_id == user_id]
        if row_ids:
            conds.append(m.id.in_(row_ids))
        return list((await db.execute(select(m).where(*conds).order_by(m.id.asc()))).scalars().all())

    async def build_contexts(self, db: AsyncSession, rows: list, tenant_id: int,
                             user_id: int, batch_id: str) -> list[CalcRow]:
        link = await self.supplier_for_batch(db, tenant_id, batch_id)
        name = link.supplier_name if link else None
        supplier_id = link.supplier_id if link else None
        return [build_calc_row(r, name, supplier_id) for r in rows]

    async def cumulative_provider(self, db: AsyncSession, tenant_id: int, user_id: int):
        """None → the engine's default (a scan of uploaded tickets).

        BSP overrides this so slab achievement reflects the airline's own settlement. A
        third-party statement is one consolidator's slice of the year, not the whole of it,
        so summing only its own rows would understate every slab and quietly pay the
        bottom band. The default at least sees the workspace's tickets.
        """
        return None
