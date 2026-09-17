"""One adapter per source: the only place a vendor table's own vocabulary is spoken.

Three shapes, because the sources genuinely differ:

  * `FlatJsonAdapter` — tp-gds, tp-lcc, ndc. Amounts live as STRINGS in a JSONB `data`
    blob under names the statement spec fixed. A field map is the whole adapter.
  * NDC additionally has `projected_ticket_id`, so it prefers the foreign key.
  * `LccDetailedAdapter` — typed columns, and NO TICKET NUMBER ANYWHERE. It is keyed on
    PNRs (`record_locator`), so its only honest link to a sale is the projection FK.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lcc_detailed import LccDetailed
from app.models.statement_row import STATEMENT_MODELS
from app.services.reconciliation.buy_row import BuyRow, to_decimal


def _norm(s) -> str | None:
    """Python mirror of `bsp_reconciliation.norm_tn` — kept identical on purpose.

    Imported rather than redefined would be better still, but that module imports the BSP
    models, and pulling the whole BSP statement schema into every reconciliation run to
    borrow a six-line regex is a worse trade. The two are tested against each other.
    """
    import re
    if not s:
        return None
    core = re.sub(r"[^0-9A-Za-z]", "", str(s))
    core = core.lstrip("0") or "0"
    return core.upper() or None


def _split_joined(value: str | None) -> tuple[str | None, str | None]:
    """Reuse the parser the ticket ingest uses, so the two can never disagree."""
    from app.services.sector_split import split_ticket_no
    return split_ticket_no(value)


def _iso_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _s(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


@dataclass(frozen=True)
class FieldMap:
    """Which `data` key holds each money field, and each identity field, for one source.

    A None means the source does not print it. That is reported as "not comparable", never
    as zero — a deal-breaking difference when a statement simply has no YR column and the
    alternative would be to claim the vendor charged nothing for it.
    """
    fare: str | None
    yq: str | None
    yr: str | None
    # EVERY tax key this source prints, summed into one `tax` figure — not a single column.
    #
    # This is not tidiness, it is the only comparison that holds. A consolidator's GDS
    # export puts the whole tax bill in `other_taxes` and leaves `yq` at 0 on one ticket
    # while filling `yq` on the next; the ticket file always splits the same money across
    # `sell_tax_yq`, `sale_yr` and `other_tax`. Compared column-to-column those disagree on
    # almost every row while the totals agree exactly — verified on ticket 2354848358656,
    # where the vendor's single `other_taxes` of 23,069 is the customer's 2,802 + 17,031 +
    # 3,236. `yq` and `yr` are still reported on their own lines as components.
    tax_parts: tuple[str, ...]
    gross: str | None
    commission: str | None
    net: str | None

    ticket_number: str | None
    ticket_prefix: str | None
    airline_name: str | None
    airline_code: str | None
    issue_date: tuple[str, ...]
    pax_name: str | None
    sector: str | None


# ── tp-gds ───────────────────────────────────────────────────────────────────
# The one source verified against real data on both sides. `ticket_prefix` is separate
# here and MUST be prepended — see buy_row's module docstring.
TP_GDS_MAP = FieldMap(
    fare="base_fare", yq="yq", yr=None, tax_parts=("yq", "other_taxes"),
    gross="total_fare", commission="commission_amount", net="net_amount",
    ticket_number="ticket_number", ticket_prefix="ticket_prefix",
    airline_name="airline_master_name", airline_code="airline_code",
    issue_date=("issue_date", "booking_date", "transaction_date"),
    pax_name="passenger_name", sector="sector",
)

# ── tp-lcc ───────────────────────────────────────────────────────────────────
# No `yq` and no `ticket_prefix` column in the spec, so both are None rather than guessed.
# The spec itself is flagged speculative in flat_statement.py — no real export has been
# supplied — so these names are the spec's, not a real file's.
TP_LCC_MAP = FieldMap(
    fare="base_fare", yq=None, yr=None, tax_parts=("taxes", "other_taxes"),
    gross="total_fare", commission="commission_amount", net="net_amount",
    ticket_number="ticket_number", ticket_prefix=None,
    airline_name="airline_master_name", airline_code="airline_code",
    issue_date=("issue_date", "booking_date", "transaction_date"),
    pax_name="passenger_name", sector="sector",
)

# ── ndc ──────────────────────────────────────────────────────────────────────
# An NDC export prints no commission of any kind, so `commission` is None. `payment_amount`
# is the settled figure and stands in for net.
NDC_MAP = FieldMap(
    # NDC prints a real `total_tax`, so that one key IS the total — no summing needed.
    fare="basic_fare", yq="yq_tax", yr="yr_tax", tax_parts=("total_tax",),
    gross="total_fare", commission=None, net="payment_amount",
    ticket_number="document_no", ticket_prefix=None,
    airline_name="airline", airline_code="airline_iata_code",
    issue_date=("date_of_issue", "date_of_booking"),
    pax_name="passenger_name", sector="sectors",
)


class FlatJsonAdapter:
    """Any source whose row is a JSONB `data` blob of statement-spec field names."""

    joins_by_ticket = True

    def __init__(self, source: str, label: str, fmap: FieldMap, *,
                 uses_projection: bool = False):
        self.source = source
        self.label = label
        self.map = fmap
        self.model = STATEMENT_MODELS[source]
        # True when the model carries `_BillingMixin.projected_ticket_id`, which is an
        # authoritative link and beats any ticket-number match.
        self.uses_projection = uses_projection

    async def list_batches(self, db: AsyncSession, tenant_id: int, user_id: int) -> list[dict]:
        m = self.model
        rows = (await db.execute(
            select(m.batch_id, m.source_file, func.count().label("n"),
                   func.max(m.uploaded_at).label("uploaded_at"))
            .where(m.tenant_id == tenant_id, m.created_by_id == user_id)
            .group_by(m.batch_id, m.source_file)
            .order_by(func.max(m.uploaded_at).desc())
        )).all()
        return [{"batch_id": r.batch_id, "source_file": r.source_file, "row_count": r.n or 0}
                for r in rows]

    async def load_buy_rows(self, db: AsyncSession, tenant_id: int, user_id: int,
                            batch_id: str | None = None) -> list[BuyRow]:
        m = self.model
        conds = [m.tenant_id == tenant_id, m.created_by_id == user_id]
        if batch_id:
            conds.append(m.batch_id == batch_id)
        rows = (await db.execute(select(m).where(*conds).order_by(m.id.asc()))).scalars().all()
        return [self._build(r) for r in rows]

    def _build(self, row) -> BuyRow:
        data = dict(row.data or {})
        fm = self.map
        notes: list[str] = []

        def money(key: str | None):
            if key is None:
                return None
            raw = data.get(key)
            val = to_decimal(raw)
            if val is None and raw not in (None, ""):
                notes.append(f"'{key}' was {raw!r}, which is not a number — not compared.")
            return val

        def tax_total():
            """Sum of every tax key the source prints — None only when it prints none.

            A key that is absent contributes nothing; a key present but unparseable has
            already been noted by `money`, and is likewise skipped rather than counted as
            zero."""
            parts = [money(k) for k in fm.tax_parts]
            present = [p for p in parts if p is not None]
            return sum(present) if present else None

        tn = _s(data.get(fm.ticket_number)) if fm.ticket_number else None
        prefix = _s(data.get(fm.ticket_prefix)) if fm.ticket_prefix else None
        # Some exports still write the two joined into one cell. Splitting fails closed and
        # is idempotent, so a value already bare comes back unchanged.
        if tn and not prefix:
            split_code, split_serial = _split_joined(tn)
            if split_code:
                prefix, tn = split_code, split_serial
        # Zero-padded because the file writes Iberia's 075 as "75"; the prefix is compared,
        # not concatenated, so the two spellings have to agree.
        prefix = prefix.zfill(3) if prefix else None

        issue = None
        for k in fm.issue_date:
            issue = _iso_date(data.get(k))
            if issue:
                break

        return BuyRow(
            source_row_id=row.id,
            batch_id=row.batch_id,
            projected_ticket_id=(getattr(row, "projected_ticket_id", None)
                                 if self.uses_projection else None),
            ticket_key=_norm(tn),
            ticket_prefix=prefix,
            ticket_number=tn,
            # The airline master's spelling where ingest resolved one, else the file's.
            airline_name=(_s(data.get(fm.airline_name)) if fm.airline_name else None)
                         or _s(data.get("airline_name")),
            airline_code=_s(data.get(fm.airline_code)) if fm.airline_code else None,
            issue_date=issue,
            pax_name=_s(data.get(fm.pax_name)) if fm.pax_name else None,
            sector=_s(data.get(fm.sector)) if fm.sector else None,
            amounts={
                "fare": money(fm.fare), "yq": money(fm.yq), "yr": money(fm.yr),
                "tax": tax_total(), "gross": money(fm.gross),
                "commission": money(fm.commission), "net": money(fm.net),
            },
            notes=notes,
        )


class LccDetailedAdapter:
    """LCC Detailed — typed columns, and no ticket number to join on.

    An IndiGo-style detailed export is keyed on PNRs (`record_locator`), not documents. It
    therefore CANNOT be matched to a sale by ticket number, and guessing from a PNR against
    `uploaded_tickets.gds_pnr` would pair a whole booking with one passenger's ticket. The
    only honest link is `projected_ticket_id`, written by the billing projection — which is
    authoritative, because the ticket was created FROM this row.

    A row with no projection is reported `buy_only` with a note saying why, rather than
    quietly dropped.
    """

    source = "lcc-detailed"
    label = "LCC Detailed"
    joins_by_ticket = False

    async def list_batches(self, db: AsyncSession, tenant_id: int, user_id: int) -> list[dict]:
        m = LccDetailed
        rows = (await db.execute(
            select(m.batch_id, func.count().label("n"))
            .where(m.tenant_id == tenant_id, m.created_by_id == user_id)
            .group_by(m.batch_id)
        )).all()
        return [{"batch_id": r.batch_id, "source_file": None, "row_count": r.n or 0}
                for r in rows]

    async def load_buy_rows(self, db: AsyncSession, tenant_id: int, user_id: int,
                            batch_id: str | None = None) -> list[BuyRow]:
        m = LccDetailed
        conds = [m.tenant_id == tenant_id, m.created_by_id == user_id]
        if batch_id:
            conds.append(m.batch_id == batch_id)
        rows = (await db.execute(select(m).where(*conds).order_by(m.id.asc()))).scalars().all()

        out: list[BuyRow] = []
        for r in rows:
            notes: list[str] = []
            if r.projected_ticket_id is None:
                notes.append(
                    "This statement prints no ticket number, so a sale can only be found "
                    "through the billing projection — and this row has not been projected "
                    "into a ticket yet."
                )
            out.append(BuyRow(
                source_row_id=r.id,
                batch_id=r.batch_id,
                projected_ticket_id=r.projected_ticket_id,
                ticket_key=None,
                ticket_prefix=None,
                ticket_number=r.record_locator,
                airline_name=r.airline_name,
                airline_code=r.airline_code,
                issue_date=_iso_date(r.booking_date or r.transaction_date),
                pax_name=r.name or r.name1,
                sector=None,
                amounts={
                    "fare": to_decimal(r.base_fare),
                    "yq": None,
                    "yr": None,
                    "tax": to_decimal(r.taxes_total),
                    "gross": to_decimal(r.total),
                    # An LCC detailed export carries no commission column at all.
                    "commission": None,
                    "net": to_decimal(r.total),
                },
                notes=notes,
            ))
        return out


TP_GDS_ADAPTER = FlatJsonAdapter("tp-gds", "Third Party · GDS", TP_GDS_MAP)
TP_LCC_ADAPTER = FlatJsonAdapter("tp-lcc", "Third Party · LCC", TP_LCC_MAP)
NDC_ADAPTER = FlatJsonAdapter("ndc", "NDC", NDC_MAP, uses_projection=True)
LCC_DETAILED_ADAPTER = LccDetailedAdapter()
