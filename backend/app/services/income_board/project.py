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
    SOURCE_BSP, SOURCE_LCC_DETAILED, SOURCE_NDC, SOURCE_TP_API, SOURCE_TP_GDS,
    SOURCE_TP_LCC,
)
from app.services.income_board.dimensions import (
    TP_API_ALIAS, bsp_segment_sql, counts_in_net_sql, date_sql, doc_key_sql,
    iso_date_sql, jsonb_decimal_sql, jsonb_numeric_sql, ndc_is_ancillary_sql,
    ndc_is_refund_sql, segment_sql, ticket_key_sql, tp_api_bill_lateral,
    tp_api_product_sql, txn_class_sql,
)
# `markup_categories` and not `report_download.columns.PRODUCT_AIR`, and the difference
# is not cosmetic. The report's vocabulary is display labels — "Air", "Hotel" — while
# tp-api's product comes from `markup_categories.category_slug`, which is lower-case
# ('air', 'hotel', 'train'). Mixing them put BOTH 'Air' and 'air' on the board and split
# one product across two rows of the same card. One vocabulary, and it is the slug:
# billing groups on it, and a label belongs to the screen rather than to the column.
from app.services.markup_categories import CATEGORY_AIR

logger = logging.getLogger(__name__)


# The statement table behind each commission source, joined only to recover a gross
# that `commission_calculations` does not carry for any source.
_SOURCE_TABLES = {
    SOURCE_TP_GDS: "third_party_gds",
    SOURCE_TP_LCC: "third_party_lcc",
    SOURCE_LCC_DETAILED: "lcc_detailed",
}

# The sources that have a commission adapter in services/commission/__init__.py. NOT the
# same list as "sources this module projects", and the two must not be conflated: ndc and
# tp-api are projected for their sale and have no adapter at all, so folding them in here
# would tell api/v1/income_board's freshness check to look for commission runs that can
# never exist and report every batch as "never projected".
COMMISSION_SOURCES = tuple(_SOURCE_TABLES)

# The two sources that carry sale and nothing prices them. `services/commission/__init__`
# has no adapter for either: an airline's own NDC export settles directly with the
# carrier, and an aggregator's hotel and train lines have no airline deal to price
# against. They project with `priced = false` and a NULL incentive.
_SALE_ONLY_TABLES = {
    SOURCE_NDC: "ndc",
    SOURCE_TP_API: "third_party_api",
}

# Everything `project_batch` has an arm for. BSP is here and not in COMMISSION_SOURCES
# for the mirror of the same reason: it is priced by its own engine, not by a registered
# adapter.
PROJECTED_SOURCES = (SOURCE_BSP, *COMMISSION_SOURCES, *_SALE_ONLY_TABLES)

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
    "txn_type", "txn_class", "product",
    "counts_in_net", "counts_in_net_reason",
    "currency",
    "gross_amount", "gross_source", "fare_amount", "yq", "yr", "taxes_total",
    "ancillary_amount",
    "incentive", "iata_commission", "incentive_breakdown",
    "declared_commission", "declared_incentive", "declared_tds", "declared_net",
    "declared_net_ok", "variance_total",
    "priced", "status", "reason", "skipped_criteria",
    "matched_deal_id", "matched_deal_type", "matched_deal_name", "matched_deal_no",
    "slab_dependent",
    "document_number", "ticket_number", "ticket_key", "doc_code", "doc_serial",
    "pnr", "pax_count",
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


def _j(field: str, alias: str = "s") -> str:
    """One `data` key off the statement row, as SQL. Keeps the quoting in one place."""
    return f"{alias}.data->>'{field}'"


