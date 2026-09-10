"""Merging a two-file LCC statement into one row set.

The ACCOUNT statement is the spine: one imported row per `AG` transaction, with the
passenger, sectors and base fare joined in from the passenger report on PNR, and tax
derived as `total - base fare`. `lcc_merge` therefore decides how many rows a statement
becomes and how much money sits on each, so its mistakes are money mistakes: let a
non-AG line through and a running balance imports as a sale; sum the base fare per
passenger instead of per booking and the derived tax is wrong on every multi-passenger
PNR; default a missing base fare to zero and the whole transaction reads as tax.

The fixtures are the real sampled rows, not invented ones — the awkward cases
(mixed-case names, one passenger on two one-way PNRs, a three-passenger PNR, a
funds-added/funds-used transfer pair, statement-balance lines with no payment method)
are awkward because real data is.

No DB, no network — lcc_merge is pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import lcc_merge as m  # noqa: E402
from app.services import lcc_detailed_spec as spec  # noqa: E402
from app.api.v1.lcc_detailed import _bill_kind  # noqa: E402


PAX_COLUMNS = [
    "sourceOrganization", "organizationName", "BookingDate", "BookingTime",
    "RecordLocator", "PaxFirstName", "PaxLastName", "PaxType",
    "Depart_Station", "Arrive_Station", "DepartureDate", "DepartureCarrierCode",
    "FlightNumber", "CurrencyCode", "BaseFare", "Tax", "TransactionFee",
    "OtherServices", "TotalFare",
]

ACCOUNT_COLUMNS = [
    "SourceOrganization", "OrganizationName", "AccountTransactionID", "ACAmount",
    "TransactionDate", "AccountTransactionType", "PaymentMethodCode", "Reference",
    "PNR", "ParentPNR", "CurrencyCode", "ForeignAmount", "ForeignCurrencyCode",
    "BookingContactNumber", "Note", "EmailAddress", "GSTCompanyName", "GSTNumber",
    "GSTEmailAddress", "BookingPromoCode", "SSRCode", "FeeCode", "CreatedAgentCode",
]


def pax(bdate, btime, pnr, first, last, dep, arr, depdate, flight,
        base, tax, fee, total, other="", ptype=""):
    return dict(zip(PAX_COLUMNS, [
        "IN00002059", "MONEYYATRA", bdate, btime, pnr, first, last, ptype,
        dep, arr, depdate, "IX", flight, "INR", base, tax, fee, other, total,
    ]))


def acct(txn_id, date, ttype, pnr, parent, amount, note, gst_no="", gst_co="",
         fee_code="", email="", phone="", agent="refundadmin"):
    return dict(zip(ACCOUNT_COLUMNS, [
        "IN00002059", "MONEYYATRA", txn_id, "8894431", date, ttype,
        "AG" if pnr else "", pnr or "Statement Balance", pnr, parent, "INR",
        amount, "INR", phone, note, email, gst_co, gst_no, email,
        "SNDL1880", "", fee_code, agent,
    ]))


# The sampled passenger file. S86NWJ is one passenger over two legs; V2L7YL is two
# passengers on one flight; H27R7V is three; N4FFNS and K65EWM are cancellations, all
# negative; M7TW6G and D1EZFY are one passenger's outbound and return sold as two PNRs.
SAMPLE_PAX = [
    pax("01 Sep 26", "13:41:15", "S86NWJ", "MADHU", "MAYOORI", "BLR", "DED", "2026-09-02", "1506", "0", "100", "0", "100"),
    pax("01 Sep 26", "13:41:15", "S86NWJ", "MADHU", "MAYOORI", "IXE", "BLR", "2026-09-02", "2923", "7008", "2410", "245", "9663"),
    pax("02 Sep 26", "15:46:51", "V2L7YL", "ASHISH", "RAI", "HYD", "BLR", "2026-09-09", "1378", "5511", "1775", "193", "7479"),
    pax("02 Sep 26", "15:46:51", "V2L7YL", "ATUL", "Singh", "HYD", "BLR", "2026-09-09", "1378", "5511", "1775", "193", "7479"),
    pax("02 Sep 26", "17:25:51", "H27R7V", "Harsha Jyoti", "Bairagi", "GAU", "JAI", "2026-09-14", "1514", "4923", "2376", "172", "7471"),
    pax("02 Sep 26", "17:25:51", "H27R7V", "Lakshya Jyoti", "Bairagi", "GAU", "JAI", "2026-09-14", "1514", "4923", "2376", "172", "7471"),
    pax("02 Sep 26", "17:25:51", "H27R7V", "Moni Mala", "Sarmah", "GAU", "JAI", "2026-09-14", "1514", "4923", "2376", "172", "7471"),
    pax("04 Aug 26", "01:03:09", "N4FFNS", "Madhu", "MAYOORI", "DEL", "IXE", "2026-09-07", "1782", "-6391", "-2060", "-224", "-8675"),
    pax("04 Aug 26", "11:20:41", "K65EWM", "Madhu", "MAYOORI", "BLR", "DED", "2026-09-02", "1506", "-6276", "-100", "0", "-6376"),
    pax("04 Aug 26", "11:20:41", "K65EWM", "Madhu", "MAYOORI", "IXE", "BLR", "2026-09-02", "2923", "-1935", "-2473", "-287", "-4695"),
    pax("31 Aug 26", "10:47:29", "M7TW6G", "RIPUL", "BERRY", "DEL", "IXR", "2026-09-03", "1046", "5461", "1430", "191", "7082"),
    pax("31 Aug 26", "10:49:36", "D1EZFY", "RIPUL", "BERRY", "IXR", "DEL", "2026-09-03", "1053", "4710", "2197", "165", "7072"),
]

# The sampled account file: a balance snapshot (no payment method), a refund, a
# funds-added / funds-used transfer pair, and a booking payment.
SAMPLE_ACCOUNT = [
    acct("58849215", "2026-08-15T01:49:20.513+0000", "StatementDateAndBalance", "", "", "-27805",
         "Prepaid Account - Statement Date: 8/14/2026 6:59:59 PM"),
    acct("58854080", "2026-08-15T08:13:17.043+0000", "PPAccountCredit", "RE7F7R", "DB5MNK", "5073",
         "Refund by utility: PMTID:496210023, RL:RE7F7R",
         gst_no="07AAACO2563P1Z3", gst_co="ORIX CORPORATION INDIA LTD", fee_code="CXL2"),
    acct("58979276", "2026-08-18T15:10:00.050+0000", "PPAccountCredit", "J7IL8G", "", "8356",
         "Funds Added: J7IL8G"),
    acct("58979277", "2026-08-18T15:10:00.057+0000", "PPAccountDebitForPayment", "IBWGPK", "J7IL8G", "-8356",
         "Funds Used: IBWGPK"),
    acct("58896436", "2026-08-16T13:32:44.967+0000", "PPAccountDebitForPayment", "D49GSC", "", "-5516",
         "Funds Used: D49GSC",
         gst_no="07AAACZ6844Q1ZI", gst_co="ZELLEVEN HEALTHCARE", fee_code="SEAT,VFPF"),
]


def run(pax_rows=None, acct_rows_in=None, airline_code="IX"):
    return m.merge(pax_rows or [], PAX_COLUMNS, acct_rows_in or [], ACCOUNT_COLUMNS,
                   airline_code=airline_code)


def by_pnr(rows):
    """{RecordLocator: [row]} for a passenger file imported on its own."""
    out = {}
    for r in rows:
        if r.row_kind == m.ROW_KIND_PAX:
            out.setdefault(r.data.get("RecordLocator"), []).append(r)
    return out


def transactions(rows):
    """{PNR: MergedRow} for the transactions that survived the AG filter."""
    return {r.data.get("PNR"): r for r in rows}


class TestClassify(unittest.TestCase):
    def test_recognises_each_file(self):
        self.assertEqual(m.classify(ACCOUNT_COLUMNS), m.ROLE_ACCOUNT)
        self.assertEqual(m.classify(PAX_COLUMNS), m.ROLE_PAX)

    def test_indigo_template_is_single(self):
        """The template now carries AccountTransactionType among its columns, so an
        account-marker test run first would call every IndiGo upload an account file."""
        self.assertEqual(m.classify(spec.LCC_STANDARD_HEADERS), m.ROLE_SINGLE)

    def test_column_order_and_separators_are_irrelevant(self):
        self.assertEqual(m.classify(list(reversed(PAX_COLUMNS))), m.ROLE_PAX)
        self.assertEqual(m.classify([c.upper() for c in ACCOUNT_COLUMNS]), m.ROLE_ACCOUNT)
        self.assertEqual(m.classify(["pax_first_name", "record_locator", "total_fare"]), m.ROLE_PAX)

    def test_required_columns(self):
        self.assertEqual(m.missing_required(m.ROLE_PAX, PAX_COLUMNS), [])
        self.assertEqual(m.missing_required(m.ROLE_ACCOUNT, ACCOUNT_COLUMNS), [])
        missing = m.missing_required(m.ROLE_PAX, ["RecordLocator", "PaxFirstName"])
        self.assertEqual(len(missing), 1)
        self.assertIn("TotalFare", missing[0])


class TestAgFilter(unittest.TestCase):
    """Rule 2: only `PaymentMethodCode = AG` is imported."""

    def test_statement_balance_lines_are_dropped(self):
        rows, st = run(SAMPLE_PAX, SAMPLE_ACCOUNT)
        self.assertEqual(st.account_rows, 4)      # 5 sampled, 1 balance line
        self.assertEqual(st.skipped_not_ag, 1)
        self.assertNotIn("", transactions(rows))  # the balance row carried no PNR

    def test_both_signs_survive_the_filter(self):
        """+ve sells and -ve refunds are BOTH transactions — the filter is the
        payment method alone, never the sign."""
        rows, _ = run([], SAMPLE_ACCOUNT)
        amounts = {r.data["PNR"]: r.data["ForeignAmount"] for r in rows}
        self.assertEqual(amounts["RE7F7R"], "5073")     # positive kept
        self.assertEqual(amounts["D49GSC"], "-5516")    # negative kept
        self.assertEqual(amounts["IBWGPK"], "-8356")
        self.assertEqual(len(amounts), 4)

    def test_a_lowercase_or_padded_ag_still_counts(self):
        r = acct("1", "2026-08-15T01:00:00.000+0000", "PPAccountCredit", "ZZZ111", "", "100", "Funds Added: ZZZ111")
        r["PaymentMethodCode"] = " ag "
        _, st = run([], [r])
        self.assertEqual((st.account_rows, st.skipped_not_ag), (1, 0))

    def test_a_different_payment_method_is_dropped(self):
        r = acct("1", "2026-08-15T01:00:00.000+0000", "PPAccountCredit", "ZZZ111", "", "100", "Funds Added: ZZZ111")
        r["PaymentMethodCode"] = "CC"
        _, st = run([], [r])
        self.assertEqual((st.account_rows, st.skipped_not_ag), (0, 1))


class TestAmountAndSign(unittest.TestCase):
    """Rule 3: ForeignAmount is the total, untouched. +ve sells, -ve refunds."""

    def _built(self, rows):
        mapping, _, _ = spec.suggest_mapping(ACCOUNT_COLUMNS)
        return {r.data["PNR"]: spec.build_typed_row(r.data, mapping) for r in rows}

    def test_the_amount_is_never_transformed(self):
        rows, _ = run([], SAMPLE_ACCOUNT)
        for r in rows:
            built = self._built([r])[r.data["PNR"]]
            self.assertEqual(str(int(built["total"])), r.data["ForeignAmount"])

    def test_positive_bills_as_a_sale_and_negative_as_a_refund(self):
        rows, _ = run([], SAMPLE_ACCOUNT)
        kinds = {k: _bill_kind(v["total"]) for k, v in self._built(rows).items()}
        self.assertEqual(kinds["RE7F7R"], "sale")      # +5073
        self.assertEqual(kinds["J7IL8G"], "sale")      # +8356
        self.assertEqual(kinds["D49GSC"], "refund")    # -5516
        self.assertEqual(kinds["IBWGPK"], "refund")    # -8356

    def test_foreign_amount_maps_to_total_not_payment_amount(self):
        """Aliased to both, the same money would show twice in the totals strip."""
        mapping, _, _ = spec.suggest_mapping(ACCOUNT_COLUMNS)
        self.assertEqual(mapping.get("total"), "ForeignAmount")
        self.assertNotEqual(mapping.get("payment_amount"), "ForeignAmount")

    def test_acamount_is_never_money(self):
        mapping, _, _ = spec.suggest_mapping(ACCOUNT_COLUMNS)
        self.assertNotIn("ACAmount", mapping.values())


class TestPnrIndex(unittest.TestCase):
    """The passenger file as a lookup, aggregated PER BOOKING."""

    def setUp(self):
        self.idx = m.build_pnr_index(SAMPLE_PAX, PAX_COLUMNS, airline_code="IX")

    def test_base_fare_sums_over_every_line_of_the_booking(self):
        self.assertEqual(self.idx["S86NWJ"].base_fare, 7008)          # 1 pax, 2 legs
        self.assertEqual(self.idx["H27R7V"].base_fare, 4923 * 3)      # 3 pax, 1 leg each
        self.assertEqual(self.idx["K65EWM"].base_fare, -6276 + -1935)  # a cancellation

    def test_every_passenger_on_the_booking_is_named(self):
        self.assertEqual(self.idx["V2L7YL"].names, ["ASHISH RAI", "ATUL Singh"])
        self.assertEqual(len(self.idx["H27R7V"].names), 3)

    def test_the_same_traveller_in_two_spellings_is_named_once(self):
        self.assertEqual(self.idx["S86NWJ"].names, ["MADHU MAYOORI"])
        self.assertEqual(self.idx["K65EWM"].names, ["Madhu MAYOORI"])

    def test_two_one_way_pnrs_stay_separate_bookings(self):
        self.assertEqual(self.idx["M7TW6G"].base_fare, 5461)
        self.assertEqual(self.idx["D1EZFY"].base_fare, 4710)

    def test_distinct_sectors_are_folded_in_departure_order(self):
        segs = self.idx["S86NWJ"].segments
        self.assertEqual([s["route"] for s in segs], ["BLR-DED", "IXE-BLR"])
        self.assertEqual(segs[0]["flight_no"], "IX1506")

    def test_a_sector_shared_by_three_passengers_is_listed_once(self):
        self.assertEqual(len(self.idx["H27R7V"].segments), 1)

    def test_blank_carrier_falls_back_to_the_declared_airline(self):
        """plb_accrual reads the carrier off the first two characters of flight_no and
        drops the row if it doesn't resolve — a bare "1506" would vanish silently."""
        row = pax("01 Sep 26", "10:00:00", "CCC333", "A", "B", "DEL", "BOM", "2026-09-05", "1506", "1", "0", "0", "1")
        row["DepartureCarrierCode"] = ""
        idx = m.build_pnr_index([row], PAX_COLUMNS, airline_code="IX")
        self.assertEqual(idx["CCC333"].segments[0]["flight_no"], "IX1506")

    def test_more_than_five_sectors_overflow_rather_than_vanish(self):
        legs = [pax("01 Sep 26", "10:00:00", "EEE555", "A", "B", "AAA", "BBB",
                    "2026-09-%02d" % i, str(100 + i), "100", "0", "0", "100")
                for i in range(1, 8)]
        st = m.MergeStats()
        idx = m.build_pnr_index(legs, PAX_COLUMNS, airline_code="IX", stats=st)
        self.assertEqual(idx["EEE555"].base_fare, 700)      # all seven fares
        self.assertEqual(len(idx["EEE555"].segments), 5)
        self.assertEqual(len(idx["EEE555"].overflow), 2)
        self.assertEqual(st.legs_truncated, 1)


