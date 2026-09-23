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

import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.income_board import (  # noqa: E402
    DIRECTION_INBOUND, DIRECTION_OUTBOUND, MATCHED_STATUSES, REVENUE_TXN_CLASSES,
    SALE_SOURCES, SOURCE_BSP, SOURCE_LCC_DETAILED, SOURCE_TP_GDS, SOURCE_TP_LCC,
    TXN_ADJUSTMENT, TXN_CREDIT_MEMO, TXN_DEBIT_MEMO, TXN_OTHER, TXN_REFUND, TXN_SALE,
)
from app.services.bsp_commission import (  # noqa: E402
    _ISSUE_TXN, _REFUND_TXN, _SKIP_TXN,
)
from app.services.deal_matching import segment_letter  # noqa: E402
from app.services.income_board import measures  # noqa: E402
from app.services.income_board.dimensions import (  # noqa: E402
    classify_txn, counts_in_net_sql, normalise_bsp_segment, normalise_segment,
    txn_class_sql,
)
from app.services.income_board.project import (  # noqa: E402
    _COLUMNS, _SOURCE_TABLES, _UPDATE_COLUMNS, COMMISSION_SOURCES, PROJECTED_SOURCES,
    _bsp_select, _ndc_select, _statement_select, _tp_api_select,
)
from app.services.report_download import columns as C  # noqa: E402
from app.api.v1 import income_board as income_board_api  # noqa: E402