def _bsp_select() -> str:
    """BSP: priced on its own settlement row, with taxes in a side table.

    The carrier is resolved through `airline_accounting_code` against
    `airlines.iata_numeric_code`, normalised to three digits first because the column is
    String(3) and statements are not consistent about leading zeros. Never on
    `airline_name`: that is free text, and `bsp_statements.airline_name` is a label the
    uploader typed over a settlement that holds many carriers.

    THIS ARM ALREADY PROJECTED UNPRICED ROWS — it reads the settlement rows themselves,
    not a calculation ledger, so a BSP statement that was uploaded and never costed has
    always landed here with a NULL incentive. What is new is that it now SAYS so:
    `priced` is the row's own `commission_calculated_at`, which separates "nobody has run
    commission on this" from "commission ran and matched nothing".
    """
    counts, counts_reason = counts_in_net_sql(SOURCE_BSP, "r")
    doc_code, doc_serial = doc_key_sql(
        "coalesce(r.document_number, r.ticket_number)", "r.airline_accounting_code")
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
            {txn_class_sql(SOURCE_BSP, 'r.transaction_type')},
            '{CATEGORY_AIR}',
            -- The settlement file itself; every row of it counts.
            {counts}, {counts_reason},
            -- BSP rows carry no currency of their own: it is printed once on the summary
            -- header. mappers/bsp.py assumes INR and flags CURRENCY_ASSUMED; this assumes
            -- the same thing so the two cannot disagree about a total.
            'INR',
            -- As printed. Signed already: a refund settles negative.
            r.transaction_amount, 'printed',
            r.fare_amount, tb.yq, tb.yr, tb.taxes_total, NULL,
            -- Carried exactly as stored. NULL stays NULL: it means needs_data.
            r.calculated_incentive, r.iata_commission, r.incentive_breakdown,
            -- What BSP itself settled, which is the vendor's own claim.
            r.standard_commission_amount, r.supplier_discount_amount, NULL, NULL,
            NULL, NULL,
            (r.commission_calculated_at IS NOT NULL),
            coalesce(r.commission_status, 'pending'), r.commission_reason,
            r.skipped_criteria,
            r.matched_deal_id, r.matched_deal_type, r.matched_deal_name, NULL,
            {_SLAB_DEPENDENT.format(deal_col='r.matched_deal_id')},
            r.document_number, r.ticket_number,
            {ticket_key_sql('coalesce(r.document_number, r.ticket_number)')},
            {doc_code}, {doc_serial},
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