class TestJoinAndDerivedTax(unittest.TestCase):
    """Rule 4: tax = total - base fare, and blank when there is no base fare."""

    def setUp(self):
        # D49GSC is in the account file at -5516; give it a two-passenger booking.
        self.pax = [
            pax("16 Aug 26", "13:32:44", "D49GSC", "ANA", "SHARMA", "DEL", "BOM", "2026-08-20", "111", "-2000", "0", "0", "0"),
            pax("16 Aug 26", "13:32:44", "D49GSC", "BEN", "SHARMA", "DEL", "BOM", "2026-08-20", "111", "-2000", "0", "0", "0"),
        ]

    def test_the_booking_joins_onto_the_transaction(self):
        rows, st = run(self.pax, SAMPLE_ACCOUNT)
        r = transactions(rows)["D49GSC"]
        self.assertEqual(r.data["Name1"], "ANA SHARMA · BEN SHARMA")
        self.assertEqual(r.data["PaxCount"], "2")
        self.assertEqual(r.data["BookingDate"], "16 Aug 26")
        self.assertEqual(r.data["First Leg"], "DEL-BOM")
        self.assertEqual(st.enriched_account_rows, 1)

    def test_base_fare_is_the_bookings_not_one_passengers(self):
        rows, _ = run(self.pax, SAMPLE_ACCOUNT)
        self.assertEqual(transactions(rows)["D49GSC"].data["BaseFare"], "-4000")

    def test_tax_is_total_minus_base_fare(self):
        rows, st = run(self.pax, SAMPLE_ACCOUNT)
        r = transactions(rows)["D49GSC"]
        self.assertEqual(r.data["ForeignAmount"], "-5516")
        self.assertEqual(r.data["BaseFare"], "-4000")
        self.assertEqual(r.data["Tax Total"], "-1516")      # -5516 - -4000
        self.assertEqual(st.tax_derived, 1)

    def test_an_unmatched_transaction_has_neither_base_fare_nor_tax(self):
        """Blank, not zero: `total - 0` would assert the whole amount was tax."""
        rows, st = run(self.pax, SAMPLE_ACCOUNT)
        r = transactions(rows)["RE7F7R"]
        self.assertIsNone(r.data.get("BaseFare"))
        self.assertIsNone(r.data.get("Tax Total"))
        self.assertEqual(r.data["ForeignAmount"], "5073")   # the amount still lands
        self.assertEqual(st.unmatched_account_rows, 3)

    def test_the_transaction_keeps_its_own_columns(self):
        rows, _ = run(self.pax, SAMPLE_ACCOUNT)
        r = transactions(rows)["D49GSC"]
        self.assertEqual(r.data["PNR"], "D49GSC")
        self.assertEqual(r.data["AccountTransactionType"], "PPAccountDebitForPayment")
        self.assertEqual(r.data["GSTNumber"], "07AAACZ6844Q1ZI")
        self.assertEqual(r.data["Note"], "Funds Used: D49GSC")

    def test_every_transaction_on_a_pnr_carries_the_bookings_fare(self):
        booking = [pax("18 Aug 26", "15:10:00", "IBWGPK", "CAT", "RAO", "DEL", "BOM", "2026-08-25", "222", "6800", "0", "0", "0")]
        rows, _ = run(booking, SAMPLE_ACCOUNT)
        r = transactions(rows)["IBWGPK"]
        self.assertEqual(r.data["BaseFare"], "6800")
        self.assertEqual(r.data["Tax Total"], "-15156")     # -8356 - 6800


