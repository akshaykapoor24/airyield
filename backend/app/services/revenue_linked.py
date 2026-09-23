"""The statements that restate a sale rather than adding to one.

Six types across three storage shapes, and none of them may ever reach a sale total:

  TGQ HMPR          the GDS's record of tickets BSP settles. Same tickets.
  ADM / ACM / RA    memos, which count through the BSP ADMA/ACMA row they were raised
                    against — `report_download/columns.COUNTS_IN_NET_RULES` says so.
  LCC DI            a deposit ledger. Money moving into an account, not a sale.
  LCC Divided PNR   a link between two PNRs.
  LCC Flown Report  the same bookings as LCC Detailed, counted when they flew.
  LCC CTA/BTA       a lodged-account settlement of bookings already on another statement.

They are still worth seeing, and airline-wise, which is what this module is for: "Air
India — 1,840 TGQ tickets, ₹1.2 L of ADM, ₹2.9 Cr flown" is the context a sale figure is
read against. Each one is reported under ITS OWN measure with its own name — flown
revenue, deposits, memo value — never under the word "sale".

READ LIVE, NOT PROJECTED, and that is a deliberate difference from the six sale types.
A projection earns its cost by making a figure cheap to slice a dozen ways; these are
read once, as a side panel, and they would otherwise be three more arm families
(`adjustment` for the memos, `_SplitMixin` for TGQ, `_NormalizedBase` for the ledgers)
carrying rows that can never enter a total. The `counts_in_net` guarantee they need is
the trivial one — they are simply not in `SALE_SOURCES`.

EVERY AMOUNT IS REGEX-GUARDED BEFORE CASTING. These tables hold the vendor's own text:
`flat_statement` deliberately keeps an unparseable cell rather than blanking it, and the
memo tables are `Text` in every column. An unguarded `::numeric` would raise on one bad
cell and take the whole panel down.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.income_board.dimensions import jsonb_numeric_sql
from app.services.report_download.registry import SOURCE_BY_KEY

#: How a linked type names its carrier. The three are genuinely different questions.
BY_NUMERIC_JSON = "numeric_json"   # a 3-digit accounting code inside `data`
BY_NUMERIC_COL = "numeric_col"     # a 3-digit accounting code in a real column
BY_BATCH = "batch"                 # nothing in the file; declared at upload


@dataclass(frozen=True)
class LinkedSource:
    """One linked statement type and the one figure it is actually about."""
    key: str
    table: str
    #: The measure, and what to call it. NOT "sale" — that word is reserved for the six
    #: types whose gross is the agency's own sale.
    amount_sql: str
    measure_label: str
    airline_by: str
    #: Only for BY_NUMERIC_*: where the accounting code lives.
    code_expr: str | None = None
    #: TGQ stores the file's declared grand-total line as a row.
    exclude_totals: bool = False


LINKED_SOURCES: tuple[LinkedSource, ...] = (
    LinkedSource(
        key="tgq-hmpr", table="tgq_hmpr",
        amount_sql=jsonb_numeric_sql("s.data->>'total_fare'"),
        measure_label="Ticketed fare", airline_by=BY_NUMERIC_JSON,
        # Lifted out of the ticket number at ingest (statement_spec._TGQ_TICKET_NO).
        code_expr="s.data->>'airline_code'", exclude_totals=True,
    ),
    LinkedSource(
        key="adm", table="airline_adm", amount_sql=jsonb_numeric_sql("s.amount"),
        measure_label="Debit memos", airline_by=BY_NUMERIC_COL,
        code_expr="s.airline_code",
    ),
    LinkedSource(
        key="acm", table="airline_acm", amount_sql=jsonb_numeric_sql("s.amount"),
        measure_label="Credit memos", airline_by=BY_NUMERIC_COL,
        code_expr="s.airline_code",
    ),
    LinkedSource(
        key="ra", table="airline_ra", amount_sql=jsonb_numeric_sql("s.amount"),
        measure_label="Refund applications", airline_by=BY_NUMERIC_COL,
        code_expr="s.airline_code",
    ),
    LinkedSource(
        key="lcc-flown-report", table="lcc_flown_report",
        amount_sql=jsonb_numeric_sql("s.data->>'total_fare'"),
        measure_label="Flown revenue", airline_by=BY_BATCH,
    ),
    LinkedSource(
        key="lcc-di", table="lcc_di",
        amount_sql=jsonb_numeric_sql("s.data->>'amount'"),
        measure_label="Deposits", airline_by=BY_BATCH,
    ),
    LinkedSource(
        key="lcc-cta-bta", table="lcc_cta_bta",
        amount_sql=jsonb_numeric_sql("s.data->>'total_amount'"),
        measure_label="Lodged settlement", airline_by=BY_BATCH,
    ),
    LinkedSource(
        key="lcc-divided-pnr", table="lcc_divided_pnr",
        amount_sql=jsonb_numeric_sql("s.data->>'payment_amount'"),
        measure_label="Split payments", airline_by=BY_BATCH,
    ),
)

# The four LCC ledgers name no carrier in the file, so the uploader declares it from
# their Airline Master and the link lives in `statement_batch_airline_ids`. Keyed
# (slug, batch_id) with no FK on the batch, because these types have no batch header
# table at all — a "batch" is a shared batch_id string across rows.
_BATCH_AIRLINE_JOIN = """
        LEFT JOIN statement_batch_airline_ids sba
               ON sba.slug = :slug AND sba.batch_id = s.batch_id
              AND sba.tenant_id = s.tenant_id
        LEFT JOIN tenant_airlines ta ON ta.id = sba.tenant_airline_id
