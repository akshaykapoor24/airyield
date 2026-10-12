"""Agency Code issuing — auto sequence, manual codes, and the pattern hand-over.

The allocator is exercised directly with a preloaded book, so these need no DB.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.agency_code import Allocator, format_error, normalise, parse  # noqa: E402


def book(*rows):
    """rows: (code, name, branch) oldest first."""
    codes = [(i + 1, c) for i, (c, _n, _b) in enumerate(rows)]
    holders = {c: (n.lower(), b.lower()) for c, n, b in rows}
    return Allocator(1, codes, holders)


class ParseTest(unittest.TestCase):
    def test_last_digit_run_is_the_counter(self):
        p, n = parse("B2B-12-M")
        self.assertEqual((p.prefix, n, p.suffix, p.width), ("B2B-", 12, "-M", 2))

    def test_no_digits_no_pattern(self):
        self.assertIsNone(parse("LORDS"))

    def test_normalise_and_format(self):
        self.assertEqual(normalise("  lt / del 9 "), "LT/DEL9")
        self.assertIsNone(format_error("AG-0001"))
        self.assertIsNotNone(format_error("-AG"))
        self.assertIsNotNone(format_error("AG#1"))
        self.assertIsNotNone(format_error("A" * 31))


class AutoTest(unittest.TestCase):
    def test_empty_book_starts_at_default(self):
        self.assertEqual(book().resolve(None, "Lords", "DEL"), "AG-0001")

    def test_continues_sequence_and_batches_do_not_repeat(self):
        a = book(("AG-0001", "A", "MAIN"), ("AG-0002", "B", "MAIN"))
        self.assertEqual(a.resolve("", "C", "MAIN"), "AG-0003")
        self.assertEqual(a.resolve(None, "D", "MAIN"), "AG-0004")

    def test_gap_continues_from_highest(self):
        a = book(("AG-0009", "A", "MAIN"), ("AG-0003", "B", "MAIN"))
        self.assertEqual(a.resolve(None, "C", "MAIN"), "AG-0010")

    def test_rolls_past_width(self):
        self.assertEqual(book(("AG-9999", "A", "MAIN")).resolve(None, "B", "MAIN"), "AG-10000")

    def test_other_channel_reuses_branch_code(self):
        a = book(("AG-0001", "Lords", "DEL"))
        self.assertEqual(a.resolve(None, "lords", "del"), "AG-0001")
        self.assertEqual(a.resolve(None, "Lords", "BOM"), "AG-0002")


class ManualTest(unittest.TestCase):
    def test_manual_code_sets_the_pattern(self):
        a = book(("AG-0001", "A", "MAIN"))
        self.assertEqual(a.resolve("lt-105", "Lords", "DEL"), "LT-105")
        self.assertEqual(a.resolve(None, "Riya", "MAIN"), "LT-106")

    def test_short_manual_padded_to_current_pattern(self):
        a = book(("AG-0042", "A", "MAIN"))
        self.assertEqual(a.resolve("ag-7", "B", "MAIN"), "AG-0007")
        self.assertEqual(a.resolve(None, "C", "MAIN"), "AG-0043")

    def test_code_without_digits_is_a_one_off(self):
        a = book(("AG-0001", "A", "MAIN"))
        self.assertEqual(a.resolve("LORDS", "B", "MAIN"), "LORDS")
        self.assertEqual(a.resolve(None, "C", "MAIN"), "AG-0002")

    def test_clash_with_another_agency_refused(self):
        a = book(("AG-0001", "A", "MAIN"))
        with self.assertRaises(ValueError):
            a.resolve("ag-0001", "B", "MAIN")

    def test_sibling_may_share(self):
        a = book(("AG-0001", "Lords", "DEL"))
        self.assertEqual(a.resolve("AG-0001", "Lords", "DEL"), "AG-0001")

    def test_bad_format_refused(self):
        with self.assertRaises(ValueError):
            book().resolve("#12", "A", "MAIN")



class CorporateBookTest(unittest.TestCase):
    """The same allocator on the corporate book: CO- default, no sibling sharing."""

    def book(self, *codes):
        from app.services.corporate_code import DEFAULT_PATTERN
        return Allocator(1, [(i + 1, c) for i, c in enumerate(codes)],
                         {c: (f"#{i + 1}", "") for i, c in enumerate(codes)},
                         default=DEFAULT_PATTERN, label="corporate")

    def test_starts_at_co(self):
        self.assertEqual(self.book().resolve(None, "\x00new", ""), "CO-0001")

    def test_typed_pattern_continues(self):
        a = self.book("CO-0001")
        self.assertEqual(a.resolve("corp/105", "\x00row0", ""), "CORP/105")
        self.assertEqual(a.resolve(None, "\x00row1", ""), "CORP/106")

    def test_no_sharing(self):
        with self.assertRaises(ValueError) as cm:
            self.book("CO-0001").resolve("co-0001", "\x00new", "")
        self.assertIn("corporate", str(cm.exception))

    def test_edit_keeps_own_code(self):
        # the row being edited is excluded from the book, so its own code is free
        self.assertEqual(self.book("CO-0002").resolve("CO-0001", "#1", ""), "CO-0001")


if __name__ == "__main__":
    unittest.main()
