"""Email intake — connecting a mailbox: credential crypto, provider detection, IMAP folder
parsing and the SSRF guard, OAuth PKCE / consent URLs. No network, no database.

Run:  python -m unittest tests.test_mail_connect      (from backend/)
"""

import base64
import hashlib
import os
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.mail import crypto, detect, imap_client, oauth  # noqa: E402

KEY = base64.b64encode(b"k" * 32).decode()
OTHER_KEY = base64.b64encode(b"z" * 32).decode()


class CryptoTests(unittest.TestCase):

    def test_round_trip(self):
        aad = crypto.row_aad(4, 17)
        enc, dek, ref = crypto.encrypt({"refresh_token": "1//abc"}, aad, master_key=KEY)
        self.assertEqual(ref, crypto.KEY_REF)
        self.assertNotIn(b"1//abc", enc)
        self.assertEqual(crypto.decrypt(enc, dek, aad, master_key=KEY), {"refresh_token": "1//abc"})

    def test_ciphertext_copied_to_another_row_does_not_open(self):
        enc, dek, _ = crypto.encrypt({"password": "x"}, crypto.row_aad(4, 17), master_key=KEY)
        with self.assertRaises(crypto.CredentialsUnreadable):
            crypto.decrypt(enc, dek, crypto.row_aad(5, 17), master_key=KEY)      # other workspace
        with self.assertRaises(crypto.CredentialsUnreadable):
            crypto.decrypt(enc, dek, crypto.row_aad(4, 18), master_key=KEY)      # other mailbox

    def test_wrong_master_key_does_not_open(self):
        aad = crypto.row_aad(1, 1)
        enc, dek, _ = crypto.encrypt({"a": 1}, aad, master_key=KEY)
        with self.assertRaises(crypto.CredentialsUnreadable):
            crypto.decrypt(enc, dek, aad, master_key=OTHER_KEY)

    def test_each_row_gets_its_own_data_key(self):
        aad = crypto.row_aad(1, 1)
        a = crypto.encrypt({"a": 1}, aad, master_key=KEY)
        b = crypto.encrypt({"a": 1}, aad, master_key=KEY)
        self.assertNotEqual(a[0], b[0])
        self.assertNotEqual(a[1], b[1])

    def test_missing_or_bad_key_refuses(self):
        for bad in ("", "not base64!!", base64.b64encode(b"short").decode()):
            with self.assertRaises(crypto.CryptoNotConfigured):
                crypto.encrypt({}, b"x", master_key=bad)


class DetectTests(unittest.TestCase):

    def test_normalise(self):
        self.assertEqual(detect.normalise_address("  Ops@Agency.IN "), "ops@agency.in")
        with self.assertRaises(detect.InvalidAddress):
            detect.normalise_address("same as above")

    def test_public_providers_need_no_dns(self):
        self.assertEqual(detect.classify("gmail.com", []).provider, "gmail")
        self.assertEqual(detect.classify("outlook.com", []).provider, "microsoft")
        s = detect.classify("zohomail.in", [])
        self.assertEqual((s.provider, s.imap_host), ("imap", "imap.zoho.in"))

    def test_business_domains_by_mx(self):
        cases = {
            "aspmx.l.google.com.": ("gmail", None),
            "agency-in.mail.protection.outlook.com": ("microsoft", None),
            # A business domain on Zoho is an organisation account → imappro, not imap.
            "mx.zoho.in": ("imap", "imappro.zoho.in"),
            "mx1.zoho.com": ("imap", "imappro.zoho.com"),
            "smtp.secureserver.net": ("imap", "imap.secureserver.net"),
            "mx1.titan.email": ("imap", "imap.titan.email"),
            "mx1.hostinger.in": ("imap", "imap.hostinger.com"),
        }
        for mx, expected in cases.items():
            s = detect.classify("acme-travels.in", [mx])
            self.assertEqual((s.provider, s.imap_host), expected, mx)

    def test_unknown_host_is_imap_without_a_guess(self):
        s = detect.classify("acme-travels.in", ["mail.acme-travels.in"])
        self.assertEqual((s.provider, s.imap_host), ("imap", None))
        self.assertIn("mail.acme-travels.in", s.note)

    def test_no_mx_cannot_tell(self):
        self.assertIsNone(detect.classify("acme-travels.in", []).provider)