def _select_exprs(sql: str) -> list[str]:
    """The top-level expressions of an arm's SELECT list.

    Hand-written rather than pulled from a SQL parser because the arms are f-string
    text, not SQLAlchemy objects, and the repo has no parser dependency. It tracks the
    three things that actually matter: string literals (with '' escapes), nesting, and
    `--` comments, which run to end of line even when they contain an apostrophe.
    """
    i = sql.index("SELECT") + len("SELECT")
    out: list[str] = []
    cur: list[str] = []
    depth, in_string = 0, False
    while i < len(sql):
        ch = sql[i]
        if in_string:
            cur.append(ch)
            if ch == "'":
                if sql[i + 1:i + 2] == "'":
                    cur.append("'")
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            cur.append(ch)
            i += 1
            continue
        if sql.startswith("--", i):
            nl = sql.find("\n", i)
            i = len(sql) if nl < 0 else nl + 1
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and sql.startswith("FROM", i) and not sql[i - 1:i].isalnum():
            break
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        out.append(tail)
    return out


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
            self.assertEqual(classify_txn(SOURCE_BSP, t), TXN_SALE, t)

    def test_every_refund_type_is_a_refund(self):
        for t in _REFUND_TXN:
            self.assertEqual(classify_txn(SOURCE_BSP, t), TXN_REFUND, t)

    def test_no_skip_type_is_ever_revenue(self):
        # The whole point of txn_class: nothing bsp_commission refuses to price may
        # land in a bucket the board counts as revenue.
        for t in _SKIP_TXN:
            self.assertNotIn(classify_txn(SOURCE_BSP, t), REVENUE_TXN_CLASSES, t)

    def test_exchange_is_not_a_sale(self):
        # bsp_commission settles an exchange under the reissued document. Counting it
        # here would book the same journey twice.
        self.assertEqual(classify_txn(SOURCE_BSP, "EXCH"), TXN_ADJUSTMENT)

    def test_memos_are_distinguishable_from_each_other(self):
        # ADM exposure is money going out and ACM is money coming back; a board that
        # merged them would net a liability against a credit.
        self.assertEqual(classify_txn(SOURCE_BSP, "ADM"), TXN_DEBIT_MEMO)
        self.assertEqual(classify_txn(SOURCE_BSP, "ACM"), TXN_CREDIT_MEMO)

    def test_unknown_and_missing_fall_to_other(self):
        for t in (None, "", "   ", "WHAT"):
            self.assertEqual(classify_txn(SOURCE_BSP, t), TXN_OTHER, repr(t))

    def test_classification_is_case_and_space_insensitive(self):
        self.assertEqual(classify_txn(SOURCE_BSP, "  tktt "), TXN_SALE)


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
        cls.ARMS = {"bsp": _bsp_select(), "ndc": _ndc_select(),
                    "tp-api": _tp_api_select()}
        for s in _SOURCE_TABLES:
            cls.ARMS[s] = _statement_select(s)

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
        #
        # Keyed off the STATEMENT row, never the calculation: an unpriced batch has no
        # calculation to read a batch_id from, so `sbs.batch_id = c.batch_id` would put
        # every unpriced consolidator line in the Unattributed bucket.
        for s in ("tp-gds", "tp-lcc"):
            sql = self.ARMS[s]
            self.assertIn("LEFT JOIN statement_batch_suppliers", sql, s)
            self.assertIn("sbs.tenant_id = s.tenant_id", sql, s)
            self.assertIn("sbs.batch_id = s.batch_id", sql, s)
            self.assertNotIn("sbs.batch_id = c.batch_id", sql, s)

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

    def test_every_arm_emits_exactly_the_projected_columns(self):
        """A swapped pair of same-typed columns is invisible to Postgres.

        The INSERT names `_COLUMNS` and each arm must answer it position for position.
        A count mismatch fails loudly at runtime; a same-typed pair in the wrong ORDER
        does not fail at all, it just files one row's ticket number under its PNR
        forever. Counting is what this can check cheaply, and it catches the mistake
        that actually happens: adding a column to the tuple and to three arms.
        """
        for name, sql in self.ARMS.items():
            self.assertEqual(len(_select_exprs(sql)), len(_COLUMNS), name)

    def test_every_arm_says_whether_the_row_was_priced(self):
        # Without it, "nobody has costed this statement" and "commission ran and matched
        # nothing" are the same row on screen: both have a NULL incentive.
        for name, sql in self.ARMS.items():
            self.assertTrue(
                "priced" in sql or "commission_calculated_at IS NOT NULL" in sql
                or "c.id IS NOT NULL" in sql, name)

    def test_the_statement_arms_key_on_the_statement_row(self):
        """`source_row_id` must be the statement row's id, not the calculation's.

        runner._upsert deletes and re-inserts the calculations on every run, so their
        ids change every time. Keyed on those, the upsert misses, the INSERT writes new
        rows and the orphan sweep removes the old ones -- which silently resets
        `first_seen_at`, the one thing project.py's header insists must survive a re-run.
        """
        for s in _SOURCE_TABLES:
            sql = self.ARMS[s]
            self.assertIn("FROM " + _SOURCE_TABLES[s] + " s", sql, s)
            self.assertIn("LEFT JOIN commission_calculations c", sql, s)
            # The projected id, fifth in _COLUMNS.
            self.assertEqual(_select_exprs(sql)[_COLUMNS.index("source_row_id")], "s.id", s)


