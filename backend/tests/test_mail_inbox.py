"""Email intake — receiving: sender registry, MIME parsing, sender matching, file sniffing.

No network, no database. Run:  python -m unittest tests.test_mail_inbox   (from backend/)
"""

import os
import sys
import unittest
from email.message import EmailMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.mail_inbox import sniff  # noqa: E402
from app.services.mail import mime, registry  # noqa: E402
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
        self.assertEqual(reg.lookup("someone@acme.in"), [])      # exact addresses only, no domain rule

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
        self.assertEqual(_match(self._parsed("accounts@acme-consol.in"), self.reg), ("accounts@acme-consol.in", [self.party]))

    def test_imap_substring_false_positive_is_rejected(self):
        # IMAP FROM "accounts@acme-consol.in" also matches this; the sync must not keep it.
        self.assertEqual(_match(self._parsed("fake.accounts@acme-consol.in.evil.example"), self.reg), (None, []))

    def test_sent_by_accounting_software_on_behalf(self):
        addr, parties = _match(self._parsed('"ACME" <message-service@books.example>', "accounts@acme-consol.in"), self.reg)
        self.assertEqual((addr, parties), ("accounts@acme-consol.in", [self.party]))


class SniffTests(unittest.TestCase):

    def test_real_types_not_claims(self):
        self.assertEqual(sniff(b"%PDF-1.7 ..."), "application/pdf")
        self.assertEqual(sniff(b"\x89PNG\r\n\x1a\n...."), "image/png")
        self.assertEqual(sniff(b"\xff\xd8\xff\xe0..."), "image/jpeg")
        self.assertIsNone(sniff(b"<html><script>"))       # an "invoice.pdf" that is HTML stays a download
        self.assertIsNone(sniff(b"MZ\x90\x00"))           # an executable never previews


if __name__ == "__main__":
    unittest.main()
