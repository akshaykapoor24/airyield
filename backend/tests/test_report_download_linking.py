"""Report download — cross-source linking and de-duplication.

Pinned (design §C / §H): BSP rows of included statements outside the period are still linkable
("outside period" / "other period", never "not in BSP"); legacy codeless BSP rows and forms the
TGQ enrichment index misses still suppress TGQ; RFND refund notices link via RTDN; a refund is
not settled by a sale; duplicate uploads are not ambiguous; codeless serials shared by two
airlines are; owner-lookup hits are re-keyed; every final link text is exact.

No DB, no network.  Run: python -m unittest test_report_download_linking   (from backend/tests)
"""
import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import bsp_tgq_enrichment  # noqa: E402
from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download import linking as L  # noqa: E402
from app.services.report_download.normalize import canon_bsp_txn, doc_key, pack  # noqa: E402
from app.services.report_download.types import DocKey, LinkResult  # noqa: E402

K = DocKey
SALE_T = frozenset({C.SALE, C.EXCHANGE})
EMPTY = L.KeySet()


def bsp(row_id, document, *, code="098", ttype="TKTT", ticket="same", rtdn=None, alt=None, assoc=None,
        amount="1000.00", issue=date(2026, 7, 5)):
    return SimpleNamespace(
        id=row_id, airline_accounting_code=code, document_number=document,
        ticket_number=document if ticket == "same" else ticket, rtdn=rtdn,
        alt_document_numbers=alt, associated_docs=assoc, transaction_type=ttype,
        transaction_amount=Decimal(amount), issue_date=issue,
    )


def index_row(sel, row, *, upload_idx=0, file_name="BSP_JUL.pdf", in_period=True):
    """What the builder's phase-A pre-pass does for one non-superseded BSP row."""
    docs, rtdns = L.bsp_row_keys(row)
    canon, _ = canon_bsp_txn(row.transaction_type, row.associated_docs)
    sel.add(row_id=row.id, upload_idx=upload_idx, file_name=file_name, canon=canon, in_period=in_period,
            doc_keys=docs, rtdn_keys=rtdns, document=row.document_number)


def memo(document, *, code="098", related=None, status="Approved"):
    return SimpleNamespace(document_number=document, airline_code=code, related_document=related, status=status)


def tgq(sel, serial, canon=C.SALE, code="098", ndc=EMPTY, gds=EMPTY):
    return L.decide_tgq(code, serial, canon, sel, ndc_keys=ndc, gds_keys=gds)


# ── SelectionIndex ────────────────────────────────────────────────────────────

