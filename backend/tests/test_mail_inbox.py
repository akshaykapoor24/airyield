"""Email intake — receiving: sender registry, MIME parsing, sender matching, file sniffing.

No network, no database. Run:  python -m unittest tests.test_mail_inbox   (from backend/)
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.mail_inbox import sniff  # noqa: E402
from app.services.mail import cloud_readers, mime, registry, sync  # noqa: E402
from app.services.mail.sync import _match  # noqa: E402


class AddressExtractionTests(unittest.TestCase):
    """Master cells are free text — the supplier directory packs several addresses into one."""

    def test_messy_cells(self):
        self.assertEqual(
            registry.extract_addresses("Rahul Sharma <Rahul@Acme-Consol.in>, accounts@acme-consol.in / 98xxxxxxxx"),
            ["rahul@acme-consol.in", "accounts@acme-consol.in"])
        self.assertEqual(registry.extract_addresses("NA"), [])
        self.assertEqual(registry.extract_addresses("same as above"), [])
        self.assertEqual(registry.extract_addresses(None), [])
        self.assertEqual(registry.extract_addresses("ops@agency.in; ops@agency.in."), ["ops@agency.in"])

    def test_plus_tags_match_the_base_address(self):
        reg = registry.Registry()
        party = registry.Party("agency", 1, "ACME — Delhi · GDS", 14)
        reg.add("accounts@acme.in", party)
        self.assertEqual(reg.lookup("Accounts+stmt@ACME.in"), [party])
        self.assertEqual(reg.lookup("someone@acme.in"), [])      # no domain added to this registry

    def test_one_address_two_master_rows(self):
        reg = registry.Registry()
        gds = registry.Party("agency", 1, "ACME — Delhi · GDS", 14)
        lcc = registry.Party("agency", 2, "ACME — Delhi · LCC", 14)
        reg.add("ops@acme.in", gds)
        reg.add("ops@acme.in", lcc)
        reg.add("ops@acme.in", gds)                              # no duplicates
        self.assertEqual(reg.lookup("ops@acme.in"), [gds, lcc])
        self.assertEqual(gds.as_dict()["segment"], "B2B")


def _mail() -> EmailMessage:
    m = EmailMessage()
    m["From"] = '"ACME Consolidators" <Accounts@Acme-Consol.in>'
    m["To"] = "ops@youragency.in"
    m["Cc"] = "finance@youragency.in"
    m["Subject"] = "=?utf-8?q?BSP_STATEMENT_23-31ST_AUG_26_=E2=80=94_revised?="
    m["Date"] = "Wed, 07 Oct 2026 10:42:00 +0530"
    m["Message-ID"] = "<abc123@acme-consol.in>"
    m.set_content("Dear Sir, PFA statement. Total 245 tickets, net payable Rs 12,34,567.")
    m.add_alternative('<p>Dear Sir, PFA statement.</p><img src="cid:logo1">', subtype="html")
    m.get_payload()[1].add_related(b"\x89PNG\r\n\x1a\nxx", maintype="image", subtype="png", cid="<logo1>")
    m.add_attachment(b"PK\x03\x04fake-xlsx", maintype="application",
                     subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     filename="ACME BSP STATEMENT 23-31ST AUG 26.xlsx")
    inner = EmailMessage()
    inner["From"] = "airline@carrier.example"
    inner["Subject"] = "Deal sheet"
    inner.set_content("see attached")
    inner.add_attachment(b"%PDF-1.4 deal", maintype="application", subtype="pdf", filename="Deal Sheet Effective 03Oct26.pdf")
    m.add_attachment(inner)
    return m


class MimeTests(unittest.TestCase):

    def setUp(self):
        self.parsed = mime.parse(_mail().as_bytes())

    def test_headers(self):
        p = self.parsed
        self.assertEqual(p.from_address, "accounts@acme-consol.in")
        self.assertEqual(p.from_name, "ACME Consolidators")
        self.assertEqual(p.subject, "BSP STATEMENT 23-31ST AUG 26 — revised")   # RFC 2047 decoded
        self.assertEqual(p.to, ["ops@youragency.in"])
        self.assertEqual(p.cc, ["finance@youragency.in"])
        self.assertEqual(p.message_id, "<abc123@acme-consol.in>")
        self.assertEqual(str(p.sent_at), "2026-10-07 05:12:00")               # IST → naive UTC

    def test_bodies(self):
        self.assertIn("245 tickets", self.parsed.text)
        self.assertIn("cid:logo1", self.parsed.html)
        self.assertTrue(self.parsed.snippet.startswith("Dear Sir"))

    def test_attachments_inline_image_and_forwarded_mail(self):
        names = [p.filename for p in self.parsed.attachments]
        self.assertIn("ACME BSP STATEMENT 23-31ST AUG 26.xlsx", names)
        # The forwarded mail is kept as .eml AND its own attachment surfaces.
        self.assertTrue(any(n.endswith(".eml") for n in names))
        self.assertIn("Deal Sheet Effective 03Oct26.pdf", names)
        inline = [p for p in self.parsed.parts if p.is_inline]
        self.assertEqual([(p.content_id, p.content_type) for p in inline], [("logo1", "image/png")])
        self.assertNotIn("logo1", [p.content_id for p in self.parsed.attachments])

    def test_text_only_and_html_only_mail(self):
        plain = EmailMessage()
        plain["From"] = "a@b.in"
        plain.set_content("hello")
        self.assertEqual(mime.parse(plain.as_bytes()).text.strip(), "hello")
        html = EmailMessage()
        html["From"] = "a@b.in"
        html.set_content("<p>Hi <b>there</b></p>", subtype="html")
        parsed = mime.parse(html.as_bytes())
        self.assertIsNone(parsed.text)
        self.assertEqual(parsed.snippet, "Hi there")

    def test_nameless_attachment_gets_a_name(self):
        m = EmailMessage()
        m["From"] = "a@b.in"
        m.set_content("x")
        m.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf")
        self.assertTrue(mime.parse(m.as_bytes()).attachments[0].filename.endswith(".pdf"))


class MatchTests(unittest.TestCase):

    def setUp(self):
        self.reg = registry.Registry()
        self.party = registry.Party("agency", 7, "ACME", 14)
        self.reg.add("accounts@acme-consol.in", self.party)

    def _parsed(self, frm, reply_to=None):
        m = EmailMessage()
        m["From"] = frm
        if reply_to:
            m["Reply-To"] = reply_to
        m.set_content("x")
        return mime.parse(m.as_bytes())

    def test_exact_from(self):
        self.assertEqual(_match(self._parsed("accounts@acme-consol.in"), self.reg),
                         ("accounts@acme-consol.in", "address", [self.party]))

    def test_imap_substring_false_positive_is_rejected(self):
        # IMAP FROM "accounts@acme-consol.in" also matches this; the sync must not keep it.
        self.assertEqual(_match(self._parsed("fake.accounts@acme-consol.in.evil.example"), self.reg), (None, None, []))

    def test_sent_by_accounting_software_on_behalf(self):
        addr, via, parties = _match(self._parsed('"ACME" <message-service@books.example>', "accounts@acme-consol.in"), self.reg)
        self.assertEqual((addr, via, parties), ("accounts@acme-consol.in", "address", [self.party]))

    def test_colleague_at_the_same_domain(self):
        self.reg.add_domain("acme-consol.in", self.party)
        self.assertEqual(_match(self._parsed('"Priya" <priya.s@Acme-Consol.in>'), self.reg),
                         ("priya.s@acme-consol.in", "domain", [self.party]))
        # IMAP FROM "@acme-consol.in" is a substring match: a lookalike domain must not get in.
        self.assertEqual(_match(self._parsed("x@acme-consol.in.evil.example"), self.reg), (None, None, []))
        self.assertEqual(_match(self._parsed("x@mail.acme-consol.in"), self.reg), (None, None, []))   # no subdomains


# ── building the registry from the masters ──────────────────────────────────

def _agency(id, email, user_id=14, name="GTM Vantage"):
    return SimpleNamespace(id=id, contact_email=email, user_id=user_id, name=name,
                           branch_name="Delhi", branch_code=None, channels="GDS")


def _corporate(id, email, company="Infosys", created_by_id=14):
    return SimpleNamespace(id=id, email=email, company=company, created_by_id=created_by_id)


def _customer(id, email, corporate_id=None, first="Rahul", company=None, created_by_id=14):
    return SimpleNamespace(id=id, email=email, corporate_id=corporate_id, first_name=first, last_name=None,
                           company=company, created_by_id=created_by_id)


class _FakeDB:
    """build() runs four selects, in order: the workspace users' emails, agencies, corporates, customers."""

    def __init__(self, users=(), agencies=(), corporates=(), customers=()):
        self._results = [list(users), list(agencies), list(corporates), list(customers)]

    async def execute(self, _query):
        rows = self._results.pop(0)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _build(mailbox="ops@youragency.in", **rows) -> registry.Registry:
    return asyncio.run(registry.build(_FakeDB(**rows), 1, [14], mailbox_address=mailbox))