class TestAccountMovements(unittest.TestCase):
    def test_note_prefixes_classify(self):
        for note, expected in (
            ("Prepaid Account - Statement Date: 8/14/2026", m.MOVEMENT_BALANCE),
            ("Funds Used: D49GSC", m.MOVEMENT_BOOKING_PAYMENT),
            ("Funds Added: J7IL8G", m.MOVEMENT_CANCELLATION_CREDIT),
            ("Refund by utility: PMTID:496210023, RL:RE7F7R", m.MOVEMENT_REFUND),
        ):
            kind, unknown = m.classify_note(note)
            self.assertEqual(kind, expected, note)
            self.assertIsNone(unknown)

    def test_transaction_type_alone_cannot_separate_transfer_from_refund(self):
        transfer, refund = SAMPLE_ACCOUNT[2], SAMPLE_ACCOUNT[1]
        self.assertEqual(transfer["AccountTransactionType"], refund["AccountTransactionType"])
        rows, _ = run([], [transfer, refund])
        self.assertEqual([r.movement_kind for r in rows],
                         [m.MOVEMENT_CANCELLATION_CREDIT, m.MOVEMENT_REFUND])

    def test_unknown_note_is_counted_not_guessed(self):
        row = acct("1", "2026-08-15T01:00:00.000+0000", "PPAccountCredit", "ZZZ999", "", "100",
                   "Chargeback reversal: 12345")
        rows, st = run([], [row])
        self.assertEqual(rows[0].movement_kind, m.MOVEMENT_UNKNOWN)
        self.assertEqual(st.unknown_notes, {"chargeback reversal": 1})


