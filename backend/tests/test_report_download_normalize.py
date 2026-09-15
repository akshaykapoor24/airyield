"""Report download — money, date and ticket-number normalisation.

Pinned: every DATE_PATTERNS layout (and the calendar check that rejects 31-Feb), the SQL twin
``date_key_sql`` compiling for Postgres, money text with Indian grouping / brackets / CR-DR,
blank never becoming 0, ``doc_key`` keeping leading zeros and expanding conjunctions, and the
BSP transaction-type canon.

No DB, no network by default.  Run: python -m unittest test_report_download_normalize   (from backend/tests)
Set REPORT_DB_TESTS=1 to also run ``date_key_sql`` on the local Postgres and compare every example
with ``date_key_py``.
"""
import asyncio
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import Date, DateTime, Text, column, literal, select, text  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download import normalize as N  # noqa: E402
from app.services.report_download.types import DocKey  # noqa: E402

JUL1 = date(2026, 7, 1)

# Every layout the contract names, with the date it must read as.
VALID_DATES: tuple[tuple[str, date], ...] = (
    ("2026-07-01", JUL1),
    ("2026-07-01 00:00:00", JUL1),
    ("2026-07-01T10:30:00", JUL1),
    ("2026/07/01", JUL1),
    ("01-Jul-2026", JUL1),
    ("01-Jul-2026 10:30", JUL1),
    ("1 July 2026", JUL1),
    ("15-Aug-26", date(2026, 8, 15)),
    ("01 Sep 26 13:41:15", date(2026, 9, 1)),
    ("23APR26", date(2026, 4, 23)),
    ("23APR2026", date(2026, 4, 23)),
    ("23apr26", date(2026, 4, 23)),
    ("01/07/2026", JUL1),
    ("01-07-2026", JUL1),
    ("01.07.2026", JUL1),
    ("1/7/2026", JUL1),
    ("01/07/26", JUL1),
    ("Jul 01, 2026", JUL1),
    ("July 1 2026", JUL1),
    ("46204", JUL1),
    ("46204.0", JUL1),
    ("46204.00", JUL1),
    ("20000", date(1954, 10, 3)),
    ("80000", date(2119, 1, 11)),
    ("29/02/2024", date(2024, 2, 29)),
    ("29-02-2000", date(2000, 2, 29)),
    ("29FEB24", date(2024, 2, 29)),
    ("  01/07/2026  ", JUL1),
    (" 01/07/2026\t", JUL1),
    ("01-Jul-2026\n", JUL1),
)

INVALID_DATES: tuple[str, ...] = (
    "2026-02-31", "31/02/2026", "29/02/2025", "29/02/2100", "31/04/2026", "31APR26", "29FEB25",
    "00/07/2026", "01/13/2026", "2026-13-01", "01-Xyz-2026", "Foo 01, 2026",
    "19999", "80001", "4620", "46204.5", "2026-7-1", "junk", "", "   ", "N/A", "0000-01-01",
)