def _statement_select(source: str) -> str:
    """tp-gds | tp-lcc | lcc-detailed, driven by the STATEMENT table.

    THE DIRECTION OF THIS JOIN IS THE POINT, and it used to be the other way round. The
    arm read `commission_calculations` and reached back to the statement only to recover
    a gross, so a batch nobody had priced contributed nothing — on the income board that
    was honest, but on a revenue board "you uploaded it and never costed it" renders as
    "you sold nothing", which is a different and much worse claim. Reading the statement
    and LEFT JOINing the calculation projects every line and lets `priced` say which
    half it is in.

    `source_row_id` MOVED WITH IT, from the calculation id to the statement row id, and
    that fixes a live bug rather than causing one. `runner._upsert` deletes and re-inserts
    the calculations on every run, so their ids change every time; the projection's
    conflict key therefore missed, inserted fresh rows and let the orphan sweep delete
    the old ones — silently resetting `first_seen_at`, the one thing this module's header
    spends a paragraph insisting must survive a re-run. Keyed on the statement row, the
    upsert lands in place. The remap is injective: `commission_calculations` is already
    UNIQUE on (tenant, user, source, source_row_id).

    Where the calculation is absent, every dimension falls back to the statement's own
    columns. The money does not: `incentive` stays NULL, because nothing has been
    claimed and a zero would say something else.
    """
    tbl = _SOURCE_TABLES[source]
    is_lcc = source == SOURCE_LCC_DETAILED
    counts, counts_reason = counts_in_net_sql(source, "s")

    if is_lcc:
        gross, gross_src = "s.total", "'printed'"
        # Covers batches uploaded before the airline had to be declared: the calc row
        # may have no airline_id where the statement row now does.
        airline_id = "coalesce(c.airline_id, s.airline_id)"
        airline_name = "coalesce(a.name, c.airline_name, s.airline_name)"
        date_failed, issue_src = "false", "NULL"
        issue_date = ("coalesce(c.issue_date, s.booking_date::date, "
                      "s.transaction_date::date)")
        travel_date = "coalesce(c.travel_date, s.departure_date)"
        segment_raw = ("coalesce(c.segment_type, CASE WHEN s.international IS NULL "
                       "THEN NULL WHEN s.international THEN 'International' "
                       "ELSE 'Domestic' END)")
        # An LCC issues no ticket, so there is no document to link on — see
        # report_download/mappers/lcc.py. NULL rather than the record locator: a PNR is
        # not a document number and must not be matched against one.
        booking_class = "c.booking_class"
        txn_raw = "coalesce(c.transaction_type, s.bill_kind, s.payment_status)"
        document_no = "coalesce(c.document_number, s.record_locator)"
        ticket_no = ("coalesce(c.ticket_number, s.record_locator, "
                     "s.gds_record_locator)")
        pnr = "coalesce(c.pnr, s.record_locator, s.gds_record_locator)"
        currency = "coalesce(s.currency_code, 'INR')"
        doc_code, doc_serial = "NULL", "NULL"
        fare = "coalesce(c.fare_amount, s.base_fare)"
        taxes_total = "s.taxes_total"
        pax = "coalesce(s.pax_count, 1)"
    else:
        gross = jsonb_numeric_sql("s.data->>'total_fare'")
        gross_src = ("CASE WHEN s.data->>'total_fare_source' = 'derived' "
                     "THEN 'derived' ELSE 'printed' END")
        # tp_airline_resolution stamps `airline_id` into `data` at ingest, so an unpriced
        # third-party row already knows its carrier. Guarded cast: the value is text and
        # a stamp that failed left the key absent rather than blank.
        stamped = jsonb_numeric_sql("s.data->>'airline_id'")
        airline_id = f"coalesce(c.airline_id, ({stamped})::int)"
        airline_name = ("coalesce(a.name, c.airline_name, "
                        "s.data->>'airline_master_name', s.data->>'airline_name')")
        # The ingest stamps this key when a date could not be parsed, so the board can
        # say "undated" rather than implying no sales.
        date_failed = "(s.data ? 'date_parse_failed')"
        issue_src = "s.data->>'issue_date_source'"
        issue_date = "coalesce(c.issue_date, " + iso_date_sql(_j("issue_date")) + ")"
        travel_date = "coalesce(c.travel_date, " + iso_date_sql(_j("travel_date")) + ")"
        segment_raw = "coalesce(c.segment_type, s.data->>'segment_type')"
        booking_class = "coalesce(c.booking_class, s.data->>'booking_class')"
        txn_raw = "coalesce(c.transaction_type, s.data->>'ticket_status')"
        document_no = "coalesce(c.document_number, s.data->>'ticket_number')"
        ticket_no = "coalesce(c.ticket_number, s.data->>'ticket_number')"
        pnr = "coalesce(c.pnr, s.data->>'pnr', s.data->>'airline_pnr')"
        currency = "coalesce(nullif(btrim(s.data->>'currency'), ''), 'INR')"
        doc_code, doc_serial = doc_key_sql(
            "coalesce(c.ticket_number, s.data->>'ticket_number')",
            "s.data->>'ticket_prefix'")
        fare = "coalesce(c.fare_amount, " + jsonb_numeric_sql(_j("base_fare")) + ")"
        taxes_total = jsonb_numeric_sql(_j("taxes"))
        pax = "1"

    return f"""
        SELECT
            s.tenant_id, s.created_by_id, :source, s.batch_id, s.id,
            :direction, :kind,
            {airline_id}, {airline_name},
            CASE WHEN {airline_id} IS NOT NULL THEN 'resolved' ELSE NULL END,
            sbs.supplier_id, sbs.supplier_name, sbs.supplier_code, sbs.supplier_branch,
            c.supplier_match_by, d.vendor_agency_id,
            {issue_date}, to_char({issue_date}, 'YYYY-MM'), {issue_src},
            {travel_date}, to_char({travel_date}, 'YYYY-MM'), NULL, {date_failed},
            {segment_sql(segment_raw)}, {segment_raw}, {booking_class},
            upper(btrim(coalesce({txn_raw}, ''))),
            {txn_class_sql(source, txn_raw)},
            '{CATEGORY_AIR}',
            {counts}, {counts_reason},
            {currency},
            {gross}, {gross_src},
            {fare}, c.yq, c.yr, {taxes_total}, c.ancillary_amount,
            c.incentive, c.iata_commission, c.incentive_breakdown,
            c.declared_commission, c.declared_incentive, c.declared_tds, c.declared_net,
            c.declared_net_ok, c.variance_total,
            (c.id IS NOT NULL), coalesce(c.status, 'unpriced'), c.reason,
            c.skipped_criteria,
            c.matched_deal_id, c.matched_deal_type, c.matched_deal_name,
            c.matched_deal_no,
            {_SLAB_DEPENDENT.format(deal_col='c.matched_deal_id')},
            {document_no}, {ticket_no},
            {ticket_key_sql(ticket_no)},
            {doc_code}, {doc_serial},
            {pnr}, {pax},
            c.run_id, :engine_version, :ver, now(), now()
        FROM {tbl} s
        -- LEFT, and scoped on all four key columns rather than on the row id alone:
        -- `commission_calculations.source_row_id` carries no foreign key and points at a
        -- different table per source, so `c.source` is what keeps a tp-lcc calculation
        -- off a tp-gds row that happens to share an id.
        LEFT JOIN commission_calculations c
               ON c.source_row_id = s.id
              AND c.source = :source
              AND c.tenant_id = s.tenant_id
              AND c.created_by_id = s.created_by_id
        LEFT JOIN airlines a
               ON a.id = {airline_id}
        LEFT JOIN deals d
               ON d.id = c.matched_deal_id
        -- LEFT, and the tenant predicate is ours to add: the unique constraint on
        -- statement_batch_suppliers is (slug, batch_id) only. A batch uploaded before
        -- that link existed has no row, and those must land in a visible
        -- "Unattributed consolidator" bucket rather than be dropped by an inner join.
        --
        -- Keyed off the STATEMENT row now, not the calculation: an unpriced batch has no
        -- calculation to read `c.source`/`c.batch_id` from, and without the consolidator
        -- its whole sale would land in the unattributed bucket.
        LEFT JOIN statement_batch_suppliers sbs
               ON sbs.slug = :source
              AND sbs.batch_id = s.batch_id
              AND sbs.tenant_id = s.tenant_id
        WHERE s.tenant_id = :tid AND s.created_by_id = :uid
          AND s.batch_id = :batch
    """