class TestPassengerFileAlone(unittest.TestCase):
    """No account statement to hang rows off — it imports as an ordinary statement."""

    def test_one_row_per_pnr_and_passenger(self):
        rows, st = run(SAMPLE_PAX, [])
        self.assertEqual(st.account_rows, 0)
        got = by_pnr(rows)
        self.assertEqual(len(got["S86NWJ"]), 1)      # 1 passenger, 2 legs folded
        self.assertEqual(len(got["V2L7YL"]), 2)      # 2 passengers
        self.assertEqual(len(got["H27R7V"]), 3)
        self.assertEqual(got["S86NWJ"][0].data["TotalFare"], "9763")

    def test_its_own_fare_columns_are_used(self):
        rows, _ = run(SAMPLE_PAX, [])
        mapping, _, _ = spec.suggest_mapping(
            m.pax_columns_after_reshape(PAX_COLUMNS, with_account=False))
        built = spec.build_typed_row(by_pnr(rows)["S86NWJ"][0].data, mapping)
        self.assertEqual(int(built["total"]), 9763)
        self.assertEqual(int(built["taxes_total"]), 2510)


class TestColumnsOfferedToTheMappingUI(unittest.TestCase):
    def test_every_joined_column_is_a_standard_header(self):
        """The whole design rests on this: named after template headers, the joined
        columns auto-map with no alias work at all."""
        standard = set(spec.LCC_STANDARD_HEADERS)
        added = (set(m.account_columns_after_merge(ACCOUNT_COLUMNS, with_pax=True))
                 - set(ACCOUNT_COLUMNS))
        self.assertTrue(added)
        for name in added:
            self.assertIn(name, standard, "%r is not a standard template header" % name)
        for name in m.synthetic_columns(with_account=True):
            self.assertIn(name, standard, "%r is not a standard template header" % name)

    def test_the_joined_columns_auto_map(self):
        cols = m.account_columns_after_merge(ACCOUNT_COLUMNS, with_pax=True)
        mapping, _, _ = spec.suggest_mapping(cols)
        for fld, col in (("name1", "Name1"), ("pax_count", "PaxCount"),
                         ("pax_type", "PaxType"), ("booking_date", "BookingDate"),
                         ("base_fare", "BaseFare"), ("taxes_total", "Tax Total"),
                         ("total", "ForeignAmount"), ("record_locator", "PNR"),
                         ("parent_pnr", "ParentPNR"), ("transaction_date", "TransactionDate"),
                         ("leg1_route", "First Leg"), ("leg1_flight_no", "First Leg Flight No")):
            self.assertEqual(mapping.get(fld), col, "%s did not auto-map" % fld)

    def test_an_account_file_alone_offers_only_its_own_columns(self):
        self.assertEqual(m.account_columns_after_merge(ACCOUNT_COLUMNS, with_pax=False),
                         ACCOUNT_COLUMNS)