class DateTests(unittest.TestCase):
    def test_every_contract_example(self):
        for raw, expected in VALID_DATES:
            with self.subTest(raw=raw):
                self.assertEqual(N.parse_report_date(raw), expected)

    def test_every_pattern_example_parses(self):
        for pat in N.DATE_PATTERNS:
            with self.subTest(pattern=pat.name):
                self.assertIsNotNone(N.parse_report_date(pat.example))

    def test_layouts_are_mutually_exclusive_on_examples(self):
        import re
        samples = [raw.strip(" \t\n\r ") for raw, _ in VALID_DATES]
        for s in samples:
            hits = [p.name for p in N.DATE_PATTERNS if re.fullmatch(p.regex, s, re.DOTALL)]
            with self.subTest(sample=s):
                self.assertEqual(len(hits), 1, hits)

    def test_invalid_calendar_dates_and_junk_are_none(self):
        for raw in INVALID_DATES:
            with self.subTest(raw=raw):
                self.assertIsNone(N.parse_report_date(raw))
        self.assertIsNone(N.parse_report_date(None))
        self.assertIsNone(N.parse_report_date(True))

    def test_date_and_datetime_objects_pass(self):
        self.assertEqual(N.parse_report_date(JUL1), JUL1)
        self.assertEqual(N.parse_report_date(datetime(2026, 7, 1, 23, 59)), JUL1)
        self.assertIsInstance(N.parse_report_date(datetime(2026, 7, 1, 23, 59)), date)
        self.assertNotIsInstance(N.parse_report_date(datetime(2026, 7, 1, 23, 59)), datetime)

    def test_two_digit_years_are_2000_plus(self):
        self.assertEqual(N.parse_report_date("01/07/99"), date(2099, 7, 1))
        self.assertEqual(N.parse_report_date("15-Aug-00"), date(2000, 8, 15))

    def test_date_key_py_agrees_with_parse_report_date(self):
        values = [raw for raw, _ in VALID_DATES] + list(INVALID_DATES) + [None, JUL1, datetime(2026, 7, 1, 10, 30)]
        for v in values:
            d = N.parse_report_date(v)
            with self.subTest(value=v):
                self.assertEqual(N.date_key_py(v), d.isoformat() if d else None)
        self.assertEqual(N.date_key_py("01-Jul-2026 10:30"), "2026-07-01")


class DateKeySqlCompileTests(unittest.TestCase):
    def _sql(self, expr) -> str:
        return str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    def test_compiles_for_postgres_with_literal_binds(self):
        sql = self._sql(N.date_key_sql(column("issue_date")))
        self.assertIn("btrim", sql)
        self.assertIn("regexp_match", sql)
        self.assertIn("CASE", sql)
        self.assertNotIn("%(", sql)                  # every bind rendered inline
        for pat in N.DATE_PATTERNS:
            self.assertIn(pat.regex, sql)

    def test_compiles_over_a_literal_and_typed_columns(self):
        for expr in (literal("01/07/2026", Text), column("d", Date), column("ts", DateTime)):
            with self.subTest(expr=str(expr)):
                self.assertTrue(self._sql(N.date_key_sql(expr)))

    def test_no_unguarded_casts_of_raw_text(self):
        # to_date only ever sees text that passed the calendar regex (substring(... from valid)).
        sql = self._sql(N.date_key_sql(column("x"))).lower()
        self.assertNotIn("::date", sql)
        self.assertEqual(sql.count("to_date("), sql.count("to_date(substring("))
        self.assertGreater(sql.count("to_date("), 0)