def _ndc_select() -> str:
    """NDC: the airline's own sales export. Sale only — nothing prices it.

    THE GROSS IS `Payment Amount`, NOT `Total Fare`, and getting that backwards inverts
    every refund. ndc_spec states it outright: "`Total Fare` on a REFUND line is the
    positive magnitude of the ORIGINAL SALE — the refund's own value is `Payment Amount`
    (-9200 against a 9480 fare and a 280 penalty)". `Payment Amount` is also the only
    signed column in the file, so a fallback to `Total Fare` has to take its sign from
    the transaction type; `-abs()` is idempotent, so a portal that already writes
    negatives needs no branch. This is `ndc_billing_projection.signed_total`, in SQL.

    PER ROW, NOT ANCHOR-ONLY. An NDC export writes ancillaries — a paid seat, a bag, a
    meal — as their own document-less lines that are latched under the ticket, and a
    latched line REPEATS the ticket's `Total Fare` while carrying its own `Payment
    Amount`. Summing `Total Fare` over the group therefore double-counts the ticket;
    summing the signed settled figure gives the group's real total, which is exactly the
    arithmetic report_download/mappers/ndc.py does with `net_payable`. The fare
    COMPONENTS are the other way round — they belong to the flight line — so they are
    taken only where the row is not an add-on.

    `is_total = false` in the WHERE: the file's own declared grand-total line is stored
    as a row (`_SplitMixin.is_total`, `registry.exclude_totals`), and counting it would
    add the statement's total to the statement's own rows.

    NDC carries no `resolve_airline`, so nothing is stamped at ingest and the carrier is
    looked up here the way ndc_billing_projection.airline_names does: the 3-digit
    accounting code first, the 2-letter designator second.
    """
    counts, counts_reason = counts_in_net_sql(SOURCE_NDC, "s")
    doc_code, doc_serial = doc_key_sql(
        _j("document_no"), _j("airline_iata_code"))
    # Everything the row needs parsed, computed once. Each date_sql is a nine-arm CASE
    # with two regexp_match runs; inlined three times it would be 15 KB per row.
    lateral = f"""
        CROSS JOIN LATERAL (
            SELECT ({date_sql(_j('date_of_issue'))})::date   AS issue_dt,
                   ({date_sql(_j('date_of_booking'))})::date AS book_dt,
                   ({date_sql(_j('departure_date'))})::date  AS travel_dt,
                   {jsonb_decimal_sql(_j('payment_amount'))} AS pay,
                   {jsonb_decimal_sql(_j('total_fare'))}     AS tot,
                   {ndc_is_refund_sql('s')}                  AS is_refund,
                   {ndc_is_ancillary_sql('s')}               AS is_ancillary
        ) n"""
    issue = "coalesce(n.issue_dt, n.book_dt)"
    gross = ("CASE WHEN n.is_refund THEN -abs(coalesce(n.pay, n.tot)) "
             "ELSE coalesce(n.pay, n.tot) END")
    # A component belongs to the flight line, so an add-on contributes none of its own —
    # and carries its whole value as ancillary instead.
    def _component(field: str) -> str:
        v = jsonb_decimal_sql(_j(field))
        return (f"CASE WHEN n.is_ancillary THEN NULL "
                f"WHEN n.is_refund THEN -abs({v}) ELSE ({v}) END")

    return f"""
        SELECT
            s.tenant_id, s.created_by_id, :source, s.batch_id, s.id,
            :direction, :kind,
            air.id, coalesce(air.name, {_j('airline')}), air.how,
            -- The airline IS the counterparty; an NDC statement has no consolidator.
            NULL, NULL, NULL, NULL, NULL, NULL,
            {issue}, to_char({issue}, 'YYYY-MM'),
            CASE WHEN n.issue_dt IS NOT NULL THEN 'date_of_issue'
                 WHEN n.book_dt IS NOT NULL THEN 'date_of_booking' ELSE NULL END,
            n.travel_dt, to_char(n.travel_dt, 'YYYY-MM'), NULL,
            -- The cell was there and no pattern read it. Distinct from an absent date,
            -- and carried for the same reason flat_statement carries it: a blank month
            -- bucket must not read as "no sales".
            ({issue} IS NULL AND nullif(btrim(coalesce({_j('date_of_issue')}, '')), '') IS NOT NULL),
            -- NDC prints no dom/intl of its own. NULL is "could not determine"; deriving
            -- it from `Sectors` would be a guess the deal engine then matches on.
            NULL, NULL, {_j('class_of_booking')},
            upper(btrim(coalesce({_j('txn_type')}, ''))),
            {txn_class_sql(SOURCE_NDC, _j('txn_type'))},
            '{CATEGORY_AIR}',
            {counts}, {counts_reason},
            coalesce(nullif(btrim({_j('currency')}), ''), 'INR'),
            {gross},
            CASE WHEN n.pay IS NOT NULL THEN 'printed' ELSE 'derived' END,
            {_component('basic_fare')}, {_component('yq_tax')}, {_component('yr_tax')},
            {_component('total_tax')},
            CASE WHEN n.is_ancillary THEN {gross} ELSE NULL END,
            -- Nothing prices NDC: it has no adapter in services/commission/__init__.py.
            NULL, NULL, NULL,
            NULL, NULL, NULL, NULL, NULL, NULL,
            false, 'unpriced', NULL, NULL,
            NULL, NULL, NULL, NULL, false,
            {_j('document_no')}, {_j('document_no')},
            {ticket_key_sql(_j('document_no'))},
            {doc_code}, {doc_serial},
            {_j('airline_pnr')}, 1,
            NULL, NULL, :ver, now(), now()
        FROM ndc s
        {lateral}
        -- LATERAL ... LIMIT 1, NOT a plain LEFT JOIN. `airlines.iata_code` is unique but
        -- `iata_numeric_code` is not constrained to be, and an OR-join matching two master
        -- rows would duplicate the statement row -- doubling its gross silently, since
        -- nothing about the total would look wrong. The ORDER BY puts the accounting code
        -- first, which is the resolution ndc_billing_projection.airline_names prefers.
        LEFT JOIN LATERAL (
            SELECT a.id, a.name,
                   CASE WHEN a.iata_numeric_code IS NOT NULL
                        THEN 'numeric_code' ELSE 'iata_code' END AS how
              FROM airlines a
             WHERE a.iata_numeric_code = lpad(nullif(regexp_replace(
                       coalesce({_j('airline_iata_code')}, ''), '[^0-9]', '', 'g'), ''), 3, '0')
                OR upper(a.iata_code) = upper(nullif(btrim({_j('airline')}), ''))
             ORDER BY (a.iata_numeric_code IS NULL)
             LIMIT 1
        ) air ON true
        WHERE s.tenant_id = :tid AND s.created_by_id = :uid
          AND s.batch_id = :batch
          AND s.is_total = false
    """


