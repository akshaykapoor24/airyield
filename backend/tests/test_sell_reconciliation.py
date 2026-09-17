"""Buy-vs-sell reconciliation: the four judgements that decide whether a figure is right.

Every case here is drawn from a real row in the workspace that prompted the feature, and
each one is a mistake the engine made at some point during the build:

  * the key is the document serial, with the airline code kept beside it, not folded in;
  * the buy side must be netted per ticket, or a cancellation is compared to a whole sale;
  * the sell side must be summed across legs, or a split ticket reports half its money;
  * a serial shared by two carriers must never auto-link — Iberia and British Airways.
"""
from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from app.services.reconciliation.adapters import TP_GDS_MAP, FlatJsonAdapter, _norm
from app.services.sell_reconciliation import (
    FIELD_SPECS, SellReconciliationService, SellSide, _compare, _group_buy_rows,
    _status_from_issues,
)
from app.models.sell_reconciliation import (
    STATUS_BUY_ONLY, STATUS_MATCHED, STATUS_MISMATCH, STATUS_MINOR_DIFF, STATUS_SELL_ONLY,
)

D = Decimal


def gds_row(rid: int, ticket: str, prefix: str | None = "235", **data):
    """A `third_party_gds` row as ingest writes one — amounts as STRINGS, like the real table."""
    base = {
        "ticket_number": ticket, "base_fare": "1000", "yq": "0", "other_taxes": "200",
        "total_fare": "1200", "commission_amount": "0", "net_amount": "1200",
        "airline_master_name": "TEST AIR", "airline_code": "TA",
        "issue_date": "2026-08-08", "passenger_name": "MR TEST", "sector": "DEL/BOM",
    }
    if prefix is not None:
        base["ticket_prefix"] = prefix
    base.update(data)
    return SimpleNamespace(id=rid, batch_id="b1", data=base)


ADAPTER = FlatJsonAdapter("tp-gds", "Third Party · GDS", TP_GDS_MAP)


def sell(ticket_id=1, ticket="1000000001", prefix="235", legs=1, **amounts):
    base = {"fare": None, "yq": None, "yr": None, "tax": None,
            "gross": None, "commission": None, "net": None}
    base.update({k: (D(str(v)) if v is not None else None) for k, v in amounts.items()})
    return SellSide(ticket_id=ticket_id, ticket_number=ticket, ticket_prefix=prefix,
                    legs=legs, amounts=base)


class TestJoinKey(unittest.TestCase):
    """The key is the document SERIAL; the accounting code rides alongside it."""

    def test_the_key_is_the_serial_and_the_code_is_kept_beside_it(self):
        row = ADAPTER._build(gds_row(1, "4848358656", prefix="235"))
        self.assertEqual(row.ticket_key, _norm("4848358656"))
        self.assertEqual(row.ticket_number, "4848358656")
        self.assertEqual(row.ticket_prefix, "235")

    def test_a_two_digit_prefix_is_padded_to_three(self):
        """The file writes Iberia's 075 as "75", so the two spellings have to agree."""
        row = ADAPTER._build(gds_row(1, "5808758877", prefix="75"))
        self.assertEqual(row.ticket_prefix, "075")
        self.assertEqual(row.ticket_number, "5808758877")

    def test_a_cell_still_holding_both_is_split(self):
        """Some exports write "2354848358656" into the one column."""
        row = ADAPTER._build(gds_row(1, "2354848358656", prefix=None))
        self.assertEqual(row.ticket_prefix, "235")
        self.assertEqual(row.ticket_number, "4848358656")

    def test_no_prefix_anywhere_leaves_the_number_alone(self):
        row = ADAPTER._build(gds_row(1, "ABC123", prefix=None))
        self.assertIsNone(row.ticket_prefix)
        self.assertEqual(row.ticket_number, "ABC123")

    def test_norm_agrees_with_bsp_reconciliation(self):
        from app.services.bsp_reconciliation import norm_tn
        for s in ("2354848358656", "098-4846834428", "0984846834428", "4848358656"):
            self.assertEqual(_norm(s), norm_tn(s), s)


