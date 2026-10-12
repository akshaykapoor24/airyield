"""The Create Ticket charge quote: a User-master rate turned into a ticket's figures."""
import unittest

from app.api.v1.ticket_charges import _quote


class QuoteTests(unittest.TestCase):
    def test_percentage_of_fare_gst_extra(self):
        q = _quote(10000, "percentage", 2, "exclusive", "Agency Master")
        self.assertEqual((q.amount, q.taxable, q.gst, q.gross), (200.0, 200.0, 36.0, 236.0))
        self.assertEqual(q.note, "2% of fare · GST extra")

    def test_fixed_inclusive_backs_tax_out(self):
        q = _quote(10000, "fixed", 1000, "inclusive", "Agency Master")
        self.assertEqual((q.amount, q.taxable, q.gst, q.gross), (1000.0, 847.46, 152.54, 1000.0))
        self.assertEqual(q.note, "₹1000 per ticket · incl. GST")

    def test_unset_rate_quotes_nothing(self):
        self.assertIsNone(_quote(10000, None, None, "exclusive", "Agency Master"))
        self.assertIsNone(_quote(10000, "percentage", None, "exclusive", "Agency Master"))

    def test_zero_rate_is_a_real_answer(self):
        q = _quote(10000, "fixed", 0, None, "Corporate Master")
        self.assertEqual((q.amount, q.gst, q.gst_treatment), (0.0, 0.0, "exclusive"))


if __name__ == "__main__":
    unittest.main()
