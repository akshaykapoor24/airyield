"""Internal Statement keeps a multi-sector ticket as one row (split_legs=False)."""
import unittest

from app.services.ticket_extraction import derive_ticket_rows


class KeepWholeTests(unittest.TestCase):
    def test_money_is_not_divided(self):
        rows = derive_ticket_rows(
            [{"ticket_number": "607 5808583279", "sector": "IST-AUH-DEL-   -",
              "sell_fare": 36045.0, "total_amt": 54978.0, "dis_sell": 205.81}],
            False, split_legs=False,
        )
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["sell_fare"], r["total_amt"], r["dis_sell"]), (36045.0, 54978.0, 205.81))
        self.assertEqual([(s["origin"], s["destination"]) for s in r["segments"]],
                         [("IST", "AUH"), ("AUH", "DEL")])
        self.assertEqual(r["split_type"], "normal")

    def test_international_if_any_leg_is(self):
        # Starts and ends in India, but the middle leg is not domestic.
        r = derive_ticket_rows([{"ticket_number": "1", "sector": "DEL/DXB DXB/BOM"}],
                               False, split_legs=False)[0]
        self.assertEqual(r["segment_type"], "International")

    def test_all_domestic_legs(self):
        r = derive_ticket_rows([{"ticket_number": "1", "sector": "DEL/BOM BOM/DEL"}],
                               False, split_legs=False)[0]
        self.assertEqual(r["segment_type"], "Domestic")

    def test_punched_leg_type_wins(self):
        r = derive_ticket_rows([{
            "ticket_number": "1", "sector": "DEL/BOM BOM/DEL",
            "segments": [{"origin": "DEL", "destination": "BOM", "segment_type": "International"},
                         {"origin": "BOM", "destination": "DEL", "segment_type": None}],
        }], False, split_legs=False)[0]
        self.assertEqual(r["segment_type"], "International")

    def test_default_still_splits(self):
        rows = derive_ticket_rows([{"ticket_number": "1", "sector": "DEL/BOM BOM/DEL",
                                    "sell_fare": 100.0}], False)
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