class TestDeterminism(unittest.TestCase):
    @staticmethod
    def _fingerprint(rows):
        return [(r.row_kind, r.movement_kind, tuple(sorted(r.data.items(), key=repr)))
                for r in rows]

    def test_reordering_the_passenger_file_changes_no_money(self):
        """Names and sectors are listed in first-seen order, so the ORDER of those
        may follow the file. Every figure must not."""
        import random
        a, sa = run(SAMPLE_PAX, SAMPLE_ACCOUNT)
        shuffled = list(SAMPLE_PAX)
        random.Random(7).shuffle(shuffled)
        b, sb = run(shuffled, SAMPLE_ACCOUNT)

        def money(rows):
            return sorted(
                (r.data.get("PNR"), r.data.get("ForeignAmount"), r.data.get("BaseFare"),
                 r.data.get("Tax Total"),
                 frozenset((r.data.get("Name1") or "").split(" · ")))
                for r in rows)

        self.assertEqual(money(a), money(b))
        self.assertEqual(sa.as_dict()["account_rows"], sb.as_dict()["account_rows"])
        self.assertEqual(sa.as_dict()["tax_derived"], sb.as_dict()["tax_derived"])

    def test_same_input_twice_is_identical(self):
        a, sa = run(SAMPLE_PAX, SAMPLE_ACCOUNT)
        b, sb = run(SAMPLE_PAX, SAMPLE_ACCOUNT)
        self.assertEqual(self._fingerprint(a), self._fingerprint(b))
        self.assertEqual(sa.as_dict(), sb.as_dict())

    def test_stats_are_json_serialisable(self):
        import json
        _, st = run(SAMPLE_PAX, SAMPLE_ACCOUNT)
        json.dumps(st.as_dict())
        self.assertEqual(st.as_dict()["merge_version"], m.MERGE_VERSION)