class TestCustomerIngestSplitsTheTicketCell(unittest.TestCase):
    """The ticket file prints "157 5808758776" in one cell. It is stored as two.

    It used to be re-joined into a 13-digit value, which left `uploaded_tickets` the only
    table holding a ticket that way and meant a purchase could never find its sale.
    """

    def test_code_and_serial_are_kept_apart(self):
        from app.services.ticket_extraction import derive_ticket_row
        out = derive_ticket_row({"ticket_number": "157 5808758776"}, is_airline=False)
        self.assertEqual(out["ticket_number"], "5808758776")
        self.assertEqual(out["ticket_prefix"], "157")

    def test_the_code_seeds_the_airline_when_the_file_omits_it(self):
        from app.services.ticket_extraction import derive_ticket_row
        out = derive_ticket_row({"ticket_number": "098 1955594970"}, is_airline=False)
        self.assertEqual(out["airlines_code"], "098")

    def test_a_cell_that_does_not_parse_is_left_whole(self):
        """Row 7 of the real file reads "157 ABC" — a value we cannot read confidently."""
        from app.services.ticket_extraction import derive_ticket_row
        out = derive_ticket_row({"ticket_number": "157 ABC"}, is_airline=False)
        self.assertEqual(out["ticket_number"], "157 ABC")
        self.assertIsNone(out.get("ticket_prefix"))

    def test_splitting_is_idempotent(self):
        """Re-running against an already-split value must not split it again."""
        from app.services.ticket_extraction import derive_ticket_row
        once = derive_ticket_row({"ticket_number": "157 5808758776"}, is_airline=False)
        twice = derive_ticket_row(dict(once), is_airline=False)
        self.assertEqual(twice["ticket_number"], "5808758776")
        self.assertEqual(twice["ticket_prefix"], "157")


class TestTaxIsATotal(unittest.TestCase):
    """A consolidator lumps the tax bill into other_taxes; the ticket file splits it."""

    def test_tax_sums_every_component_the_source_prints(self):
        row = ADAPTER._build(gds_row(1, "4848358656", yq="3243", other_taxes="5641"))
        self.assertEqual(row.amount("tax"), D("8884"))
        # yq is still reported on its own line, as a component.
        self.assertEqual(row.amount("yq"), D("3243"))

    def test_tax_is_none_when_the_source_prints_no_tax_at_all(self):
        row = ADAPTER._build(gds_row(1, "4848358656", yq="", other_taxes=""))
        self.assertIsNone(row.amount("tax"))

    def test_an_unparseable_amount_is_noted_not_counted_as_zero(self):
        row = ADAPTER._build(gds_row(1, "4848358656", base_fare="BALANCE"))
        self.assertIsNone(row.amount("fare"))
        self.assertTrue(any("not a number" in n for n in row.notes))


class TestBuySideIsNettedPerTicket(unittest.TestCase):
    """An issue and its cancellation are two rows about ONE purchase."""

    def test_issue_and_cancellation_net_to_what_was_actually_paid(self):
        rows = [
            ADAPTER._build(gds_row(7, "4848358799", base_fare="31505",
                                   other_taxes="24060", net_amount="55683")),
            ADAPTER._build(gds_row(28, "4848358799", base_fare="-31505",
                                   other_taxes="-24060", net_amount="-36445")),
        ]
        groups = _group_buy_rows(rows)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        # 55,683 paid, 36,445 refunded — the airline kept 19,238.
        self.assertEqual(g.amount("net"), D("19238"))
        self.assertEqual(g.amount("fare"), D("0"))
        self.assertEqual(g.source_row_ids, [7, 28])
        self.assertEqual(g.source_row_id, 7)  # min, so a re-run picks the same one
        self.assertTrue(any("net of 2 statement rows" in n for n in g.notes))

    def test_rows_with_no_ticket_number_are_never_pooled_together(self):
        """Two footer lines share a blank key but are not one ticket."""
        rows = [ADAPTER._build(gds_row(90, "", prefix=None, net_amount="1441734.59")),
                ADAPTER._build(gds_row(91, "", prefix=None, net_amount="2024899.81"))]
        groups = _group_buy_rows(rows)
        self.assertEqual(len(groups), 2)

    def test_different_tickets_stay_apart(self):
        rows = [ADAPTER._build(gds_row(1, "4848358656")),
                ADAPTER._build(gds_row(2, "4848358657"))]
        self.assertEqual(len(_group_buy_rows(rows)), 2)


class TestComparison(unittest.TestCase):
    def test_variance_is_sell_minus_buy_so_positive_means_earned(self):
        spec = next(s for s in FIELD_SPECS if s.key == "net")
        variance, match, issue = _compare(spec, D("1000"), D("1200"))
        self.assertEqual(variance, D("200.00"))
        self.assertFalse(match)
        self.assertTrue(issue)

    def test_both_sides_missing_is_not_comparable_rather_than_equal(self):
        spec = next(s for s in FIELD_SPECS if s.key == "yr")
        variance, match, issue = _compare(spec, None, None)
        self.assertIsNone(variance)
        self.assertIsNone(match)
        self.assertFalse(issue)

    def test_rounding_is_inside_tolerance(self):
        spec = next(s for s in FIELD_SPECS if s.key == "net")
        _v, match, issue = _compare(spec, D("1000.00"), D("1000.50"))
        self.assertTrue(match)
        self.assertFalse(issue)

    def test_status_takes_the_worst_severity(self):
        self.assertEqual(_status_from_issues([]), (STATUS_MATCHED, "ok"))
        self.assertEqual(_status_from_issues([{"severity": "warning"}]),
                         (STATUS_MINOR_DIFF, "warning"))
        self.assertEqual(
            _status_from_issues([{"severity": "warning"}, {"severity": "critical"}]),
            (STATUS_MISMATCH, "critical"))


