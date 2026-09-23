"""What the Total Revenue board must never get wrong.

Two families of mistake, both of which produce a number that looks entirely reasonable:

  * ADDING A LINE THAT RESTATES ANOTHER LINE. Twelve statement types cover six
    businesses. A TGQ HMPR row is the same ticket as its BSP row, a memo counts through
    the BSP row it was raised against, a Flown Report line is the same booking as its
    LCC Detailed row. Summed naively, the BSP and LCC families roughly double.
  * LOSING A LINE THAT IS REAL. `counts_in_net` on a gross is one predicate away from
    `counts_in_net` on a count, and `priced` belongs on neither.

Pure-unit, as everything in this directory is: the SQL is asserted by compiling it, not
by running it.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api.v1 import revenue_board as rb  # noqa: E402
from app.models.income_board import (  # noqa: E402
    SALE_SOURCES, SOURCE_TP_API, IncomeBoardRow as R,
)
from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download.registry import SOURCE_BY_KEY  # noqa: E402
from app.services.revenue_linked import LINKED_SOURCES  # noqa: E402


def _sql(*exprs) -> str:
    return str(
        select(*exprs).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _where_sql(conds) -> str:
    """A predicate list as the Postgres text it will actually run as."""
    return str(
        select(R.id).where(*conds).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


class TestSaleScope(unittest.TestCase):
    """Only the six types that ARE the sale may reach a sale total."""

    def _filters(self, **kw):
        base = dict(basis="issue", date_from=None, date_to=None, airline=None,
                    supplier=None, source=None, category=None, currency=None)
        return rb._filters(**{**base, **kw})

    def test_the_source_list_is_pinned_even_with_no_filter(self):
        # Not a narrowing and not optional. The table also holds the linked statements
        # and the selling side; letting either in would not look wrong, just larger.
        rendered = _where_sql(self._filters())
        for src in SALE_SOURCES:
            self.assertIn(f"'{src}'", rendered, src)

    def test_a_linked_statement_can_never_be_asked_for(self):
        # Even when the caller names one explicitly: `source` intersects SALE_SOURCES,
        # it does not replace it.
        rendered = _where_sql(self._filters(source=["tgq-hmpr", "adm", "bsp"]))
        self.assertIn("'bsp'", rendered)
        self.assertNotIn("'tgq-hmpr'", rendered)
        self.assertNotIn("'adm'", rendered)

    def test_asking_only_for_linked_statements_returns_nothing_not_everything(self):
        # The empty intersection must not fall back to "no filter" -- that is the
        # classic version of this bug, and it shows the whole board.
        rendered = _where_sql(self._filters(source=["tgq-hmpr"]))
        self.assertIn("'__none__'", rendered)
        for src in SALE_SOURCES:
            self.assertNotIn(f"'{src}'", rendered, src)

    def test_a_category_narrows_to_that_family_only(self):
        rendered = _where_sql(self._filters(category=["LCC"]))
        self.assertIn("'lcc-detailed'", rendered)
        self.assertNotIn("'bsp'", rendered)
        self.assertNotIn("'tp-gds'", rendered)

    def test_the_six_sale_sources_and_the_linked_ones_do_not_overlap(self):
        linked = {s.key for s in LINKED_SOURCES}
        self.assertEqual(linked & set(SALE_SOURCES), set())

    def test_every_source_on_the_board_is_a_real_registry_key(self):
        # The category and the label both read off the report registry, so a source
        # spelled differently here would KeyError at import rather than mislabel a card.
        for src in SALE_SOURCES:
            self.assertIn(src, SOURCE_BY_KEY, src)
        for s in LINKED_SOURCES:
            self.assertIn(s.key, SOURCE_BY_KEY, s.key)

    def test_ndc_is_filed_under_bsp_the_way_the_statements_hub_files_it(self):
        # A reader chasing a number goes looking where they uploaded it.
        self.assertEqual(rb.SOURCE_CATEGORY["ndc"], "BSP")
        self.assertEqual(rb.SOURCE_CATEGORY["lcc-detailed"], "LCC")
        for s in ("tp-gds", "tp-lcc", "tp-api"):
            self.assertEqual(rb.SOURCE_CATEGORY[s], "Third Party", s)


class TestSaleMeasures(unittest.TestCase):
    """The two predicates that make a sale total honest."""

    def test_sale_gross_excludes_memos_and_restating_lines(self):
        from app.services.income_board import measures
        rendered = _sql(measures.sale_gross())
        self.assertIn("counts_in_net", rendered)
        self.assertIn("'sale'", rendered)
        self.assertIn("'refund'", rendered)
        # A memo has no fare. Its value in a gross denominator corrupts every ratio.
        self.assertNotIn("'debit_memo'", rendered)
        self.assertNotIn("'credit_memo'", rendered)

    def test_sale_counts_the_unpriced(self):
        # "We sold this and have not costed it yet" is still a sale. Pinning `priced`
        # here would understate every workspace that is behind on pricing.
        from app.services.income_board import measures
        self.assertNotIn("priced", _sql(measures.sale_gross()))
        self.assertNotIn("priced", _sql(measures.sale_rows()))

    def test_the_incentive_carries_the_same_counts_in_net(self):
        # So that income-over-sale is a ratio the board's own two figures support.
        from app.services.income_board import measures
        rendered = _sql(measures.counted_incentive())
        self.assertIn("counts_in_net", rendered)
        self.assertIn("'calculated'", rendered)
        self.assertNotIn("coalesce", rendered.lower())

    def test_what_was_held_out_is_measured_rather_than_dropped(self):
        from app.services.income_board import measures
        rendered = _sql(measures.not_counted_gross())
        self.assertIn("counts_in_net IS false", rendered)


class TestIncentiveBreakdown(unittest.TestCase):
    """PLB per airline is the question this board is asked most."""

    def test_the_breakdown_is_read_by_key_not_by_a_fixed_column_list(self):
        # `deal_incentives.incentive_type` is a String; the canonical eleven are a
        # convention. A twelfth type must appear without a migration -- a fixed list
        # drops it silently, which on an incentive means money earned and nowhere shown.
        sql = str(rb._incentive_type_select([R.tenant_id == 1]).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("jsonb_each_text", sql)
        self.assertNotIn("'PLB'", sql)

    def test_the_value_is_regex_guarded_before_casting(self):
        sql = str(rb._incentive_type_select([R.tenant_id == 1]).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("^-?[0-9]+", sql)
        self.assertIn("CAST", sql)

    def test_the_lateral_declares_no_column_definition_list(self):
        """`AS inc(key text, value text)` is rejected by Postgres for this function.

        `jsonb_each_text` declares its own OUT parameters, so a column definition list
        is redundant and the server answers "a column definition list is redundant for a
        function with OUT parameters" and refuses the statement. SQLAlchemy compiles it
        either way, which is exactly why a compile-only assertion is the wrong guard and
        this one looks at the rendered text instead. Caught by running it, not by
        reading it.
        """
        sql = str(rb._incentive_type_select([R.tenant_id == 1]).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("jsonb_each_text", sql)
        self.assertNotIn("(key ", sql)
        self.assertNotIn("TEXT,", sql.upper().replace("CAST(INC.VALUE AS ", ""))

    def test_only_claimable_counted_rows_contribute(self):
        sql = str(rb._incentive_type_select([R.tenant_id == 1]).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("counts_in_net", sql)
        self.assertIn("'calculated'", sql)
        self.assertIn("'reversed'", sql)


class TestNotCountedVocabulary(unittest.TestCase):
    """One wording, two screens."""

    def test_the_linked_types_name_their_own_measure_never_sale(self):
        for s in LINKED_SOURCES:
            self.assertNotIn("sale", s.measure_label.lower(), s.key)
            self.assertTrue(s.measure_label, s.key)

    def test_every_linked_amount_is_regex_guarded(self):
        # These tables hold the vendor's own text -- the memo tables are Text in every
        # column -- so an unguarded ::numeric raises on one bad cell and takes the
        # whole panel down.
        for s in LINKED_SOURCES:
            self.assertIn("~ '^-?[0-9]+", s.amount_sql, s.key)

    def test_the_reasons_the_board_can_store_are_the_reports_own(self):
        known = {v for k, v in vars(C).items()
                 if k.startswith("NET_") and isinstance(v, str)}
        self.assertIn(C.NET_NDC_IN_BSP, known)
        self.assertIn(C.NET_LCC_PAYMENT, known)
        self.assertIn(C.NET_SUMMARY_ONLY, known)


class TestCarrierAttribution(unittest.TestCase):
    """"No carrier" and "carrier we could not resolve" are different sentences."""

    def test_the_aggregator_source_is_counted_apart(self):
        # tp-api declares no resolve_airline: an aggregator's hotel row has no carrier
        # BY NATURE. Folding it into the unattributed bucket would report a data-quality
        # problem that does not exist, on every file, forever.
        self.assertEqual(SOURCE_TP_API, "tp-api")
        fields = rb.RevenueTotals.model_fields
        self.assertIn("unattributed_airline_rows", fields)
        self.assertIn("not_carrier_attributed_rows", fields)


if __name__ == "__main__":
    unittest.main()