class TestSourceVocabularies(unittest.TestCase):
    """The test that would have caught it.

    `txn_class_sql` was generated from BSP's transaction types alone, while
    commission_calculations.transaction_type holds a ticket STATUS for the consolidator
    sources and a bill_kind for lcc-detailed. Every non-BSP row therefore classified as
    'other', and gross_revenue() -- which filters on sale|refund -- returned BSP-only
    figures from the day the table shipped. Nothing errored.
    """

    #: (source, value, expected class). Real strings each engine actually writes.
    CASES = (
        (SOURCE_BSP, "TKTT", TXN_SALE),
        (SOURCE_BSP, "RFND", TXN_REFUND),
        (SOURCE_BSP, "ADM", TXN_DEBIT_MEMO),
        (SOURCE_BSP, "ACM", TXN_CREDIT_MEMO),
        (SOURCE_BSP, "EXCH", TXN_ADJUSTMENT),
        (SOURCE_BSP, "CONFIRMED", TXN_OTHER),      # another source's word, not BSP's
        (SOURCE_TP_GDS, "CONFIRMED", TXN_SALE),
        (SOURCE_TP_GDS, "REFUNDED", TXN_REFUND),
        (SOURCE_TP_GDS, "CANCELLED", TXN_ADJUSTMENT),
        (SOURCE_TP_GDS, "PENDING", TXN_ADJUSTMENT),
        (SOURCE_TP_GDS, "TICKETED", TXN_SALE),     # unrecognised falls through to a sale
        (SOURCE_TP_GDS, "", TXN_SALE),             # ...and so does a blank status
        (SOURCE_TP_LCC, "REFUNDED", TXN_REFUND),
        (SOURCE_LCC_DETAILED, "sale", TXN_SALE),
        (SOURCE_LCC_DETAILED, "refund", TXN_REFUND),
        (SOURCE_LCC_DETAILED, "payment", TXN_ADJUSTMENT),
    )

    def test_each_source_reads_its_own_vocabulary(self):
        for source, value, expected in self.CASES:
            self.assertEqual(classify_txn(source, value), expected,
                             f"{source} / {value!r}")

    def test_the_consolidator_sources_see_real_sales(self):
        # The regression itself, stated as the thing a reader cares about: a confirmed
        # consolidator ticket is revenue, and before the fix it was 'other'.
        for source in (SOURCE_TP_GDS, SOURCE_TP_LCC):
            self.assertIn(classify_txn(source, "CONFIRMED"), REVENUE_TXN_CLASSES, source)
        self.assertIn(classify_txn(SOURCE_LCC_DETAILED, "sale"), REVENUE_TXN_CLASSES)

    def test_the_sql_agrees_with_the_python_for_every_source(self):
        """One vocabulary, two renderings. They are generated from one set, so the only
        way they can disagree is if somebody edits one of them by hand.

        A value the classifier reaches by FALL-THROUGH is deliberately absent from the
        SQL -- that is what a fallback is -- so only the listed ones are looked for.
        """
        unlisted = "ZZ_NOT_A_REAL_TRANSACTION_TYPE"
        for source, value, expected in self.CASES:
            sql = txn_class_sql(source, "col")
            fallback = classify_txn(source, unlisted)
            self.assertIn(f"THEN '{expected}'", sql, f"{source} / {value!r}")
            if value and expected != fallback:
                self.assertIn(f"'{value.upper()}'", sql.upper(), f"{source} / {value!r}")

    def test_an_unknown_source_raises_rather_than_inheriting_bsp(self):
        # The signature exists to make the original bug impossible. A new arm that
        # forgets its vocabulary must fail here, not classify everything as 'other'.
        with self.assertRaises(ValueError):
            classify_txn("some-new-source", "TKTT")
        with self.assertRaises(ValueError):
            txn_class_sql("some-new-source", "col")

    def test_every_sale_source_has_a_projection_arm(self):
        # SALE_SOURCES is the product decision -- the six statement types whose gross IS
        # the agency's sale. PROJECTED_SOURCES is what project_batch can actually write.
        # A source in the first and not the second is a headline missing a whole family,
        # and it would show as a smaller number rather than as an error.
        self.assertEqual(set(SALE_SOURCES) - set(PROJECTED_SOURCES), set())

    def test_the_two_unpriced_sources_are_not_claimed_to_have_an_adapter(self):
        # COMMISSION_SOURCES drives api/v1/income_board's freshness check, which looks
        # for a completed commission run per batch. ndc and tp-api have no adapter in
        # services/commission/__init__.py, so a batch of either can never have one --
        # folding them in here would report every upload as permanently "never
        # projected" and leave the Rebuild banner up for good.
        for s in ("ndc", "tp-api"):
            self.assertIn(s, PROJECTED_SOURCES, s)
            self.assertNotIn(s, COMMISSION_SOURCES, s)