class TestEndToEndThroughTheSpec(unittest.TestCase):
    """The merge only earns its keep if build_typed_row can consume its output."""

    def test_a_merged_transaction_types_correctly(self):
        booking = [
            pax("16 Aug 26", "13:32:44", "D49GSC", "ANA", "SHARMA", "DEL", "BOM", "2026-08-20", "111", "-2000", "0", "0", "0"),
            pax("16 Aug 26", "13:32:44", "D49GSC", "BEN", "SHARMA", "DEL", "IXE", "2026-08-21", "222", "-2000", "0", "0", "0"),
        ]
        rows, _ = run(booking, SAMPLE_ACCOUNT)
        cols = m.account_columns_after_merge(ACCOUNT_COLUMNS, with_pax=True)
        mapping, _, _ = spec.suggest_mapping(cols)
        built = spec.build_typed_row(transactions(rows)["D49GSC"].data, mapping)

        self.assertEqual(built["record_locator"], "D49GSC")
        self.assertEqual(built["name1"], "ANA SHARMA · BEN SHARMA")
        self.assertEqual(built["pax_count"], 2)
        self.assertEqual(int(built["total"]), -5516)
        self.assertEqual(int(built["base_fare"]), -4000)
        self.assertEqual(int(built["taxes_total"]), -1516)
        self.assertEqual(built["transaction_type"], "PPAccountDebitForPayment")
        self.assertEqual(built["gst_number"], "07AAACZ6844Q1ZI")
        self.assertIsNone(built["transaction_date"].tzinfo)
        self.assertEqual(len(built["segments"]), 2)
        self.assertEqual(built["segments"][0]["flight_no"], "IX111")
        self.assertEqual(str(built["departure_date"]), "2026-08-20")
        self.assertEqual(_bill_kind(built["total"]), "refund")


if __name__ == "__main__":
    unittest.main()