@unittest.skipUnless(os.environ.get("REPORT_DB_TESTS") == "1", "set REPORT_DB_TESTS=1 to run date_key_sql on the local DB")
class DateKeySqlDatabaseTests(unittest.TestCase):
    """``date_key_sql`` executed by Postgres must equal ``date_key_py`` for every example.

    normalize.py declares no approximation (the calendar is validated exactly in SQL), so the
    comparison is strict equality, valid and invalid values alike.
    """

    VALUES = [raw for raw, _ in VALID_DATES] + list(INVALID_DATES)

    @staticmethod
    def _run(fn):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from app.config import Settings, settings

        # Settings reads ".env" relative to the cwd; the tests run from backend/tests.
        env_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
        url = Settings(_env_file=env_file).DATABASE_URL if os.path.exists(env_file) else settings.DATABASE_URL

        async def go():
            engine = create_async_engine(url, poolclass=NullPool)
            try:
                async with engine.connect() as conn:
                    return await fn(conn)
            finally:
                await engine.dispose()

        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        return asyncio.run(go())

    def test_bound_parameters_match_python(self):
        values = self.VALUES

        async def q(conn):
            stmt = select(*[N.date_key_sql(literal(v, Text)).label(f"k{i}") for i, v in enumerate(values)])
            return list((await conn.execute(stmt)).one())

        got = self._run(q)
        for v, sql_key in zip(values, got):
            with self.subTest(value=v):
                self.assertEqual(sql_key, N.date_key_py(v))

    def test_literal_binds_sql_matches_python(self):
        # The rendered string is what a hand-built listing query would embed. Rendered with
        # the connection's own dialect: the psycopg2 default doubles "%" for its paramstyle.
        values = self.VALUES

        async def q(conn):
            parts = [
                str(N.date_key_sql(literal(v, Text)).compile(
                    dialect=conn.dialect, compile_kwargs={"literal_binds": True}))
                for v in values
            ]
            sql = "SELECT " + ", ".join(f"{p} AS k{i}" for i, p in enumerate(parts))
            return list((await conn.exec_driver_sql(sql)).one())

        got = self._run(q)
        for v, sql_key in zip(values, got):
            with self.subTest(value=v):
                self.assertEqual(sql_key, N.date_key_py(v))

    def test_typed_date_and_timestamp_columns(self):
        async def q(conn):
            stmt = select(
                N.date_key_sql(literal(JUL1, Date)),
                N.date_key_sql(literal(datetime(2026, 7, 1, 10, 30), DateTime)),
            )
            return list((await conn.execute(stmt)).one())

        self.assertEqual(self._run(q), ["2026-07-01", "2026-07-01"])

    def test_null_input(self):
        async def q(conn):
            return (await conn.execute(select(N.date_key_sql(literal(None, Text))))).scalar()

        self.assertIsNone(self._run(q))