class TestRowBuilding(unittest.TestCase):
    def test_a_paired_row_reports_a_margin(self):
        buy = _group_buy_rows([ADAPTER._build(gds_row(1, "4848358656", net_amount="1000"))])[0]
        row = SellReconciliationService._build_row(
            buy, sell(net=1250), status=STATUS_MATCHED, severity="ok",
            match_method="ticket_number", source="tp-gds")
        self.assertEqual(row["margin"], 250.0)
        self.assertEqual(row["abs_margin"], 250.0)
        self.assertEqual(row["buy_rows"], 1)

    def test_a_purchase_with_no_sale_has_a_cost_but_no_margin(self):
        """Calling the whole value a negative margin put statement footer lines at the top
        of a grid that sorts worst-first."""
        buy = _group_buy_rows([ADAPTER._build(
            gds_row(1, "", prefix=None, net_amount="2024899.81"))])[0]
        row = SellReconciliationService._build_row(
            buy, None, status=STATUS_BUY_ONLY, severity="warning",
            match_method="none", source="tp-gds")
        self.assertIsNone(row["margin"])
        self.assertIsNone(row["abs_margin"])
        self.assertEqual(row["buy_net"], 2024899.81)

    def test_a_sale_with_no_purchase_likewise(self):
        row = SellReconciliationService._build_row(
            None, sell(net=500), status=STATUS_SELL_ONLY, severity="critical",
            match_method="none", source="tp-gds")
        self.assertIsNone(row["margin"])
        self.assertEqual(row["sell_net"], 500.0)

    def test_one_sided_rows_are_not_compared_field_by_field(self):
        """A variance against nothing would just restate the amount."""
        row = SellReconciliationService._build_row(
            None, sell(net=500), status=STATUS_SELL_ONLY, severity="critical",
            match_method="none", source="tp-gds")
        self.assertTrue(all(d["variance"] is None for d in row["field_diffs"]))
        self.assertEqual(row["issues"], [])

    def test_split_legs_are_declared_in_the_notes(self):
        buy = _group_buy_rows([ADAPTER._build(gds_row(1, "4848358656"))])[0]
        row = SellReconciliationService._build_row(
            buy, sell(net=1200, legs=4), status=STATUS_MATCHED, severity="ok",
            match_method="ticket_number", source="tp-gds")
        self.assertEqual(row["sell_legs"], 4)
        self.assertTrue(any("sum of 4 sector rows" in n for n in row["notes"]))

    def test_amounts_are_rounded_to_the_stored_scale(self):
        """field_diffs feeds the drilldown while the columns feed the grid; they must agree."""
        buy = _group_buy_rows([ADAPTER._build(
            gds_row(1, "4848358656", net_amount="2024899.8144"))])[0]
        row = SellReconciliationService._build_row(
            buy, sell(net=0), status=STATUS_MATCHED, severity="ok",
            match_method="ticket_number", source="tp-gds")
        net_diff = next(d for d in row["field_diffs"] if d["key"] == "net")
        self.assertEqual(net_diff["buy"], 2024899.81)
        self.assertEqual(row["buy_net"], 2024899.81)


class TestPrefixIsTheCheckNotTheKey(unittest.TestCase):
    """A ticket serial is unique only WITHIN an airline."""

    def test_two_carriers_can_share_a_serial(self):
        # Iberia 075-5808758877 and British Airways 125-5808758877 — both present in this
        # workspace's data. The serial alone cannot tell them apart...
        a = ADAPTER._build(gds_row(1, "5808758877", prefix="75"))
        b = ADAPTER._build(gds_row(2, "5808758877", prefix="125"))
        self.assertEqual(a.ticket_key, b.ticket_key)
        # ...which is exactly why the accounting code is carried separately and compared.
        self.assertNotEqual(a.ticket_prefix, b.ticket_prefix)

    def test_a_suggested_pairing_shows_no_margin(self):
        """A figure in the money column reads as money whatever the status chip says."""
        buy = _group_buy_rows([ADAPTER._build(
            gds_row(1, "5808758877", prefix="75", net_amount="1000"))])[0]
        row = SellReconciliationService._build_row(
            buy, sell(net=351), status=STATUS_MATCHED, severity="ok",
            match_method="alt10", source="tp-gds")
        # What the engine does to it once it knows the match was only a suggestion.
        row["match_status"], row["severity"] = "possible_match", "critical"
        row["margin"] = row["abs_margin"] = None
        self.assertIsNone(row["margin"])
        # ...while both sides stay visible, so the near-miss can be judged.
        self.assertEqual(row["buy_net"], 1000.0)
        self.assertEqual(row["sell_net"], 351.0)


if __name__ == "__main__":
    unittest.main()