def _tp_api_select() -> str:
    """Third Party API: an aggregator's booking export. Sale only — nothing prices it.

    THE ONLY MULTI-PRODUCT ARM. One MakeMyTrip or TBO file carries hotel, flight, train,
    bus and car bookings side by side, so `product` is a real dimension here and not a
    constant, and `airline_id` is NULL on every row: the type declares no
    `resolve_airline`, its only carrier field is a free-text `airline_property_name` that
    holds a hotel's name on a hotel row, and tp_api_billing_projection says the same
    thing where it refuses to derive a code from it. The revenue tab surfaces this source
    BY PRODUCT and says on screen that it is not carrier-attributed — which is a
    different statement from "unattributed carrier", and must not share a bucket with it.

    The amount is `tpb.classify`'s, rendered in SQL by `tp_api_bill_lateral`. Not
    `bill_amount`: that column is written only when somebody resolves the batch in the
    billing worklist, so it is NULL on every unresolved upload.
    """
    counts, counts_reason = counts_in_net_sql(SOURCE_TP_API, "s")
    issue = (f"coalesce({iso_date_sql(_j('transaction_date'))}, "
             f"{iso_date_sql(_j('booking_date'))})")
    travel = (f"coalesce({iso_date_sql(_j('travel_date'))}, "
              f"{iso_date_sql(_j('start_date'))})")
    return f"""
        SELECT
            s.tenant_id, s.created_by_id, :source, s.batch_id, s.id,
            :direction, :kind,
            NULL, NULL, NULL,
            sbs.supplier_id, sbs.supplier_name, sbs.supplier_code, sbs.supplier_branch,
            NULL, NULL,
            {issue}, to_char({issue}, 'YYYY-MM'),
            CASE WHEN {iso_date_sql(_j('transaction_date'))} IS NOT NULL
                 THEN 'transaction_date' ELSE 'booking_date' END,
            {travel}, to_char({travel}, 'YYYY-MM'), NULL,
            (s.data ? 'date_parse_failed'),
            {segment_sql(_j('intl_dom'))}, {_j('intl_dom')}, {_j('booking_class')},
            upper(btrim(coalesce({_j('booking_status')}, ''))),
            {txn_class_sql(SOURCE_TP_API, _j('booking_status'))},
            -- markup_categories' slug, which is what billing and the report both group on.
            {tp_api_product_sql('s')},
            {counts}, {counts_reason},
            'INR',
            {TP_API_ALIAS}.amount,
            CASE WHEN tpm.net IS NOT NULL OR tpm.paid IS NOT NULL
                 THEN 'printed' ELSE 'derived' END,
            {jsonb_decimal_sql(_j('base_fare'))}, NULL, NULL,
            {jsonb_decimal_sql(_j('taxes'))}, NULL,
            -- No commission adapter: an aggregator's hotel and train lines have no
            -- airline deal to price against.
            NULL, NULL, NULL,
            NULL, NULL, NULL, NULL, NULL, NULL,
            false, 'unpriced', NULL, NULL,
            NULL, NULL, NULL, NULL, false,
            {_j('invoice_number')}, {_j('booking_id')},
            {ticket_key_sql(_j('booking_id'))},
            NULL, NULL,
            {_j('pnr')}, coalesce(s.bill_pax_count, 1),
            NULL, NULL, :ver, now(), now()
        FROM third_party_api s
        {tp_api_bill_lateral('s')}
        LEFT JOIN statement_batch_suppliers sbs
               ON sbs.slug = :source
              AND sbs.batch_id = s.batch_id
              AND sbs.tenant_id = s.tenant_id
        WHERE s.tenant_id = :tid AND s.created_by_id = :uid
          AND s.batch_id = :batch
    """