class DomainRegistryTests(unittest.TestCase):
    """One onboarded address reads its whole company — never a free-mail or the workspace's own domain."""

    def test_anyone_at_an_onboarded_agency_domain(self):
        reg = _build(agencies=[_agency(1, "Manvendra@GTMVantage.com")])
        via, parties = reg.match("rahul.k@gtmvantage.com")
        self.assertEqual((via, [p.party_id for p in parties]), ("domain", [1]))
        self.assertEqual(reg.match("manvendra@gtmvantage.com")[0], "address")
        # One "@domain" term covers the typed address too: shorter IMAP / Gmail searches.
        self.assertEqual(reg.search_terms, ["@gtmvantage.com"])

    def test_free_mail_stays_exact_address_only(self):
        reg = _build(agencies=[_agency(1, "lordstravels@gmail.com"), _agency(2, "ops@rediffmail.com"),
                               _agency(3, "acc@sify.com")])
        self.assertEqual(reg.lookup("anyone@gmail.com"), [])
        self.assertEqual(reg.lookup("anyone@sify.com"), [])
        self.assertEqual([p.party_id for p in reg.lookup("lordstravels@gmail.com")], [1])
        self.assertEqual(reg.search_terms, ["acc@sify.com", "lordstravels@gmail.com", "ops@rediffmail.com"])

    def test_workspace_own_domain_is_never_a_domain_sender(self):
        reg = _build(mailbox="accounts@youragency.co.in",
                     users=["owner@youragency.in", None],
                     customers=[_customer(5, "test@youragency.in"), _customer(6, "me@youragency.co.in")])
        self.assertEqual(reg.match("test@youragency.in")[0], "address")      # typed: still read
        self.assertEqual(reg.lookup("colleague@youragency.in"), [])          # internal mail: not read
        self.assertEqual(reg.lookup("colleague@youragency.co.in"), [])       # the mailbox's own domain

    def test_exact_address_beats_the_domain(self):
        reg = _build(agencies=[_agency(1, "manvendra@gtmvantage.com")],
                     customers=[_customer(9, "rahul@gtmvantage.com", first="Rahul")])
        self.assertEqual(reg.lookup("rahul@gtmvantage.com")[0].party_type, "customer")
        self.assertEqual(reg.lookup("priya@gtmvantage.com")[0].party_type, "agency")

    def test_an_organisation_owns_its_domain_before_a_customer(self):
        reg = _build(corporates=[_corporate(3, "travel@infosys.com")],
                     customers=[_customer(9, "rahul@infosys.com")])     # not linked to the corporate
        self.assertEqual([(p.party_type, p.party_id) for p in reg.lookup("priya@infosys.com")], [("corporate", 3)])

    def test_an_employees_work_domain_is_their_corporates(self):
        # The corporate was onboarded with a Gmail address; its employee with a work address.
        reg = _build(corporates=[_corporate(3, "infosys.travel@gmail.com")],
                     customers=[_customer(9, "rahul@infosys.com", corporate_id=3),
                                _customer(10, "amit@infosys.com", corporate_id=3)])
        self.assertEqual([(p.party_type, p.party_id) for p in reg.lookup("priya@infosys.com")], [("corporate", 3)])
        self.assertEqual(reg.lookup("amit@infosys.com")[0].party_id, 10)

    def test_a_direct_customers_company_domain(self):
        reg = _build(customers=[_customer(9, "rahul@deloitte.com", company="Deloitte")])
        via, parties = reg.match("priya@deloitte.com")
        self.assertEqual((via, parties[0].party_id), ("domain", 9))

    def test_one_vendor_two_channel_rows_share_the_domain(self):
        reg = _build(agencies=[_agency(1, "ops@acme.in"), _agency(2, "accounts@acme.in")])
        self.assertEqual([p.party_id for p in reg.lookup("priya@acme.in")], [1, 2])
        self.assertEqual(reg.match("priya@acme.in")[1][0].as_dict("domain")["via"], "domain")