"""

_NUMERIC_AIRLINE_JOIN = """
        LEFT JOIN airlines a
               ON a.iata_numeric_code = lpad(nullif(regexp_replace(
                      coalesce({code}, ''), '[^0-9]', '', 'g'), ''), 3, '0')
"""


def _airline_expr(src: LinkedSource) -> tuple[str, str]:
    """(airline_id expression, the joins it needs)."""
    if src.airline_by == BY_BATCH:
        return "ta.airline_id", _BATCH_AIRLINE_JOIN
    return "a.id", _NUMERIC_AIRLINE_JOIN.format(code=src.code_expr)


async def linked_totals(
    db: AsyncSession, *, tenant_id: int, user_id: int | None,
    airline_id: int | None = None,
) -> list[dict]:
    """Row counts and each type's own measure. `user_id=None` reads the whole workspace.

    `airline_id=None` returns the workspace total for every type; an id narrows to that
    carrier, which is what the drill-down shows beside its sale.
    """
    out: list[dict] = []
    for src in LINKED_SOURCES:
        airline_col, joins = _airline_expr(src)
        conds = ["s.tenant_id = :tid"]
        params: dict = {"tid": tenant_id, "slug": src.key}
        if user_id is not None:
            conds.append("s.created_by_id = :uid")
            params["uid"] = user_id
        if src.exclude_totals:
            conds.append("s.is_total = false")
        if airline_id is not None:
            conds.append(f"{airline_col} = :aid")
            params["aid"] = airline_id

        sql = f"""
            SELECT count(*), sum({src.amount_sql})
              FROM {src.table} s
              {joins}
             WHERE {' AND '.join(conds)}
        """
        rows, amount = (await db.execute(text(sql), params)).one()
        if not rows:
            continue
        meta = SOURCE_BY_KEY[src.key]
        out.append({
            "source": src.key,
            "label": meta.sheet_title,
            "category": meta.category,
            "rows": rows,
            "measure_label": src.measure_label,
            "measure": None if amount is None else float(amount),
            # Built without a real sample, so the figure carries the caveat on screen
            # rather than in a comment nobody reading the board will see.
            "schema_unverified": meta.schema_unverified,
        })
    return out