# Per source: the batches it holds and when each last CHANGED, which is what a freshness
# check compares against `max(projected_at)`. "Changed" is the later of two things — when
# the statement itself last landed, and when it was last priced — because either one
# restates the projection and only one of them used to be watched.
#
# The statement side is the half that is new. Before unpriced rows were projected,
# freshness could ask commission_runs alone; now an upload with no run behind it is real
# sale, and a board that has not seen it is behind even though nothing has ever been
# priced.
_BATCH_SQL = {
    SOURCE_BSP: """
        SELECT s.batch_id, s.created_by_id,
               greatest(s.created_at, coalesce(s.commission_calculated_at, s.created_at))
          FROM bsp_statements s
         WHERE s.tenant_id = :tid {user}
    """,
    SOURCE_LCC_DETAILED: """
        SELECT b.batch_id, b.created_by_id,
               greatest(coalesce(b.completed_at, b.uploaded_at),
                        coalesce(r.done, coalesce(b.completed_at, b.uploaded_at)))
          FROM lcc_detailed_batch b
          LEFT JOIN (
                SELECT batch_id, max(completed_at) AS done FROM commission_runs
                 WHERE source = :source AND status = 'completed' GROUP BY batch_id
          ) r ON r.batch_id = b.batch_id
         WHERE b.tenant_id = :tid {user_b}
    """,
}