# ── Gmail / Microsoft: reaching back when a sender is added ─────────────────

class CloudWindowTests(unittest.TestCase):
    """A domain or party added since the last check has older mail the time window never covered."""

    def setUp(self):
        self.reg = registry.Registry()
        self.reg.add_domain("gtmvantage.com", registry.Party("agency", 1, "GTM", 14))
        self.now = datetime.utcnow()
        self.last_check = self.now - timedelta(hours=1)

    def _read(self, known, messages=(), more_waiting=False):
        conn = SimpleNamespace(provider="gmail", sync_cursor={"cloud": {
            "last_check": self.last_check.isoformat(), "senders": known, "ignored": []}})
        seen = {}

        async def fake_gmail(token, *, senders, after, **kw):
            seen.update(senders=senders, after=after)
            return cloud_readers.CloudRead(messages=list(messages), more_waiting=more_waiting)

        with mock.patch.object(sync, "_access_token", mock.AsyncMock(return_value="t")), \
                mock.patch.object(cloud_readers, "gmail_read", fake_gmail):
            read = asyncio.run(sync._read_cloud(None, conn, self.reg, set(), {"backfill_days": 30}))
        return read, seen

    def _msg(self, days_ago):
        return cloud_readers.CloudFetched(provider_id=f"gmail:{days_ago}", folder="INBOX", size=1, raw=b"",
                                          internaldate=self.now - timedelta(days=days_ago))

    def test_new_domain_reaches_back_and_imports_older_mail_quietly(self):
        old, recent = self._msg(20), self._msg(1)
        read, seen = self._read(["manvendra@gtmvantage.com"], [old, recent])
        self.assertEqual(seen["senders"], ["@gtmvantage.com"])
        self.assertLess(seen["after"], self.now - timedelta(days=29))                # the backfill window
        self.assertTrue(old.first_sync)            # earlier mail: one summary notification
        self.assertFalse(recent.first_sync)        # inside the usual lookback: its own notification
        self.assertEqual(read.cursors["__cloud__"]["senders"], ["@gtmvantage.com"])

    def test_known_senders_keep_the_short_window(self):
        _, seen = self._read(["@gtmvantage.com"])
        self.assertGreater(seen["after"], self.now - timedelta(days=sync.LOOKBACK_DAYS + 1))

    def test_unfinished_reach_back_is_resumed_next_check(self):
        read, _ = self._read(["manvendra@gtmvantage.com"], more_waiting=True)
        cur = read.cursors["__cloud__"]
        self.assertEqual(cur["senders"], ["manvendra@gtmvantage.com"])            # widens again next time
        self.assertEqual(cur["last_check"], self.last_check.isoformat())


class SniffTests(unittest.TestCase):

    def test_real_types_not_claims(self):
        self.assertEqual(sniff(b"%PDF-1.7 ..."), "application/pdf")
        self.assertEqual(sniff(b"\x89PNG\r\n\x1a\n...."), "image/png")
        self.assertEqual(sniff(b"\xff\xd8\xff\xe0..."), "image/jpeg")
        self.assertIsNone(sniff(b"<html><script>"))       # an "invoice.pdf" that is HTML stays a download
        self.assertIsNone(sniff(b"MZ\x90\x00"))           # an executable never previews


if __name__ == "__main__":
    unittest.main()
