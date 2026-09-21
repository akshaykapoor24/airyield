"""Writing `income_board_rows` from whichever store priced the line.

TWO STATEMENTS PER BATCH, BOTH SET-BASED. An INSERT ... SELECT that upserts, then a
DELETE that sweeps orphans. No row is ever loaded into Python and summed in a loop —
that is what /dashboard/income-summary does today and it is the pattern this module
exists to replace. A batch of any size costs two statements.

WHY THE ORPHAN SWEEP IS NOT OPTIONAL. Reprocessing a statement under a new column spec
mints NEW `source_row_id`s for the same documents. A pure upsert would leave the
previous spec's projected rows alive beside the new ones as income that nothing will
ever restate, and the board would double-count the batch with no sign that anything was
wrong. The DELETE ... NOT IN is what makes re-projection actually idempotent.

WHY `first_seen_at` IS EXCLUDED FROM THE UPDATE. It records when a line was first
priced, not when it was last restated. Re-running commission on a six-month-old
statement must not make its income look new.

EVERY SELECT EMITS THE SAME COLUMNS IN THE SAME ORDER, from `_COLUMNS`. The arms differ
in almost every expression but must agree exactly in shape, and a mismatch would be
caught by Postgres only if the types happened to differ — a silently swapped pair of
same-typed columns would just be wrong. `test_income_board` asserts the counts match.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.income_board import (
    DIRECTION_INBOUND, KIND_AIRLINE, KIND_SUPPLIER, PROJECTION_VERSION,
    SOURCE_BSP, SOURCE_LCC_DETAILED, SOURCE_TP_GDS, SOURCE_TP_LCC,
)
from app.services.income_board.dimensions import (
    bsp_segment_sql, jsonb_numeric_sql, segment_sql, ticket_key_sql, txn_class_sql,
)

logger = logging.getLogger(__name__)


# The statement table behind each commission source, joined only to recover a gross
# that `commission_calculations` does not carry for any source.
_SOURCE_TABLES = {
    SOURCE_TP_GDS: "third_party_gds",
    SOURCE_TP_LCC: "third_party_lcc",
    SOURCE_LCC_DETAILED: "lcc_detailed",
}

COMMISSION_SOURCES = tuple(_SOURCE_TABLES)

# The projected shape, in order. The INSERT column list and every arm's SELECT are
# generated from this single tuple so they cannot drift apart.
_COLUMNS = (
    "tenant_id", "created_by_id", "source", "batch_id", "source_row_id",
    "direction", "counterparty_kind",
    "airline_id", "airline_name", "airline_match_by",
    "supplier_id", "supplier_name", "supplier_code", "supplier_branch",
    "supplier_match_by", "vendor_agency_id",
    "issue_date", "issue_ym", "issue_date_source",
    "travel_date", "travel_ym", "travel_date_source", "date_parse_failed",
    "segment", "segment_raw", "booking_class",
    "txn_type", "txn_class",
    "gross_amount", "gross_source", "fare_amount", "yq", "yr", "taxes_total",
    "ancillary_amount",
    "incentive", "iata_commission",
    "declared_commission", "declared_incentive", "declared_tds", "declared_net",
    "declared_net_ok", "variance_total",
    "status", "reason", "skipped_criteria",
    "matched_deal_id", "matched_deal_type", "matched_deal_name", "matched_deal_no",
    "slab_dependent",
    "document_number", "ticket_number", "ticket_key", "pnr", "pax_count",
    "run_id", "engine_version", "projection_version", "projected_at", "first_seen_at",
)

# Everything a re-projection restates. `first_seen_at` is deliberately absent, and so
# are the key columns, which cannot change for a given conflict target.
_UPDATE_COLUMNS = tuple(
    c for c in _COLUMNS
    if c not in ("tenant_id", "created_by_id", "source", "source_row_id", "first_seen_at")
)

_INSERT_COLS = ", ".join(_COLUMNS)
_DO_UPDATE = ", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATE_COLUMNS)

# A deal is slab-based if any of its incentives pays on a slab rather than a fixed
# target. Such a line is not additive across time the way a flat-rate line is, so the
# board marks the months that contain one instead of implying a stable series.
_SLAB_DEPENDENT = """
    EXISTS (SELECT 1 FROM deal_incentives di
             WHERE di.deal_id = {deal_col} AND di.target_based = 'Slab')"""


def _bsp_select() -> str:
    """BSP: priced on its own settlement row, with taxes in a side table.

    The carrier is resolved through `airline_accounting_code` against
    `airlines.iata_numeric_code`, normalised to three digits first because the column is
    String(3) and statements are not consistent about leading zeros. Never on
    `airline_name`: that is free text, and `bsp_statements.airline_name` is a label the
    uploader typed over a settlement that holds many carriers.
    """
    return f"""
        SELECT
            r.tenant_id, r.created_by_id, :source, r.statement_id, r.id,
            :direction, :kind_airline,
            a.id, coalesce(a.name, r.airline_name),
            CASE WHEN a.id IS NOT NULL THEN 'numeric_code' ELSE NULL END,
            -- BSP has no B2B counterparty: the carrier IS the counterparty.
            NULL, NULL, NULL, NULL, NULL, NULL,
            r.issue_date, to_char(r.issue_date, 'YYYY-MM'), NULL,
            -- BSP prints no travel date; it exists only where TGQ HMPR enrichment
            -- supplied one, and that enrichment records whether it was explicit.
            r.enriched_travel_date, to_char(r.enriched_travel_date, 'YYYY-MM'),
            r.enriched_travel_date_source, false,
            {bsp_segment_sql('r.stat')}, r.stat,
            -- Never from BSP itself; only TGQ HMPR knows the class.
            r.enriched_booking_class,
            upper(btrim(coalesce(r.transaction_type, ''))),
            {txn_class_sql('r.transaction_type')},
            -- As printed. Signed already: a refund settles negative.
            r.transaction_amount, 'printed',
            r.fare_amount, tb.yq, tb.yr, tb.taxes_total, NULL,
            -- Carried exactly as stored. NULL stays NULL: it means needs_data.
            r.calculated_incentive, r.iata_commission,
            -- What BSP itself settled, which is the vendor's own claim.
            r.standard_commission_amount, r.supplier_discount_amount, NULL, NULL,
            NULL, NULL,
            coalesce(r.commission_status, 'pending'), r.commission_reason,
            r.skipped_criteria,
            r.matched_deal_id, r.matched_deal_type, r.matched_deal_name, NULL,
            {_SLAB_DEPENDENT.format(deal_col='r.matched_deal_id')},
            r.document_number, r.ticket_number,
            {ticket_key_sql('coalesce(r.document_number, r.ticket_number)')},
            NULL, 1,
            -- BSP does not go through commission_runs.
            NULL, NULL, :ver, now(), now()
        FROM bsp_statement_rows r
        LEFT JOIN airlines a
               ON a.iata_numeric_code = lpad(
                      nullif(regexp_replace(
                          coalesce(r.airline_accounting_code, ''), '[^0-9]', '', 'g'
                      ), ''), 3, '0')
        LEFT JOIN (
            SELECT bsp_row_id,
                   sum(amount) FILTER (WHERE component_code = 'YQ')  AS yq,
                   sum(amount) FILTER (WHERE component_code = 'YR')  AS yr,
                   sum(amount) FILTER (WHERE component_type = 'TAX') AS taxes_total
              FROM bsp_tax_breakups
             WHERE tenant_id = :tid
             GROUP BY bsp_row_id
        ) tb ON tb.bsp_row_id = r.id
        WHERE r.tenant_id = :tid AND r.created_by_id = :uid
          AND r.statement_id = :batch
    """


def _commission_select(source: str) -> str:
    """tp-gds | tp-lcc | lcc-detailed: priced into `commission_calculations`.

    The statement table is joined ONLY to recover a gross, which the calculation row
    does not carry for any source. For third-party that gross lives in JSONB text and
    must be regex-guarded before casting, because services/flat_statement.py
    deliberately keeps unparseable text rather than blanking it.
    """
    tbl = _SOURCE_TABLES[source]
    is_lcc = source == SOURCE_LCC_DETAILED

    if is_lcc:
        gross, gross_src = "s.total", "'printed'"
        # Covers batches uploaded before the airline had to be declared: the calc row
        # may have no airline_id where the statement row now does.
        airline_id = "coalesce(c.airline_id, s.airline_id)"
        date_failed, issue_src = "false", "NULL"
    else:
        gross = jsonb_numeric_sql("s.data->>'total_fare'")
        gross_src = ("CASE WHEN s.data->>'total_fare_source' = 'derived' "
                     "THEN 'derived' ELSE 'printed' END")
        airline_id = "c.airline_id"
        # The ingest stamps this key when a date could not be parsed, so the board can
        # say "undated" rather than implying no sales.
        date_failed = "(s.data ? 'date_parse_failed')"
        issue_src = "s.data->>'issue_date_source'"

    return f"""
        SELECT
            c.tenant_id, c.created_by_id, c.source, c.batch_id, c.id,
            :direction, :kind,
            {airline_id}, coalesce(a.name, c.airline_name),
            CASE WHEN {airline_id} IS NOT NULL THEN 'resolved' ELSE NULL END,
            sbs.supplier_id, sbs.supplier_name, sbs.supplier_code, sbs.supplier_branch,
            c.supplier_match_by, d.vendor_agency_id,
            c.issue_date, to_char(c.issue_date, 'YYYY-MM'), {issue_src},
            c.travel_date, to_char(c.travel_date, 'YYYY-MM'), NULL, {date_failed},
            {segment_sql('c.segment_type')}, c.segment_type, c.booking_class,
            upper(btrim(coalesce(c.transaction_type, ''))),
            {txn_class_sql('c.transaction_type')},
            {gross}, {gross_src},
            c.fare_amount, c.yq, c.yr, NULL, c.ancillary_amount,
            c.incentive, c.iata_commission,
            c.declared_commission, c.declared_incentive, c.declared_tds, c.declared_net,
            c.declared_net_ok, c.variance_total,
            c.status, c.reason, c.skipped_criteria,
            c.matched_deal_id, c.matched_deal_type, c.matched_deal_name,
            c.matched_deal_no,
            {_SLAB_DEPENDENT.format(deal_col='c.matched_deal_id')},
            c.document_number, c.ticket_number,
            {ticket_key_sql('c.ticket_number')},
            c.pnr, 1,
            c.run_id, :engine_version, :ver, now(), now()
        FROM commission_calculations c
        LEFT JOIN {tbl} s
               ON s.id = c.source_row_id
        LEFT JOIN airlines a
               ON a.id = {airline_id}
        LEFT JOIN deals d
               ON d.id = c.matched_deal_id
        -- LEFT, and the tenant predicate is ours to add: the unique constraint on
        -- statement_batch_suppliers is (slug, batch_id) only. A batch uploaded before
        -- that link existed has no row, and those must land in a visible
        -- "Unattributed consolidator" bucket rather than be dropped by an inner join.
        LEFT JOIN statement_batch_suppliers sbs
               ON sbs.slug = c.source
              AND sbs.batch_id = c.batch_id
              AND sbs.tenant_id = c.tenant_id
        WHERE c.tenant_id = :tid AND c.created_by_id = :uid
          AND c.source = :source AND c.batch_id = :batch
    """


async def clear_batch(
    db: AsyncSession, *, tenant_id: int, user_id: int, source: str, batch_id: str
) -> int:
    """Drop a batch's projected rows. Called when the batch itself is deleted.

    Explicit, because `source_row_id` carries no foreign key — exactly as
    `commission_calculations` is cleared today.
    """
    res = await db.execute(
        text("""
            DELETE FROM income_board_rows
             WHERE tenant_id = :tid AND created_by_id = :uid
               AND source = :source AND batch_id = :batch
        """),
        {"tid": tenant_id, "uid": user_id, "source": source, "batch": batch_id},
    )
    return res.rowcount or 0


async def project_batch(
    db: AsyncSession, *, tenant_id: int, user_id: int, source: str, batch_id: str,
    engine_version: str | None = None,
) -> int:
    """Project one batch onto the board. Returns rows written. Idempotent.

    `source` selects the arm: SOURCE_BSP reads the settlement rows, everything in
    COMMISSION_SOURCES reads the calculation ledger.
    """
    if source == SOURCE_BSP:
        select_sql = _bsp_select()
        params = {
            "tid": tenant_id, "uid": user_id, "batch": batch_id,
            "source": SOURCE_BSP, "direction": DIRECTION_INBOUND,
            "kind_airline": KIND_AIRLINE, "ver": PROJECTION_VERSION,
        }
        id_sql = ("SELECT r.id FROM bsp_statement_rows r "
                  "WHERE r.tenant_id = :tid AND r.created_by_id = :uid "
                  "AND r.statement_id = :batch")
        id_params = {"tid": tenant_id, "uid": user_id, "batch": batch_id}
    elif source in _SOURCE_TABLES:
        select_sql = _commission_select(source)
        params = {
            "tid": tenant_id, "uid": user_id, "batch": batch_id, "source": source,
            "direction": DIRECTION_INBOUND,
            # lcc-detailed is an airline deal; the two third-party sources are B2B.
            "kind": KIND_AIRLINE if source == SOURCE_LCC_DETAILED else KIND_SUPPLIER,
            "engine_version": engine_version, "ver": PROJECTION_VERSION,
        }
        id_sql = ("SELECT c.id FROM commission_calculations c "
                  "WHERE c.tenant_id = :tid AND c.created_by_id = :uid "
                  "AND c.source = :source AND c.batch_id = :batch")
        id_params = {"tid": tenant_id, "uid": user_id, "source": source,
                     "batch": batch_id}
    else:
        raise ValueError(f"income_board: no projection arm for source {source!r}")

    res = await db.execute(
        text(f"""
            INSERT INTO income_board_rows ({_INSERT_COLS})
            {select_sql}
            ON CONFLICT (tenant_id, created_by_id, source, source_row_id)
            DO UPDATE SET {_DO_UPDATE}
        """),
        params,
    )
    written = res.rowcount or 0

    # The re-spec orphan sweep. A reprocessed batch mints new source_row_ids; without
    # this, the previous spec's rows survive as income nothing will ever restate.
    swept = await db.execute(
        text(f"""
            DELETE FROM income_board_rows
             WHERE tenant_id = :tid AND created_by_id = :uid
               AND source = :source AND batch_id = :batch
               AND source_row_id NOT IN ({id_sql})
        """),
        {**id_params, "source": source},
    )
    if swept.rowcount:
        logger.info("income_board: swept %s orphaned rows for %s/%s",
                    swept.rowcount, source, batch_id)

    logger.info("income_board: projected %s rows for %s/%s", written, source, batch_id)
    return written