# GROUP BY the owner as well as the batch: a batch belongs to exactly one uploader, so
# this adds no rows, and it means a tenant-wide rebuild can re-project a colleague's
# upload under THEIR id rather than the admin's.
_SPEC_BATCH_SQL = """
    SELECT s.batch_id, s.created_by_id,
           greatest(max(s.uploaded_at), coalesce(max(r.done), max(s.uploaded_at)))
      FROM {tbl} s
      LEFT JOIN (
            SELECT batch_id, max(completed_at) AS done FROM commission_runs
             WHERE source = :source AND status = 'completed' GROUP BY batch_id
      ) r ON r.batch_id = s.batch_id
     WHERE s.tenant_id = :tid {user}
     GROUP BY s.batch_id, s.created_by_id
"""


async def batch_changes(
    db: AsyncSession, *, tenant_id: int, user_id: int | None, source: str,
) -> list[tuple[str, int, object]]:
    """(batch_id, owner_id, last_changed) for one source. `user_id=None` = tenant-wide.

    The tenant-wide mode exists because the revenue board defaults to agency scope: a
    Company Admin looking at a board that sums everyone's uploads, fed by a rebuild that
    only re-projected their own, would be told the figures were current when half of
    them had never been projected at all.

    THE OWNER IS RETURNED, NOT ASSUMED. `created_by_id` is half the projection's unique
    key, so re-projecting a colleague's batch under the caller's id would insert a second
    copy of every row rather than restate the first.
    """
    if source not in PROJECTED_SOURCES:
        return []
    params: dict = {"tid": tenant_id, "source": source}
    if user_id is not None:
        params["uid"] = user_id
    scoped = " AND s.created_by_id = :uid" if user_id is not None else ""
    scoped_b = " AND b.created_by_id = :uid" if user_id is not None else ""

    if source in _BATCH_SQL:
        sql = _BATCH_SQL[source].format(user=scoped, user_b=scoped_b)
    else:
        tbl = {**_SOURCE_TABLES, **_SALE_ONLY_TABLES}[source]
        sql = _SPEC_BATCH_SQL.format(tbl=tbl, user=scoped)
    return [(r[0], r[1], r[2]) for r in (await db.execute(text(sql), params)).all()]


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
    elif source in _SALE_ONLY_TABLES:
        # ndc and tp-api: statement rows with no commission adapter behind them. Sale
        # only, `priced = false`, incentive NULL — and NULL is the whole point, because a
        # zero would say a deal applied and earned nothing.
        select_sql = _ndc_select() if source == SOURCE_NDC else _tp_api_select()
        params = {
            "tid": tenant_id, "uid": user_id, "batch": batch_id, "source": source,
            "direction": DIRECTION_INBOUND,
            # NDC comes straight from the carrier; an aggregator statement is issued by a
            # consolidator we bought through.
            "kind": KIND_AIRLINE if source == SOURCE_NDC else KIND_SUPPLIER,
            "ver": PROJECTION_VERSION,
        }
        tbl = _SALE_ONLY_TABLES[source]
        # The same predicate the arm carries, so the sweep's live-id set is exactly the
        # set the INSERT wrote. NDC's declared grand-total line is stored as a row and
        # never projected; leaving it out of both is what keeps them in step.
        extra = " AND s.is_total = false" if source == SOURCE_NDC else ""
        id_sql = (f"SELECT s.id FROM {tbl} s "
                  "WHERE s.tenant_id = :tid AND s.created_by_id = :uid "
                  f"AND s.batch_id = :batch{extra}")
        id_params = {"tid": tenant_id, "uid": user_id, "batch": batch_id}
    elif source in _SOURCE_TABLES:
        select_sql = _statement_select(source)
        params = {
            "tid": tenant_id, "uid": user_id, "batch": batch_id, "source": source,
            "direction": DIRECTION_INBOUND,
            # lcc-detailed is an airline deal; the two third-party sources are B2B.
            "kind": KIND_AIRLINE if source == SOURCE_LCC_DETAILED else KIND_SUPPLIER,
            "engine_version": engine_version, "ver": PROJECTION_VERSION,
        }
        # Moved with `source_row_id` — the live ids are the statement rows', not the
        # calculations'. Reading the calc ledger here would now sweep away every unpriced
        # row the INSERT had just written.
        tbl = _SOURCE_TABLES[source]
        id_sql = (f"SELECT s.id FROM {tbl} s "
                  "WHERE s.tenant_id = :tid AND s.created_by_id = :uid "
                  "AND s.batch_id = :batch")
        id_params = {"tid": tenant_id, "uid": user_id, "batch": batch_id}
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
