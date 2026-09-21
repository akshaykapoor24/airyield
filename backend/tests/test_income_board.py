"""What the income board must never get wrong.

These are the regression guards for the five invariants models/income_board.py exists
to enforce. Each one protects a mistake that would look like a reasonable change in
review and would be invisible on screen: a NULL coalesced to zero, a memo counted as
revenue, an exchange counted as a sale, a segment silently unreadable, a supplier join
narrowed from LEFT to INNER.

Pure-unit, as everything in this directory is: the SQL is asserted by compiling it,
not by running it. The projection is exercised end to end against a real database
separately.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.income_board import (  # noqa: E402
    DIRECTION_INBOUND, DIRECTION_OUTBOUND, MATCHED_STATUSES, REVENUE_TXN_CLASSES,
    TXN_ADJUSTMENT, TXN_CREDIT_MEMO, TXN_DEBIT_MEMO, TXN_OTHER, TXN_REFUND, TXN_SALE,
)
from app.services.bsp_commission import (  # noqa: E402
    _ISSUE_TXN, _REFUND_TXN, _SKIP_TXN,
)
from app.services.deal_matching import segment_letter  # noqa: E402
from app.services.income_board import measures  # noqa: E402
from app.services.income_board.dimensions import (  # noqa: E402
    classify_txn, normalise_bsp_segment, normalise_segment,
)
from app.services.income_board.project import (  # noqa: E402
    _COLUMNS, _SOURCE_TABLES, _UPDATE_COLUMNS, _bsp_select, _commission_select,
)


def _sql(expr) -> str:
    """An expression as the Postgres text it will actually run as."""
    return str(
        select(expr).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestTransactionClass(unittest.TestCase):
    """Memos are not sales, and an exchange is not a second sale."""

    def test_every_issue_type_is_a_sale(self):
        for t in _ISSUE_TXN:
            self.assertEqual(classify_txn(t), TXN_SALE, t)

    def test_every_refund_type_is_a_refund(self):
        for t in _REFUND_TXN:
            self.assertEqual(classify_txn(t), TXN_REFUND, t)

    def test_no_skip_type_is_ever_revenue(self):
        # The whole point of txn_class: nothing bsp_commission refuses to price may
        # land in a bucket the board counts as revenue.
        for t in _SKIP_TXN:
            self.assertNotIn(classify_txn(t), REVENUE_TXN_CLASSES, t)

    def test_exchange_is_not_a_sale(self):
        # bsp_commission settles an exchange under the reissued document. Counting it
        # here would book the same journey twice.
        self.assertEqual(classify_txn("EXCH"), TXN_ADJUSTMENT)

    def test_memos_are_distinguishable_from_each_other(self):
        # ADM exposure is money going out and ACM is money coming back; a board that
        # merged them would net a liability against a credit.
        self.assertEqual(classify_txn("ADM"), TXN_DEBIT_MEMO)
        self.assertEqual(classify_txn("ACM"), TXN_CREDIT_MEMO)

    def test_unknown_and_missing_fall_to_other(self):
        for t in (None, "", "   ", "WHAT"):
            self.assertEqual(classify_txn(t), TXN_OTHER, repr(t))

    def test_classification_is_case_and_space_insensitive(self):
        self.assertEqual(classify_txn("  tktt "), TXN_SALE)


class TestSegment(unittest.TestCase):
    """The board must speak the money engine's vocabulary, not a looser one."""

    def test_agrees_with_the_engine(self):
        for spelling in ("INTERNATIONAL", "INTL", "INTER", "INT", "DOMESTIC", "DOM",
                         "international", "", None, "WHAT"):
            self.assertEqual(normalise_segment(spelling), segment_letter(spelling),
                             repr(spelling))

    def test_bare_letters_are_not_accepted_from_a_word_source(self):
        # Deliberate: segment_letter rejects them, and the board agreeing with the
        # engine matters more than the board being lenient. dashboard.py's
        # _DOM_VARIANTS/_INT_VARIANTS DO accept them, which is the disagreement this
        # module exists to avoid inheriting.
        self.assertIsNone(normalise_segment("I"))
        self.assertIsNone(normalise_segment("D"))

    def test_bsp_stat_round_trips_through_the_word_form(self):
        # THE REGRESSION THIS FILE MOST EXISTS FOR. Feeding STAT straight into
        # segment_letter yields None for every BSP row -- silently, because None is a
        # legitimate "could not determine".
        self.assertEqual(normalise_bsp_segment("I"), "I")
        self.assertEqual(normalise_bsp_segment("D"), "D")

    def test_bsp_stat_tolerates_the_amended_row_suffix(self):
        # Real statements print I71 / D41 on amended rows.
        self.assertEqual(normalise_bsp_segment("I71"), "I")
        self.assertEqual(normalise_bsp_segment("D41"), "D")

    def test_bsp_unreadable_stat_is_none_not_a_guess(self):
        for s in (None, "", "X", "71"):
            self.assertIsNone(normalise_bsp_segment(s), repr(s))