class SelectionIndexTests(unittest.TestCase):
    def test_exact_typed_lookup_and_ref_view(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(11, "5805708071"))
        self.assertEqual(len(sel), 1)
        m = sel.find(K("098", "5805708071"), SALE_T)
        self.assertTrue(m.hit)
        self.assertFalse(m.ambiguous)
        self.assertEqual(m.best, L.RefView(11, 0, "BSP_JUL.pdf", C.SALE, True, "5805708071"))
        self.assertFalse(sel.find(K("098", "5805708071"), frozenset({C.REFUND})).hit)
        self.assertTrue(sel.find(K("098", "5805708071"), None).hit)
        self.assertFalse(sel.find(K("098", "5805708071"), SALE_T, "rtdn").hit)
        self.assertFalse(sel.find(K("176", "5805708071"), SALE_T).hit)
        self.assertFalse(sel.find(None, SALE_T).hit)

    def test_document_keeps_leading_zeros_and_text(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "0012345678", ttype="RFND", ticket=None, rtdn="5805708071"))
        index_row(sel, bsp(2, "ADM-77X", ttype="ADMA", ticket=None))
        sel.add(row_id=3, upload_idx=0, file_name=None, canon=C.SALE, in_period=True,
                doc_keys=[K("098", "5805708099")], rtdn_keys=[])
        self.assertEqual(sel.find(K("098", "0012345678"), None).best.document, "0012345678")
        self.assertEqual(sel.find(K("098", "ADM77X"), None).best.document, "ADM-77X")
        # no document passed → the first doc key's 13-digit form
        self.assertEqual(sel.find(K("098", "5805708099"), None).best.document, "0985805708099")

    def test_file_name_stored_once_per_upload(self):
        sel = L.SelectionIndex()
        sel.add(row_id=1, upload_idx=2, file_name="old.pdf", canon=C.SALE, in_period=True,
                doc_keys=[K("098", "1111111111")], rtdn_keys=[])
        sel.add(row_id=2, upload_idx=2, file_name=None, canon=C.SALE, in_period=True,
                doc_keys=[K("098", "2222222222")], rtdn_keys=[])
        self.assertEqual(sel.find(K("098", "2222222222"), None).best.file_name, "old.pdf")
        self.assertEqual(sel._files, [None, None, "old.pdf"])

    def test_unknown_canon_stored_as_unknown(self):
        sel = L.SelectionIndex()
        sel.add(row_id=1, upload_idx=0, file_name="a", canon="FLOWN", in_period=True,
                doc_keys=[K("098", "1111111111")], rtdn_keys=[])
        self.assertEqual(sel.find(K("098", "1111111111"), None).best.canon, C.UNKNOWN)

    def test_bad_arguments(self):
        sel = L.SelectionIndex()
        with self.assertRaises(ValueError):
            sel.add(row_id=1, upload_idx=70000, file_name=None, canon=C.SALE, in_period=True, doc_keys=[], rtdn_keys=[])
        with self.assertRaises(ValueError):
            sel.find(K("098", "1"), None, "ticket")
        with self.assertRaises(TypeError):
            sel.add(1, 0, None, C.SALE, True, [], [])          # keyword-only

    def test_columnar_storage(self):
        sel = L.SelectionIndex()
        for i in range(5):
            index_row(sel, bsp(100 + i, f"580570807{i}"))
        self.assertEqual(sel._row_ids.typecode, "q")
        self.assertEqual(sel._uploads.typecode, "H")
        self.assertIsInstance(sel._canon, bytearray)
        self.assertIsInstance(sel._in_period, bytearray)
        self.assertEqual(len(sel), 5)

    def test_many_rows_on_one_key_use_overflow_and_are_one_upload(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        index_row(sel, bsp(2, "5805708071", ttype="RFND"))
        index_row(sel, bsp(3, "5805708071", ttype="CANX"))
        m = sel.find(K("098", "5805708071"), None)
        self.assertEqual({r.row_id for r in m.refs}, {1, 2, 3})
        self.assertFalse(m.ambiguous)                      # all in the same upload
        self.assertEqual([r.row_id for r in sel.find(K("098", "5805708071"), frozenset({C.REFUND})).refs], [2])

    def test_same_key_in_two_uploads_is_ambiguous_newest_best(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071", amount="900.00"), upload_idx=0, file_name="new.pdf")
        index_row(sel, bsp(2, "5805708071"), upload_idx=1, file_name="old.pdf")
        m = sel.find(K("098", "5805708071"), SALE_T)
        self.assertTrue(m.ambiguous)
        self.assertEqual(m.best.file_name, "new.pdf")
        self.assertEqual(m.best.upload_idx, 0)

    def test_best_prefers_newest_upload_then_in_period(self):
        a = L.RefView(1, 1, "old", C.SALE, True, None)
        b = L.RefView(2, 0, "new", C.SALE, False, None)
        c = L.RefView(3, 0, "new", C.SALE, True, None)
        self.assertEqual(L.Match((a, b, c)).best, c)
        self.assertEqual(L.Match((a, b)).best, b)
        self.assertIsNone(L.Match().best)
        self.assertFalse(L.Match((), True).hit)

    def test_via_rtdn_and_any(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "0012345678", ttype="RFND", ticket=None, rtdn="5805708071"))
        self.assertFalse(sel.find(K("098", "5805708071"), frozenset({C.REFUND}), "document").hit)
        self.assertTrue(sel.find(K("098", "5805708071"), frozenset({C.REFUND}), "rtdn").hit)
        self.assertTrue(sel.find(K("098", "5805708071"), frozenset({C.REFUND}), "any").hit)
        self.assertTrue(sel.find_any(K("098", "5805708071")).hit)

    def test_codeless_probe_single_code(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        m = sel.find(K(None, "5805708071"), SALE_T)
        self.assertTrue(m.hit)
        self.assertFalse(m.ambiguous)

    def test_codeless_serial_held_by_two_codes_is_ambiguous(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071", code="098"))
        index_row(sel, bsp(2, "5805708071", code="176"))
        m = sel.find(K(None, "5805708071"), SALE_T)
        self.assertEqual(m, L.Match((), True))
        self.assertFalse(m.hit)
        self.assertTrue(sel.find_any(K(None, "5805708071")).ambiguous)
        # a coded probe is still exact
        m = sel.find(K("176", "5805708071"), SALE_T)
        self.assertEqual([r.row_id for r in m.refs], [2])
        self.assertFalse(m.ambiguous)

    def test_coded_probe_finds_legacy_codeless_row(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071", code=None, ttype="tktt"))
        m = sel.find(K("098", "5805708071"), SALE_T)
        self.assertTrue(m.hit)
        self.assertFalse(m.ambiguous)
        # ... but that is ambiguous once another airline also holds the serial
        index_row(sel, bsp(2, "5805708071", code="176"))
        m = sel.find(K("098", "5805708071"), SALE_T)
        self.assertTrue(m.hit)
        self.assertTrue(m.ambiguous)

    def test_alpha_designator_code_is_treated_as_codeless(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        self.assertTrue(sel.find(K("AI", "5805708071"), SALE_T).hit)


# ── small indexes ─────────────────────────────────────────────────────────────

class KeySetTests(unittest.TestCase):
    def test_doc_keys_are_packed(self):
        ks = L.KeySet()
        ks.add(K("098", "5805708071"))
        ks.add(K("098", "5805708071"))
        ks.add(None)
        self.assertEqual(len(ks), 1)
        self.assertIn(pack(K("098", "5805708071")), ks._keys)
        self.assertIn(K("098", "5805708071"), ks)
        self.assertIn(doc_key(None, "098-5805708071-3"), ks)
        self.assertNotIn(K("176", "5805708071"), ks)
        self.assertNotIn(None, ks)

    def test_codeless_rules(self):
        ks = L.KeySet([K("098", "5805708071"), K(None, "1111111111")])
        self.assertIn(K(None, "5805708071"), ks)          # one code holds it
        self.assertIn(K("098", "1111111111"), ks)         # codeless member
        ks.add(K("176", "5805708071"))
        self.assertNotIn(K(None, "5805708071"), ks)       # two codes: not provable

    def test_tuples_and_strings_as_is(self):
        ks = L.KeySet()
        ks.add((7, "0985805708071"))
        ks.add("PNR:ABC123")
        self.assertIn((7, "0985805708071"), ks)
        self.assertNotIn((8, "0985805708071"), ks)
        self.assertIn("PNR:ABC123", ks)
        self.assertEqual(len(ks), 2)


class LccPnrIndexTests(unittest.TestCase):
    def test_lookups(self):
        idx = L.LccPnrIndex()
        idx.add("6E", "abc123", "lcc-detailed:1")
        idx.add("6E", "ABC123", "lcc-detailed:2")        # first row wins
        idx.add("SG", "XYZ999", "lcc-detailed:3")
        idx.add("IX", "XYZ999", "lcc-detailed:4")
        idx.add(None, "NOAIR1", "lcc-detailed:5")
        idx.add("6E", None, "lcc-detailed:6")            # ignored
        self.assertEqual(idx.get("6e", " abc123 "), "lcc-detailed:1")
        self.assertIsNone(idx.get("SG", "ABC123"))
        self.assertEqual(idx.get(None, "ABC123"), "lcc-detailed:1")      # single airline
        self.assertIsNone(idx.get(None, "XYZ999"))                       # two airlines
        self.assertEqual(idx.get("IX", "XYZ999"), "lcc-detailed:4")
        self.assertEqual(idx.get("6E", "NOAIR1"), "lcc-detailed:5")      # detailed row without airline
        self.assertIsNone(idx.get("6E", None))
        self.assertIsNone(idx.get(None, "MISSING"))

    def test_lcc_ledger_link(self):
        idx = L.LccPnrIndex()
        idx.add("SG", "CHILD1", "lcc-detailed:9")
        link = L.lcc_ledger_link("SG", ["PARENT", "child1"], idx)
        self.assertEqual(link, LinkResult(linked_document="CHILD1", linked_via="LCC Detailed PNR",
                                          flags=["ALSO_IN_LCC_DETAILED"]))
        idx.add("SG", "PARENT", "lcc-detailed:8")
        self.assertEqual(L.lcc_ledger_link("SG", ["PARENT", "CHILD1"], idx).linked_document, "PARENT")
        self.assertIsNone(L.lcc_ledger_link("6E", ["PARENT"], idx))
        self.assertIsNone(L.lcc_ledger_link("SG", [None, ""], idx))


class DuplicateTrackerTests(unittest.TestCase):
    def test_first_upload_wins(self):
        t = L.DuplicateTracker()
        key = (pack(K("098", "5805708071")), C.SALE, Decimal("1000.00"), date(2026, 7, 5))
        self.assertIsNone(t.check("bsp", key, 0))
        self.assertIsNone(t.check("bsp", key, 0))          # repeat inside one upload
        self.assertEqual(t.check("bsp", key, 1), 0)
        self.assertIsNone(t.check("adm", key, 1))          # other source, other key
        self.assertEqual(len(t), 2)
        self.assertTrue(all(isinstance(k, int) and k < 2**64 for k in t._seen))

    def test_tgq_dedupe_on_key_and_type_keeps_sale_and_refund(self):
        t = L.DuplicateTracker()
        pk = pack(K("098", "5805708071"))
        self.assertIsNone(t.check("tgq-hmpr", (pk, C.SALE), 0))
        self.assertIsNone(t.check("tgq-hmpr", (pk, C.REFUND), 0))
        self.assertEqual(t.check("tgq-hmpr", (pk, C.SALE), 1), 0)

    def test_duplicate_bsp_upload_is_not_ambiguous(self):
        uploads = [("BSP_JUL_v2.pdf", [bsp(10, "5805708071")]), ("BSP_JUL.pdf", [bsp(1, "5805708071")])]

        def prepass(dedupe):
            tracker, sel, superseded = L.DuplicateTracker(), L.SelectionIndex(), set()
            for idx, (name, rows) in enumerate(uploads):          # newest first
                for r in rows:
                    canon, _ = canon_bsp_txn(r.transaction_type, r.associated_docs)
                    nk = (pack(doc_key(r.airline_accounting_code, r.document_number)), canon,
                          r.transaction_amount, r.issue_date)
                    if dedupe and tracker.check("bsp", nk, idx) is not None:
                        superseded.add(r.id)
                        continue
                    index_row(sel, r, upload_idx=idx, file_name=name)
            return sel, superseded

        sel, superseded = prepass(dedupe=True)
        self.assertEqual(superseded, {1})
        m = sel.find(K("098", "5805708071"), SALE_T)
        self.assertFalse(m.ambiguous)
        self.assertEqual(m.best.file_name, "BSP_JUL_v2.pdf")
        self.assertEqual(tgq(sel, "5805708071").action, "suppress")
        # without the tracker the same two files would flag every ticket
        sel, _ = prepass(dedupe=False)
        self.assertTrue(sel.find(K("098", "5805708071"), SALE_T).ambiguous)


# ── BSP rows ──────────────────────────────────────────────────────────────────

class BspRowKeysTests(unittest.TestCase):
    def test_all_document_and_rtdn_sources(self):
        row = bsp(1, "5805708071", ticket="0985805708071", rtdn="1234567890",
                  alt=["5805708072", {"doc": "5805708073"}],
                  assoc={"rtdn": {"doc": "1234567890"}, "exchanges": [{"doc": "2234567890"}],
                         "conjunctions": [{"doc": "5805708073"}, {"doc": "5805708074"}]})
        docs, rtdns = L.bsp_row_keys(row)
        self.assertEqual(docs, [K("098", s) for s in ("5805708071", "5805708072", "5805708073", "5805708074")])
        self.assertEqual(rtdns, [K("098", "1234567890"), K("098", "2234567890")])

    def test_json_text_code_padding_and_blanks(self):
        row = bsp(1, "5805708071", code="98", ticket=None,
                  alt='["5805708072"]', assoc='{"exchanges": [{"doc": null}], "rtdn": null}')
        docs, rtdns = L.bsp_row_keys(row)
        self.assertEqual(docs, [K("098", "5805708071"), K("098", "5805708072")])
        self.assertEqual(rtdns, [])
        self.assertEqual(L.bsp_row_keys(SimpleNamespace()), ([], []))
        self.assertEqual(L.bsp_row_keys({"document_number": "0985805708071"}), ([K("098", "5805708071")], []))

    def test_conjunction_document_expanded(self):
        docs, _ = L.bsp_row_keys(bsp(1, "5800920932-933"))
        self.assertEqual(docs, [K("098", "5800920932"), K("098", "5800920933")])

    def test_link_bsp_flags(self):
        ndc = L.KeySet([K("098", "5805708071")])
        memos = L.KeySet([K("098", "7000000001"), K("098", "0012345678")])
        self.assertEqual(L.link_bsp_flags(bsp(1, "5805708071"), ndc_keys=ndc, memo_keys=memos), ["ALSO_IN_NDC"])
        self.assertEqual(L.link_bsp_flags(bsp(2, "7000000001", ttype="ADMA", ticket=None), ndc_keys=ndc, memo_keys=memos),
                         ["MEMO_UPLOADED"])
        self.assertEqual(L.link_bsp_flags(bsp(3, "7000000001", ttype="TKTT"), ndc_keys=ndc, memo_keys=memos), [])
        refund = bsp(4, "0099999999", ttype="RFND", ticket=None, rtdn="0012345678")
        self.assertEqual(L.link_bsp_flags(refund, ndc_keys=ndc, memo_keys=memos), ["MEMO_UPLOADED"])
        acm_rtdn = bsp(5, "0099999998", ttype="ACMA", ticket=None, rtdn="0012345678")
        self.assertEqual(L.link_bsp_flags(acm_rtdn, ndc_keys=ndc, memo_keys=memos), [])


# ── ADM / ACM / RA ────────────────────────────────────────────────────────────

class MemoTests(unittest.TestCase):
    def setUp(self):
        self.sel = L.SelectionIndex()
        index_row(self.sel, bsp(1, "7000000001", ttype="ADMA", ticket=None), in_period=True)
        index_row(self.sel, bsp(2, "7000000002", ttype="ADMA", ticket=None), in_period=False)
        index_row(self.sel, bsp(3, "5805708071"))
        index_row(self.sel, bsp(4, "0012345678", ttype="RFND", ticket=None, rtdn="5805708099"))

    def test_in_period_memo_counts_in_billing_and_links_the_memo_row(self):
        link, pending = L.link_memo("adm", memo("7000000001"), self.sel)
        self.assertEqual(link.also_in_bsp, "Yes – this report")
        self.assertEqual(link.counts_in_net, C.NET_MEMO_IN_BILLING)
        self.assertEqual((link.linked_document, link.linked_via), ("7000000001", "BSP memo row"))
        self.assertEqual(pending, [])

    def test_out_of_period_row_of_included_statement(self):
        link, pending = L.link_memo("ADM", memo("098-7000000002"), self.sel)
        self.assertEqual(link.also_in_bsp, "Yes – other period (BSP_JUL.pdf)")
        self.assertEqual(link.counts_in_net, C.NET_MEMO_OTHER_PERIOD)
        self.assertEqual(pending, [])

    def test_related_ticket_link(self):
        link, _ = L.link_memo("adm", memo("7000000001", related="0985805708071"), self.sel)
        self.assertEqual((link.linked_document, link.linked_via), ("5805708071", "Related ticket (BSP_JUL.pdf)"))
        # a memo about a refunded ticket links the refund notice through its RTDN
        link, _ = L.link_memo("adm", memo("7000000001", related="5805708099"), self.sel)
        self.assertEqual((link.linked_document, link.linked_via), ("0012345678", "Related ticket (BSP_JUL.pdf)"))

    def test_type_filter_acm_does_not_match_adm_row(self):
        link, pending = L.link_memo("acm", memo("7000000001", related="5805708071"), self.sel)
        self.assertEqual(link.also_in_bsp, "No")
        self.assertIsNone(link.counts_in_net)
        self.assertEqual(link.linked_via, "Related ticket (BSP_JUL.pdf)")
        self.assertEqual(pending, [(K("098", "7000000001"), frozenset({C.ACM}), "document")])

    def test_unresolved_memo_then_finalize(self):
        link, pending = L.link_memo("adm", memo("7000000009"), self.sel)
        self.assertEqual((link.also_in_bsp, link.counts_in_net, link.linked_via), ("No", None, None))
        self.assertEqual(pending, [(K("098", "7000000009"), frozenset({C.ADM}), "document")])
        hit = L.OwnerHit(99, "098", "7000000009", None, None, "ADMA", "BSP_JUN.pdf")
        [found] = L.resolve_outside(pending, [hit])
        final = L.finalize_pending("memo", link, found)
        self.assertEqual(final.also_in_bsp, "Yes – other upload (BSP_JUN.pdf)")
        self.assertEqual(final.counts_in_net, "No – in another BSP upload")

    def test_memo_without_document(self):
        link, pending = L.link_memo("adm", memo(None), self.sel)
        self.assertEqual((link.also_in_bsp, pending), ("No", []))
        with self.assertRaises(ValueError):
            L.link_memo("ra", memo("7000000001"), self.sel)

    def test_ra_by_document_and_original_ticket(self):
        ra = SimpleNamespace(document_number="0012345678", rtdn_number="5805708099", airline_code="098")
        link, pending = L.link_ra(ra, self.sel)
        self.assertEqual((link.also_in_bsp, link.counts_in_net), ("Yes – this report", C.NET_MEMO_IN_BILLING))
        self.assertEqual((link.linked_document, link.linked_via), ("0012345678", "BSP memo row"))
        self.assertEqual(pending, [])

    def test_ra_by_rtdn_links_original_ticket(self):
        index_row(self.sel, bsp(5, "5805708099"))
        ra = SimpleNamespace(document_number="9999999999", rtdn_number="5805708099", airline_code="98")
        link, pending = L.link_ra(ra, self.sel)
        self.assertEqual(link.also_in_bsp, "Yes – this report")
        self.assertEqual((link.linked_document, link.linked_via), ("5805708099", "Original ticket (RTDN)"))
        self.assertEqual(pending, [])

    def test_ra_unresolved_probes_both_sides(self):
        ra = SimpleNamespace(document_number="9999999999", rtdn_number="8888888888", airline_code="098")
        link, pending = L.link_ra(ra, self.sel)
        self.assertEqual(link.also_in_bsp, "No")
        self.assertEqual(pending, [(K("098", "9999999999"), frozenset({C.REFUND}), "document"),
                                   (K("098", "8888888888"), frozenset({C.REFUND}), "rtdn")])
        self.assertEqual(L.finalize_pending("ra", link, None).also_in_bsp, "No")


# ── TGQ ───────────────────────────────────────────────────────────────────────

class TgqTests(unittest.TestCase):
    def test_type_targets_table(self):
        self.assertEqual(L.TYPE_TARGETS[C.SALE], (frozenset({C.SALE, C.EXCHANGE}), ("document",)))
        self.assertEqual(L.TYPE_TARGETS[C.EXCHANGE], (frozenset({C.SALE, C.EXCHANGE}), ("document",)))
        self.assertEqual(L.TYPE_TARGETS[C.EMD], (frozenset({C.EMD}), ("document",)))
        self.assertEqual(L.TYPE_TARGETS[C.REFUND], (frozenset({C.REFUND}), ("document", "rtdn")))
        self.assertEqual(L.TYPE_TARGETS[C.VOID], (frozenset({C.CANCELLATION, C.VOID}), ("document",)))
        types, vias = L.TYPE_TARGETS[C.UNKNOWN]
        self.assertTrue(set(L.CANON) <= types)
        self.assertEqual(vias, ("document",))

    def test_in_period_sale_suppressed(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        d = tgq(sel, "5805708071")
        self.assertEqual(d.action, "suppress")
        self.assertEqual(d.pending_probes, [])

    def test_bsp_row_outside_period(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"), in_period=False, file_name="BSP_JUL.pdf")
        d = tgq(sel, "5805708071")
        self.assertEqual(d.action, "emit")
        self.assertEqual(d.link.not_in_bsp, "BSP row outside period (BSP_JUL.pdf)")
        self.assertEqual(d.link.counts_in_net, C.NET_TGQ_OUTSIDE_PERIOD)
        self.assertEqual(d.pending_probes, [])

    def test_in_period_ref_in_older_upload_still_suppresses(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071", amount="1.00"), upload_idx=0, in_period=False, file_name="new.pdf")
        index_row(sel, bsp(2, "5805708071"), upload_idx=1, in_period=True, file_name="old.pdf")
        self.assertEqual(tgq(sel, "5805708071").action, "suppress")

    def test_legacy_codeless_bsp_row_matched_by_serial(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071", code=None, ttype="tktt"))
        self.assertEqual(tgq(sel, "5805708071", code="098").action, "suppress")
        self.assertEqual(tgq(sel, "5805708071", code=None).action, "suppress")
        self.assertEqual(tgq(sel, "5805708071", code="AI").action, "suppress")

    def test_forms_the_enrichment_index_misses_are_still_suppressed(self):
        # bsp_tgq_enrichment only reads 9-11 digit serials; membership reads every doc_key form.
        for serial in ("0985805708071", "098-5805708071", "985805708071"):
            with self.subTest(serial=serial):
                self.assertIsNone(bsp_tgq_enrichment._SERIAL_RE.match(serial))
                sel = L.SelectionIndex()
                index_row(sel, bsp(1, "5805708071"))
                self.assertEqual(tgq(sel, serial, code=None).action, "suppress")

    def test_conjunction_matches_second_document(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5800920933"))
        d = tgq(sel, "5800920932-933")
        self.assertEqual(d.action, "suppress")
        # and the BSP side's conjunction list is indexed too
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5800920932", alt=["5800920933"]))
        self.assertEqual(tgq(sel, "5800920933").action, "suppress")

    def test_rfnd_refund_notice_matched_via_rtdn(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "0012345678", ttype="RFND", ticket=None, rtdn="5805708071"))
        index_row(sel, bsp(2, "4012345679", ttype="RFDA", ticket=None, rtdn="5805708072"))
        self.assertEqual(tgq(sel, "5805708071", C.REFUND).action, "suppress")
        self.assertEqual(tgq(sel, "5805708072", C.REFUND).action, "suppress")

    def test_refund_not_suppressed_by_matching_sale(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        d = tgq(sel, "5805708071", C.REFUND)
        self.assertEqual(d.action, "emit")
        self.assertEqual(d.link.not_in_bsp, "Yes")
        self.assertEqual(d.link.counts_in_net, C.NET_TGQ_NOT_IN_BSP)
        self.assertIn("BSP_HAS_OTHER_TXN", d.link.flags)
        self.assertEqual(d.pending_probes, [])

    def test_void_matches_canx_by_ticket_number(self):
        sel = L.SelectionIndex()
        # distributed CANX: document rewritten to the SPDR, printed ticket kept in ticket_number
        index_row(sel, bsp(1, "9100000001", ttype="CANX", ticket="5805708071"))
        self.assertEqual(tgq(sel, "5805708071", C.VOID).action, "suppress")

    def test_not_found_emits_with_pending_probes(self):
        sel = L.SelectionIndex()
        d = tgq(sel, "5805708071", C.REFUND)
        self.assertEqual(d.action, "emit")
        self.assertEqual((d.link.not_in_bsp, d.link.counts_in_net), ("Yes", C.NET_TGQ_NOT_IN_BSP))
        refund = frozenset({C.REFUND})
        self.assertEqual(d.pending_probes, [(K("098", "5805708071"), refund, "document"),
                                            (K("098", "5805708071"), refund, "rtdn")])
        d = tgq(sel, "5800920932-933")
        self.assertEqual([p[0] for p in d.pending_probes], [K("098", "5800920932"), K("098", "5800920933")])
        final = L.finalize_pending("tgq", d.link, L.OwnerHit(5, "098", "5800920933", None, None, "TKTT", "BSP_JUN.pdf"))
        self.assertEqual(final.not_in_bsp, "In another BSP upload (BSP_JUN.pdf)")
        self.assertEqual(final.counts_in_net, "No – in another BSP upload")

    def test_unmatchable(self):
        sel = L.SelectionIndex()
        for serial in (None, "", "N/A", "12345", "VOID"):
            with self.subTest(serial=serial):
                d = tgq(sel, serial)
                self.assertEqual(d.action, "emit")
                self.assertEqual(d.link.not_in_bsp, "Unknown – no ticket no.")
                self.assertEqual(d.link.counts_in_net, C.NET_TGQ_UNMATCHABLE)
                self.assertEqual(d.link.flags, ["TGQ_UNMATCHABLE"])
                self.assertEqual(d.pending_probes, [])

    def test_also_in_ndc_and_tp_gds_on_emitted_rows(self):
        sel = L.SelectionIndex()
        ndc = L.KeySet([K("098", "5805708071")])
        gds = L.KeySet([K("098", "5805708071")])
        d = tgq(sel, "5805708071", code=None, ndc=ndc, gds=gds)
        self.assertEqual(d.link.flags, ["ALSO_IN_NDC", "ALSO_IN_TP_GDS"])

    def test_codeless_ambiguous_serial_is_emitted_and_flagged(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071", code="098"))
        index_row(sel, bsp(2, "5805708071", code="176"))
        d = tgq(sel, "5805708071", code=None)
        self.assertEqual(d.action, "emit")
        self.assertIn("LINK_AMBIGUOUS", d.link.flags)

    def test_every_emitted_flag_is_in_the_legend(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        for serial, canon in (("5805708071", C.REFUND), ("x", C.SALE), ("5805708072", C.SALE)):
            for f in tgq(sel, serial, canon).link.flags:
                self.assertIn(f, C.FLAG_LEGEND)


# ── NDC ───────────────────────────────────────────────────────────────────────

class NdcTests(unittest.TestCase):
    def test_sale_in_period_and_other_period(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        index_row(sel, bsp(2, "5805708072", ttype="EMDS", ticket=None), in_period=False)
        link, pending = L.decide_ndc(K("098", "5805708071"), C.SALE, sel)
        self.assertEqual((link.also_in_bsp, link.counts_in_net, pending), ("Yes – this report", "No – settled in BSP", []))
        link, pending = L.decide_ndc(K("098", "5805708072"), C.EMD, sel)
        self.assertEqual(link.also_in_bsp, "Yes – other period (BSP_JUL.pdf)")
        self.assertEqual(link.counts_in_net, C.NET_NDC_IN_BSP)

    def test_rfnd_refund_notice_via_rtdn(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "0012345678", ttype="RFND", ticket=None, rtdn="5805708071"))
        link, pending = L.decide_ndc(K("098", "5805708071"), C.REFUND, sel)
        self.assertEqual((link.also_in_bsp, link.counts_in_net), ("Yes – this report", C.NET_NDC_IN_BSP))
        # a sale group is not settled by the refund notice
        link, pending = L.decide_ndc(K("098", "5805708071"), C.SALE, sel)
        self.assertEqual((link.also_in_bsp, link.counts_in_net), ("No", None))
        self.assertEqual(pending, [(K("098", "5805708071"), frozenset({C.SALE, C.EXCHANGE, C.EMD}), "document")])

    def test_unresolved_and_finalize(self):
        sel = L.SelectionIndex()
        link, pending = L.decide_ndc(K("098", "5805708071"), C.REFUND, sel)
        self.assertEqual(len(pending), 2)
        final = L.finalize_pending("ndc", link, L.OwnerHit(1, None, "0012345678", None, "0985805708071", "RFND", "BSP_AUG.pdf"))
        self.assertEqual((final.also_in_bsp, final.counts_in_net), ("Yes – other upload (BSP_AUG.pdf)", "No – in another BSP upload"))
        final = L.finalize_pending("ndc", link, None)
        self.assertEqual((final.also_in_bsp, final.counts_in_net), ("No", None))

    def test_no_key(self):
        self.assertEqual(L.decide_ndc(None, C.SALE, L.SelectionIndex()), (LinkResult(), []))


# ── owner lookup ──────────────────────────────────────────────────────────────

class OwnerLookupTests(unittest.TestCase):
    def test_probe_forms(self):
        forms = L.owner_probe_forms([K("098", "0580570807"), K(None, "5805708071"), None, K("098", "0580570807")])
        self.assertEqual(forms, ["0580570807", "0980580570807", "980580570807", "580570807", "5805708071"])

    def test_resolve_rekeys_13_digit_and_lost_zero_hits(self):
        probes = [
            (K("098", "5805708071"), SALE_T, "document"),
            (K("098", "5805708072"), SALE_T, "document"),
            (K("098", "5805708073"), SALE_T, "document"),        # only a refund holds it
            (K("098", "5805708074"), frozenset({C.REFUND}), "rtdn"),
            (K("098", "5805708075"), SALE_T, "document"),        # nobody
        ]
        hits = [
            L.OwnerHit(1, None, "0985805708071", "0985805708071", None, "TKTT", "a.pdf"),
            L.OwnerHit(2, None, "985805708072", None, None, "TKTT", "b.xlsx"),           # Excel lost the zero
            L.OwnerHit(3, "098", "0012345678", None, "5805708073", "RFND", "c.pdf"),
            L.OwnerHit(4, "98", "4012345678", None, "5805708074", "RFDA", "d.pdf"),
        ]
        got = L.resolve_outside(probes, hits)
        self.assertEqual([h.row_id if h else None for h in got], [1, 2, None, 4, None])
        # the SQL forms for these probes cover how the hits were stored
        forms = L.owner_probe_forms([p[0] for p in probes])
        self.assertIn("0985805708071", forms)
        self.assertIn("985805708072", forms)

    def test_newest_row_id_wins_and_canon_accepted_either_way(self):
        probes = [(K("098", "5805708071"), SALE_T, "document")]
        hits = [
            L.OwnerHit(5, "098", "5805708071", None, None, "SALE", "old.pdf"),
            L.OwnerHit(9, "098", "5805708071", None, None, "tktt", "new.pdf"),
        ]
        self.assertEqual(L.resolve_outside(probes, hits)[0].file_name, "new.pdf")

    def test_codeless_rules(self):
        hits = [L.OwnerHit(1, "098", "5805708071", None, None, "TKTT", "a"),
                L.OwnerHit(2, "176", "5805708071", None, None, "TKTT", "b"),
                L.OwnerHit(3, None, "5805708079", None, None, "TKTT", "c")]
        got = L.resolve_outside([
            (K(None, "5805708071"), SALE_T, "document"),      # two codes → no guess
            (K("176", "5805708071"), SALE_T, "document"),
            (K("098", "5805708079"), SALE_T, "document"),     # codeless hit
            (K(None, "5805708079"), SALE_T, "document"),
            (None, SALE_T, "document"),
        ], hits)
        self.assertEqual([h.row_id if h else None for h in got], [None, 2, 3, 3, None])

    def test_side_rule(self):
        hits = [L.OwnerHit(1, "098", "0012345678", None, "5805708071", "RFND", "a")]
        refund = frozenset({C.REFUND})
        got = L.resolve_outside([(K("098", "5805708071"), refund, "document"),
                                 (K("098", "5805708071"), refund, "rtdn"),
                                 (K("098", "5805708071"), refund, "any")], hits)
        self.assertEqual([h.row_id if h else None for h in got], [None, 1, 1])


class FinalizePendingTests(unittest.TestCase):
    def test_strings(self):
        hit = L.OwnerHit(1, "098", "5805708071", None, None, "TKTT", "BSP_JUN.pdf")
        base = LinkResult(also_in_bsp="No", not_in_bsp="Yes", flags=["LINK_AMBIGUOUS"])
        cases = {
            ("memo", True): ("Yes – other upload (BSP_JUN.pdf)", None, "No – in another BSP upload"),
            ("memo", False): ("No", None, None),
            ("ra", True): ("Yes – other upload (BSP_JUN.pdf)", None, "No – in another BSP upload"),
            ("ra", False): ("No", None, None),
            ("ndc", True): ("Yes – other upload (BSP_JUN.pdf)", None, "No – in another BSP upload"),
            ("ndc", False): ("No", None, None),
            ("tgq", True): (None, "In another BSP upload (BSP_JUN.pdf)", "No – in another BSP upload"),
            ("tgq", False): (None, "Yes", "No – GDS record, not in BSP"),
        }
        for (kind, found), (also, not_in, net) in cases.items():
            with self.subTest(kind=kind, found=found):
                link = LinkResult(also_in_bsp=None if kind == "tgq" else "No",
                                  not_in_bsp="Yes" if kind == "tgq" else None, flags=list(base.flags))
                out = L.finalize_pending(kind, link, hit if found else None)
                self.assertEqual((out.also_in_bsp, out.not_in_bsp, out.counts_in_net), (also, not_in, net))
                self.assertEqual(out.flags, ["LINK_AMBIGUOUS"])
                self.assertIsNot(out.flags, link.flags)
                self.assertIsNot(out, link)

    def test_unnamed_file_and_unknown_kind(self):
        hit = L.OwnerHit(1, "098", "5805708071", None, None, "TKTT", None)
        self.assertEqual(L.finalize_pending("memo", LinkResult(), hit).also_in_bsp, "Yes – other upload (unnamed upload)")
        with self.assertRaises(ValueError):
            L.finalize_pending("bsp", LinkResult(), hit)


# ── third party ───────────────────────────────────────────────────────────────

class TpFlagsTests(unittest.TestCase):
    def test_also_in_bsp_any_type(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "0012345678", ttype="RFND", ticket=None, rtdn="5805708071"))
        self.assertEqual(L.tp_flags("tp-gds", gds_key=K("098", "5805708071"), sel=sel, canon=C.SALE), ["ALSO_IN_BSP"])
        self.assertEqual(L.tp_flags("tp-gds", gds_key=K("098", "5805708072"), sel=sel, canon=C.SALE), [])
        self.assertEqual(L.tp_flags("tp-lcc", gds_key=None, sel=sel, canon=C.SALE), [])

    def test_refund_without_sale(self):
        sales = L.KeySet([(7, "0985805708071")])
        self.assertEqual(L.tp_flags("tp-gds", canon=C.REFUND, refund_key=(7, "0985805708072"), sale_keys=sales),
                         ["TP_REFUND_WITHOUT_SALE"])
        self.assertEqual(L.tp_flags("tp-gds", canon=C.REFUND, refund_key=(7, "0985805708071"), sale_keys=sales), [])
        self.assertEqual(L.tp_flags("tp-gds", canon=C.REFUND, sale_key=(8, "0985805708071"), sale_keys=sales),
                         ["TP_REFUND_WITHOUT_SALE"])
        self.assertEqual(L.tp_flags("tp-gds", canon=C.SALE, sale_key=(8, "X"), sale_keys=sales), [])
        self.assertEqual(L.tp_flags("tp-gds", canon=C.REFUND, sale_keys=sales), [])       # unkeyed: unprovable

    def test_both_flags(self):
        sel = L.SelectionIndex()
        index_row(sel, bsp(1, "5805708071"))
        flags = L.tp_flags("tp-gds", gds_key=K(None, "5805708071"), sel=sel, canon=C.REFUND,
                           refund_key=(1, "5805708071"), sale_keys=L.KeySet())
        self.assertEqual(flags, ["ALSO_IN_BSP", "TP_REFUND_WITHOUT_SALE"])


if __name__ == "__main__":
    unittest.main()