class ImapParsingTests(unittest.TestCase):

    def test_list_lines(self):
        f = imap_client.parse_list_line(b'(\\HasNoChildren \\Junk) "/" "Junk"')
        self.assertEqual((f.name, f.special_use), ("Junk", "junk"))
        f = imap_client.parse_list_line(b'(\\HasNoChildren) "." INBOX')
        self.assertEqual(f.name, "INBOX")
        self.assertIsNone(imap_client.parse_list_line(b'(\\Noselect \\HasChildren) "/" "[Gmail]"'))
        self.assertIsNone(imap_client.parse_list_line(b"garbage"))

    def test_modified_utf7_names(self):
        self.assertEqual(imap_client.decode_modified_utf7("Statements &- Deals"), "Statements & Deals")
        self.assertEqual(imap_client.decode_modified_utf7("&AMk-tat"), "État")
        self.assertEqual(imap_client.decode_modified_utf7("INBOX"), "INBOX")

    def test_folder_suggestion_finds_junk_by_flag_or_name(self):
        folders = [imap_client.parse_list_line(x) for x in (
            b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Spam"', b'(\\Sent) "/" "Sent"')]
        inbox, junk = imap_client.suggest_folders(folders)
        self.assertEqual((inbox, junk), (["INBOX"], "Spam"))


class ImapHostGuardTests(unittest.TestCase):
    """The host is user input: never let 'test my mailbox' reach the private network."""

    def _resolving_to(self, *ips):
        return mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 993)) for ip in ips])

    def test_private_and_loopback_addresses_are_refused(self):
        for ip in ("127.0.0.1", "10.32.224.3", "192.168.1.5", "169.254.169.254", "::1"):
            with self._resolving_to(ip), self.assertRaises(imap_client.ImapError) as ctx:
                imap_client.resolve_public("imap.example.com", 993)
            self.assertEqual(ctx.exception.code, "blocked_host", ip)

    def test_a_name_resolving_to_both_public_and_private_is_refused(self):
        with self._resolving_to("8.8.8.8", "10.0.0.7"), self.assertRaises(imap_client.ImapError):
            imap_client.resolve_public("imap.example.com", 993)

    def test_nat64_is_judged_by_the_ipv4_inside(self):
        # IPv6-only ISPs resolve imappro.zoho.in to 64:ff9b::<public v4> — must pass…
        with self._resolving_to("64:ff9b::a994:95d7", "169.148.149.215"):
            self.assertEqual(imap_client.resolve_public("imappro.zoho.in", 993), "169.148.149.215")
        # …while a NAT64 wrapper around a private v4 (10.32.224.3) is still refused.
        with self._resolving_to("64:ff9b::a20:e003"), self.assertRaises(imap_client.ImapError):
            imap_client.resolve_public("imap.example.com", 993)
        with self._resolving_to("::ffff:127.0.0.1"), self.assertRaises(imap_client.ImapError):
            imap_client.resolve_public("imap.example.com", 993)

    def test_public_address_passes(self):
        with self._resolving_to("8.8.8.8"):
            self.assertEqual(imap_client.resolve_public("imap.example.com", 993), "8.8.8.8")

    def test_only_imap_ports(self):
        for port in (22, 5432, 6379, 110, 80):
            with self.assertRaises(imap_client.ImapError) as ctx:
                imap_client.resolve_public("imap.example.com", port)
            self.assertEqual(ctx.exception.code, "bad_port")

    def test_junk_host_names(self):
        for host in ("", "imap.example.com/../x", "imap example.com", "http://imap.example.com"):
            with self.assertRaises(imap_client.ImapError):
                imap_client.resolve_public(host, 993)


class OAuthTests(unittest.TestCase):

    def test_pkce_is_s256_of_the_verifier(self):
        verifier, challenge = oauth.pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        self.assertTrue(43 <= len(verifier) <= 128)

    def test_google_consent_url_is_read_only_offline_and_pkce(self):
        with mock.patch.object(oauth.settings, "GOOGLE_OAUTH_CLIENT_ID", "cid"), \
             mock.patch.object(oauth.settings, "API_PUBLIC_URL", "https://api.fareqube.com/"):
            q = parse_qs(urlparse(oauth.google_consent_url("st", "ch", "ops@agency.in")).query)
        self.assertEqual(q["scope"][0], "openid email https://www.googleapis.com/auth/gmail.readonly")
        self.assertEqual(q["access_type"][0], "offline")
        self.assertEqual(q["code_challenge_method"][0], "S256")
        self.assertEqual(q["redirect_uri"][0], "https://api.fareqube.com/api/v1/mail/oauth/google/callback")
        self.assertEqual(q["login_hint"][0], "ops@agency.in")

    def test_microsoft_scopes_have_no_write_permission(self):
        with mock.patch.object(oauth.settings, "MS_OAUTH_CLIENT_ID", "cid"):
            q = parse_qs(urlparse(oauth.microsoft_consent_url("st", "ch", None)).query)
        scopes = q["scope"][0].split()
        self.assertIn("Mail.Read", scopes)
        self.assertIn("offline_access", scopes)
        self.assertFalse([s for s in scopes if "Write" in s or "Send" in s])

    def test_admin_consent_error_explains_the_way_out(self):
        msg = oauth.provider_error_message("microsoft", "access_denied", "AADSTS65001: The user or administrator has not consented")
        self.assertIn("admin", msg)
        self.assertIn("forwarding", msg)

    def test_id_token_claims_are_read_without_crashing_on_junk(self):
        body = base64.urlsafe_b64encode(b'{"tid":"t1","oid":"o1"}').rstrip(b"=").decode()
        self.assertEqual(oauth._jwt_claims(f"h.{body}.s"), {"tid": "t1", "oid": "o1"})
        self.assertEqual(oauth._jwt_claims("not-a-jwt"), {})
        self.assertEqual(oauth._jwt_claims(None), {})


if __name__ == "__main__":
    unittest.main()