class TestMeasures(unittest.TestCase):
    """Every money sum carries its guard."""

    def test_incentive_sum_is_status_filtered(self):
        sql = _sql(measures.incentive_sum())
        self.assertIn("FILTER", sql)
        for status in MATCHED_STATUSES:
            self.assertIn(status, sql)

    def test_incentive_sum_never_coalesces_the_null_away(self):
        # NULL means "we could not confirm what you are owed". A coalesce here would
        # turn it into "you are owed nothing" -- a number someone would act on.
        self.assertNotIn("coalesce(income_board_rows.incentive",
                         _sql(measures.incentive_sum()).lower())

    def test_iata_commission_is_never_part_of_an_incentive_total(self):
        self.assertNotIn("iata_commission", _sql(measures.incentive_sum()))
        self.assertNotIn("sum(income_board_rows.incentive)",
                         _sql(measures.iata_sum()).lower())

    def test_gross_revenue_excludes_every_memo_class(self):
        sql = _sql(measures.gross_revenue())
        for cls in REVENUE_TXN_CLASSES:
            self.assertIn(cls, sql)
        for cls in (TXN_DEBIT_MEMO, TXN_CREDIT_MEMO, TXN_ADJUSTMENT):
            self.assertNotIn(cls, sql)

    def test_spread_has_all_three_terms_with_the_right_signs(self):
        # "Vendor income minus customer income" is a three-term expression: the
        # outbound commission is a COST and the markup is INCOME.
        sql = _sql(measures.spread_expr())
        self.assertIn(DIRECTION_INBOUND, sql)
        self.assertIn(DIRECTION_OUTBOUND, sql)
        self.assertIn("markup_amount", sql)
        self.assertIn(" - ", sql)
        self.assertIn(" + ", sql)

    def test_spread_applies_the_sign_once(self):
        # There is no stored direction_sign and no stored net_income precisely so that
        # the sign cannot be applied twice. If either ever appears on the model, this
        # fails and the reviewer has to justify it.
        from app.models.income_board import IncomeBoardRow as R
        cols = {c.name for c in R.__table__.columns}
        self.assertNotIn("direction_sign", cols)
        self.assertNotIn("net_income", cols)


class TestProjectionShape(unittest.TestCase):
    """Every arm agrees in shape, and none of them loses a guard."""

    ARMS = None

    @classmethod
    def setUpClass(cls):
        cls.ARMS = {"bsp": _bsp_select()}
        for s in _SOURCE_TABLES:
            cls.ARMS[s] = _commission_select(s)

    def test_column_list_has_no_duplicates(self):
        self.assertEqual(len(_COLUMNS), len(set(_COLUMNS)))

    def test_first_seen_at_is_never_restated(self):
        # It records when a line was first priced. Re-running commission on a
        # six-month-old statement must not make its income look new.
        self.assertIn("first_seen_at", _COLUMNS)
        self.assertNotIn("first_seen_at", _UPDATE_COLUMNS)

    def test_the_conflict_key_is_never_in_the_update_set(self):
        for c in ("tenant_id", "created_by_id", "source", "source_row_id"):
            self.assertNotIn(c, _UPDATE_COLUMNS, c)

    def test_every_arm_carries_both_scope_predicates(self):
        # There is no shared scoping dependency in this repo; each query filters by
        # hand, so each one is checked by hand.
        for name, sql in self.ARMS.items():
            self.assertIn("tenant_id = :tid", sql, name)
            self.assertIn("created_by_id = :uid", sql, name)

    def test_the_supplier_join_is_left_and_tenant_scoped(self):
        # INNER would drop every row of a batch uploaded before the supplier link
        # existed -- income vanishing rather than showing as Unattributed. The tenant
        # predicate is ours to add: the unique constraint is (slug, batch_id) only.
        for s in ("tp-gds", "tp-lcc"):
            sql = self.ARMS[s]
            self.assertIn("LEFT JOIN statement_batch_suppliers", sql, s)
            self.assertIn("sbs.tenant_id = c.tenant_id", sql, s)

    def test_third_party_gross_is_regex_guarded_before_casting(self):
        # flat_statement keeps the ORIGINAL TEXT when a number fails to parse, so an
        # unguarded ::numeric raises and takes the whole projection down.
        for s in ("tp-gds", "tp-lcc"):
            sql = self.ARMS[s]
            self.assertIn("~ '^-?[0-9]+(\\.[0-9]+)?$'", sql, s)
            self.assertIn("::numeric", sql, s)

    def test_bsp_resolves_the_carrier_by_code_never_by_name(self):
        # Grouping BSP on its free-text carrier name splits one airline across several
        # dashboard rows.
        sql = self.ARMS["bsp"]
        self.assertIn("a.iata_numeric_code", sql)
        self.assertNotIn("a.name = ", sql)
        self.assertIn("lpad(", sql)   # statements are inconsistent about leading zeros

    def test_no_arm_coalesces_the_incentive(self):
        for name, sql in self.ARMS.items():
            low = sql.lower().replace(" ", "")
            self.assertNotIn("coalesce(c.incentive", low, name)
            self.assertNotIn("coalesce(r.calculated_incentive", low, name)


if __name__ == "__main__":
    unittest.main()