class MoneyTests(unittest.TestCase):
    def test_text_forms(self):
        cases = {
            "1,23,456.78": Decimal("123456.78"),
            "1,234,567.00": Decimal("1234567.00"),
            "(285.72)": Decimal("-285.72"),
            "100-": Decimal("-100"),
            "-100": Decimal("-100"),
            "+100": Decimal("100"),
            "500 CR": Decimal("-500"),
            "500CR": Decimal("-500"),
            "500 DR": Decimal("500"),
            "₹ 1,234": Decimal("1234"),
            "Rs. 500": Decimal("500"),
            "INR 1,000.50": Decimal("1000.50"),
            " 12.50 ": Decimal("12.50"),
            " 12.50": Decimal("12.50"),
            ".5": Decimal("0.5"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                got = N.parse_money(raw)
                self.assertIsInstance(got, Decimal)
                self.assertEqual(got, expected)

    def test_blank_placeholders_are_none_not_zero(self):
        for raw in ("N/A", "-", "", "  ", "NIL", "--", None):
            with self.subTest(raw=raw):
                self.assertIsNone(N.parse_money(raw))
                self.assertEqual(N.parse_money_checked(raw), (None, False))

    def test_junk_is_none_and_flagged_unparseable(self):
        for raw in ("abc", "12,34", "1.234,56", "(500) CR", "-100-", "12.3.4", "CR"):
            with self.subTest(raw=raw):
                self.assertIsNone(N.parse_money(raw))
                self.assertEqual(N.parse_money_checked(raw), (None, True))

    def test_numeric_passthrough(self):
        self.assertEqual(N.parse_money(Decimal("1.50")), Decimal("1.50"))
        self.assertEqual(str(N.parse_money(Decimal("1.50"))), "1.50")
        self.assertEqual(N.parse_money(7), Decimal(7))
        self.assertEqual(N.parse_money(0.1), Decimal("0.1"))       # via str, not binary float
        self.assertEqual(N.parse_money(-2.5), Decimal("-2.5"))
        self.assertIsNone(N.parse_money(float("nan")))
        self.assertIsNone(N.parse_money(True))
        self.assertEqual(N.parse_money_checked(Decimal("NaN")), (None, True))

    def test_no_negative_zero(self):
        self.assertEqual(str(N.parse_money("-0.00")), "0.00")
        self.assertEqual(str(N.signed(Decimal("0"), C.REFUND)), "0")

    def test_signed_per_type_sign(self):
        self.assertEqual(N.signed(Decimal("-5"), C.SALE), Decimal("5"))
        self.assertEqual(N.signed(Decimal("5"), C.EXCHANGE), Decimal("5"))
        self.assertEqual(N.signed(Decimal("-5"), C.ADM), Decimal("5"))
        self.assertEqual(N.signed(Decimal("5"), C.REFUND), Decimal("-5"))
        self.assertEqual(N.signed(Decimal("-5"), C.REFUND), Decimal("-5"))
        self.assertEqual(N.signed(Decimal("5"), C.ACM), Decimal("-5"))
        # "as stored" types and unknown names keep the value
        self.assertEqual(N.signed(Decimal("-5"), C.VOID), Decimal("-5"))
        self.assertEqual(N.signed(Decimal("5"), C.AGENT_FEE), Decimal("5"))
        self.assertEqual(N.signed(Decimal("-5"), "NOT_A_TYPE"), Decimal("-5"))
        self.assertIsNone(N.signed(None, C.SALE))
        for canon, sign in C.TYPE_SIGN.items():
            with self.subTest(canon=canon):
                got = N.signed(Decimal("-3"), canon)
                self.assertEqual(got, Decimal("-3") if sign is None else Decimal(3 * sign))

    def test_magnitude(self):
        self.assertEqual(N.magnitude(Decimal("-3.25")), Decimal("3.25"))
        self.assertEqual(N.magnitude(Decimal("3.25")), Decimal("3.25"))
        self.assertIsNone(N.magnitude(None))

    def test_D_and_dsum(self):
        self.assertEqual(N.D(Decimal("2")), Decimal("2"))
        self.assertEqual(N.D(3), Decimal("3"))
        self.assertIsNone(N.D(None))
        self.assertIsNone(N.dsum())
        self.assertIsNone(N.dsum(None, None))
        self.assertEqual(N.dsum(None, Decimal("1.5"), 2, "1,000"), Decimal("1003.5"))
        self.assertEqual(N.dsum(Decimal("0"), None), Decimal("0"))       # a real zero stays


class TextTests(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(N.clean_text("  x "), "x")
        for v in (None, "", "   ", "nan", "NaN", "None", "NaT"):
            with self.subTest(v=v):
                self.assertIsNone(N.clean_text(v))
        self.assertEqual(N.clean_text("NAN"), "NAN")      # could be a real code or name
        self.assertEqual(N.clean_text(12), "12")

    def test_join_unique(self):
        self.assertEqual(N.join_unique(["L", "L", None, " ", "U"]), "L/U")
        self.assertEqual(N.join_unique(["A", "B"], sep=", "), "A, B")
        self.assertIsNone(N.join_unique([None, ""]))
        self.assertIsNone(N.join_unique(None))

    def test_zfill3(self):
        self.assertEqual(N.zfill3("98"), "098")
        self.assertEqual(N.zfill3(98), "098")
        self.assertEqual(N.zfill3("98.0"), "098")
        self.assertEqual(N.zfill3(" 176 "), "176")
        self.assertEqual(N.zfill3("ai"), "AI")
        self.assertEqual(N.zfill3("1234"), "1234")
        self.assertIsNone(N.zfill3(""))
        self.assertIsNone(N.zfill3(None))

    def test_stat_segment(self):
        self.assertEqual(N.stat_segment("I"), "International")
        self.assertEqual(N.stat_segment("D"), "Domestic")
        self.assertEqual(N.stat_segment(" d "), "Domestic")
        self.assertEqual(N.stat_segment("I71"), "International")
        self.assertEqual(N.stat_segment("INTL"), "International")
        self.assertEqual(N.stat_segment("dom"), "Domestic")
        self.assertEqual(N.stat_segment("xyz"), "XYZ")
        self.assertIsNone(N.stat_segment(""))
        self.assertIsNone(N.stat_segment(None))


K = DocKey


class DocKeyTests(unittest.TestCase):
    def test_structured_three_plus_ten(self):
        for raw in ("098 5805708071", "098-5805708071", "098-5805708071-3", "0985805708071", " 0985805708071 "):
            with self.subTest(raw=raw):
                self.assertEqual(N.doc_key(None, raw), K("098", "5805708071"))
                # the printed prefix wins over a declared code
                self.assertEqual(N.doc_key("176", raw), K("098", "5805708071"))

    def test_ten_digits_take_the_code(self):
        self.assertEqual(N.doc_key("98", "5805708071"), K("098", "5805708071"))
        self.assertEqual(N.doc_key(None, "5805708071"), K(None, "5805708071"))
        self.assertEqual(N.doc_key("098", 5805708071), K("098", "5805708071"))
        self.assertEqual(N.doc_key("098", "5805708071.0"), K("098", "5805708071"))

    def test_nine_digits_zero_filled(self):
        self.assertEqual(N.doc_key("98", "580570807"), K("098", "0580570807"))
        self.assertEqual(N.doc_key(None, "580570807"), K(None, "0580570807"))

    def test_twelve_digit_lost_leading_zero(self):
        self.assertEqual(N.doc_key(None, "985805708071"), K("098", "5805708071"))
        self.assertEqual(N.doc_key("098", "985805708071"), K("098", "5805708071"))
        self.assertEqual(N.doc_key("98", "985805708071"), K("098", "5805708071"))
        # a declared code that disagrees with the surviving prefix wins
        self.assertEqual(N.doc_key("176", "985805708071"), K("176", "5805708071"))
        self.assertEqual(N.doc_key(None, "15805708071"), K("001", "5805708071"))

    def test_fourteen_digits_drop_check_digit(self):
        self.assertEqual(N.doc_key(None, "09858057080713"), K("098", "5805708071"))

    def test_conjunction(self):
        self.assertEqual(N.doc_keys("98", "5800920932-933"), [K("098", "5800920932"), K("098", "5800920933")])
        self.assertEqual(N.doc_keys(None, "5800920932 - 933"), [K(None, "5800920932"), K(None, "5800920933")])
        self.assertEqual(N.doc_key("98", "5800920932-933"), K("098", "5800920932"))
        self.assertEqual(N.doc_keys(None, "0985800920932-933"), [K("098", "5800920932"), K("098", "5800920933")])
        # implausible range (tail below head) keeps only the printed head
        self.assertEqual(N.doc_keys("098", "5800920932-900"), [K("098", "5800920932")])

    def test_check_digit_form_is_not_a_conjunction(self):
        self.assertEqual(N.doc_keys(None, "098-5805708071-3"), [K("098", "5805708071")])

    def test_alphanumeric_memo(self):
        self.assertEqual(N.doc_key("98", "ADM12345X"), K("098", "ADM12345X"))
        self.assertEqual(N.doc_key("98", "adm-123 45x"), K("098", "ADM12345X"))
        self.assertEqual(N.doc_key(None, "ADM12345X"), K(None, "ADM12345X"))

    def test_blank_and_unusable(self):
        for raw in (None, "", "   ", "nan", "12345", "123-45", "----"):
            with self.subTest(raw=raw):
                self.assertIsNone(N.doc_key("098", raw))
                self.assertEqual(N.doc_keys("098", raw), [])

    def test_doc_key_is_first_of_doc_keys(self):
        for code, raw in (("98", "5800920932-933"), (None, "0985805708071"), ("98", "580570807"),
                          (None, "985805708071"), ("98", "ADM1"), (None, "0985800920932-933")):
            with self.subTest(raw=raw):
                self.assertEqual(N.doc_key(code, raw), N.doc_keys(code, raw)[0])

    def test_pack(self):
        self.assertEqual(N.pack(K("098", "5805708071")), 98 * 10**10 + 5805708071)
        self.assertIsInstance(N.pack(K("098", "0580570807")), int)
        self.assertNotEqual(N.pack(K("098", "0580570807")), N.pack(K("009", "8058057080")))
        self.assertEqual(N.pack(K(None, "5805708071")), "|5805708071")
        self.assertEqual(N.pack(K("098", "ADM12345X")), "098|ADM12345X")
        self.assertEqual(N.pack(K("AI", "5805708071")), "AI|5805708071")
        self.assertEqual(N.pack(K("098", "58057080711")), "098|58057080711")   # serial > 10 digits
        # codeless and coded never collide
        self.assertNotEqual(N.pack(K(None, "5805708071")), N.pack(K("000", "5805708071")))

    def test_ticket13(self):
        self.assertEqual(N.ticket13(None, "098 5805708071"), ("0985805708071", False))
        self.assertEqual(N.ticket13(None, "098-5805708071-3"), ("0985805708071", False))
        self.assertEqual(N.ticket13("98", "5805708071"), ("0985805708071", False))
        self.assertEqual(N.ticket13("98", "580570807"), ("0980580570807", True))
        self.assertEqual(N.ticket13(None, "5805708071"), ("5805708071", True))       # no code: as printed
        self.assertEqual(N.ticket13("98", "985805708071"), ("985805708071", True))   # lost zero: as printed
        self.assertEqual(N.ticket13("98", "5800920932-933"), ("5800920932-933", True))
        self.assertEqual(N.ticket13("AI", "5805708071"), ("5805708071", True))
        self.assertEqual(N.ticket13("98", " ADM123 "), ("ADM123", True))
        self.assertEqual(N.ticket13("98", ""), (None, False))
        self.assertEqual(N.ticket13("98", None), (None, False))


class CanonBspTests(unittest.TestCase):
    def test_codes(self):
        cases = {
            "TKTT": C.SALE, "EXCH": C.EXCHANGE, "RFND": C.REFUND, "RFDA": C.REFUND,
            "EMDS": C.EMD, "EMDA": C.EMD, "ADMA": C.ADM, "ADMD": C.ADM, "SPDR": C.ADM,
            "ACMA": C.ACM, "ACMD": C.ACM, "SPCR": C.ACM, "CANX": C.CANCELLATION, "CANN": C.CANCELLATION,
            "VOID": C.VOID, "TASF": C.AGENT_FEE,
        }
        for raw, canon in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(N.canon_bsp_txn(raw, None), (canon, False))

    def test_tktt_with_exchange_is_exchange(self):
        self.assertEqual(N.canon_bsp_txn("TKTT", {"exchanges": [{"doc": "5805708071"}]}), (C.EXCHANGE, False))
        self.assertEqual(N.canon_bsp_txn("TKTT", '{"exchanges": [{"doc": "5805708071"}]}'), (C.EXCHANGE, False))
        self.assertEqual(N.canon_bsp_txn("TKTT", {"exchanges": []}), (C.SALE, False))
        self.assertEqual(N.canon_bsp_txn("TKTT", {"exchanges": [{"doc": None}]}), (C.SALE, False))
        self.assertEqual(N.canon_bsp_txn("TKTT", "not json"), (C.SALE, False))

    def test_legacy_lower_case(self):
        self.assertEqual(N.canon_bsp_txn("refund", None), (C.REFUND, True))
        self.assertEqual(N.canon_bsp_txn("adm", None), (C.ADM, True))
        self.assertEqual(N.canon_bsp_txn("acm", None), (C.ACM, True))
        self.assertEqual(N.canon_bsp_txn("sale", None), (C.SALE, True))
        self.assertEqual(N.canon_bsp_txn("tktt", None), (C.SALE, True))
        self.assertEqual(N.canon_bsp_txn("Refund", None), (C.REFUND, True))

    def test_blank_and_unknown(self):
        self.assertEqual(N.canon_bsp_txn(None, None), (C.UNKNOWN, False))
        self.assertEqual(N.canon_bsp_txn("", None), (C.UNKNOWN, False))
        self.assertEqual(N.canon_bsp_txn("ZZZZ", None), (C.UNKNOWN, False))


if __name__ == "__main__":
    unittest.main()