class TestCountsInNet(unittest.TestCase):
    """`counts_in_net` is the Report Download's rule set, rendered into SQL.

    Two independently-written definitions of "does this line count" would hand finance
    two authoritative sale figures and no way to tell which is right.
    """

    def test_bsp_always_counts(self):
        counts, reason = counts_in_net_sql(SOURCE_BSP, "r")
        self.assertEqual(counts, "true")
        self.assertEqual(reason, "NULL")

    def test_a_consolidator_footer_line_is_excluded_before_its_status_is_read(self):
        # A statement's own total row has no status either, so testing the status first
        # would read it as an issue and add the statement's total to its own rows.
        counts, reason = counts_in_net_sql(SOURCE_TP_GDS, "s")
        # [0] is the text before the first WHEN, so the arms themselves start at [1].
        arms = counts.split("WHEN")[1:]
        self.assertIn("invoice_number", arms[0])
        self.assertIn("ticket_status", arms[1])
        self.assertNotIn("invoice_number", arms[1])
        self.assertIn(C.NET_SUMMARY_ONLY, reason)

    def test_a_cancelled_consolidator_line_is_not_a_sale(self):
        counts, reason = counts_in_net_sql(SOURCE_TP_GDS, "s")
        self.assertIn("'CANCELLED'", counts)
        self.assertIn(C.NET_NOT_A_SALE, reason)
        # ...but a void carrying its own negative net is the consolidator crediting us,
        # which IS a refund and does count.
        self.assertIn("< 0 THEN true", counts)

    def test_an_lcc_payment_movement_is_not_a_sale(self):
        counts, reason = counts_in_net_sql(SOURCE_LCC_DETAILED, "s")
        self.assertIn("'balance'", counts)
        self.assertIn("'payment'", counts)
        self.assertIn(C.NET_LCC_PAYMENT, reason)

    def test_every_reason_is_the_reports_own_wording(self):
        # One vocabulary, two screens. A reason this board invents would be a reason the
        # downloadable report never prints.
        known = {v for k, v in vars(C).items()
                 if k.startswith("NET_") and isinstance(v, str)}
        seen = set()
        for source in (SOURCE_BSP, SOURCE_TP_GDS, SOURCE_TP_LCC, SOURCE_LCC_DETAILED):
            _counts, reason = counts_in_net_sql(source, "s")
            # A reason always begins "No" -- every NET_* string except NET_YES does, and
            # NET_YES is never stored (the column is NULL when the row counts). Anything
            # else quoted in the expression is a status value it is comparing against.
            for quoted in re.findall(r"'((?:[^']|'')*)'", reason):
                text = quoted.replace("''", "'")
                if text.startswith("No"):
                    seen.add(text)
                    self.assertIn(text, known, f"{source}: {text!r}")
        # Not just "nothing invented" -- the rules that exist are actually rendered.
        self.assertTrue(
            {C.NET_SUMMARY_ONLY, C.NET_NOT_A_SALE, C.NET_CANCELLED_VERIFY,
             C.NET_LCC_PAYMENT} <= seen, sorted(seen))

    def test_an_unknown_source_raises(self):
        with self.assertRaises(ValueError):
            counts_in_net_sql("some-new-source", "s")


class TestPricedGuard(unittest.TestCase):
    """/dashboard/income must keep meaning what it meant before sale rows arrived.

    The table now holds every statement line, priced or not. A comment saying "remember
    the predicate" is not a guard; these are. Without them `IncomeTotals.rows` quietly
    stops meaning priced lines, `unattributed_airline_rows` absorbs every Third Party
    API row (no carrier, by nature), and the airline ranking fills up with carriers that
    earned nothing because nobody has costed them yet.
    """

    def test_filters_pins_priced_on_every_query_that_uses_it(self):
        # get_summary builds all five of its WHEREs from this one list.
        conds = income_board_api._filters(
            basis="issue", date_from=None, date_to=None,
            airline=None, supplier=None, source=None,
        )
        rendered = " ".join(_sql(c) for c in conds)
        self.assertIn("priced", rendered)

    def test_the_filter_pickers_pin_priced_separately(self):
        # get_filters' four queries do NOT go through _filters, so they need their own.
        src = inspect.getsource(income_board_api.get_filters)
        self.assertIn("R.priced.is_(True)", src)

    def test_the_revenue_measures_do_not_pin_priced(self):
        # The mirror image, and the reason the two boards can share one table: an
        # uploaded-but-uncosted statement is still a sale. Pinning `priced` here would
        # make the revenue tab understate every workspace that is behind on pricing.
        rendered = _sql(measures.sale_gross())
        self.assertNotIn("priced", rendered)
        self.assertIn("counts_in_net", rendered)


if __name__ == "__main__":
    unittest.main()
