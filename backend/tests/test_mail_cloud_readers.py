"""Gmail API and Microsoft Graph readers against a mocked HTTP server. No network.

Run:  python -m unittest tests.test_mail_cloud_readers      (from backend/)
"""

import asyncio
import base64
import os
import sys
import unittest
from datetime import datetime
from unittest import mock
from urllib.parse import parse_qs, urlparse

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.mail import cloud_readers  # noqa: E402
from app.services.mail.oauth import OAuthError  # noqa: E402

SENDER = "accounts@acme-consol.in"
RAW = b"From: accounts@acme-consol.in\r\nSubject: stmt\r\n\r\nbody"
AFTER = datetime(2026, 10, 5, 0, 0, 0)


def _patched(handler):
    """Make every AsyncClient the reader opens talk to `handler` instead of the network."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)
    return mock.patch.object(cloud_readers.httpx, "AsyncClient", side_effect=factory)


def run(coro):
    return asyncio.run(coro)


class GmailTests(unittest.TestCase):

    def setUp(self):
        self.requests: list[httpx.Request] = []

    def handler(self, sizes=None, status=200):
        sizes = sizes or {}

        def h(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if status != 200:
                return httpx.Response(status, json={})
            path, q = request.url.path, parse_qs(urlparse(str(request.url)).query)
            if path.endswith("/messages"):
                return httpx.Response(200, json={"messages": [{"id": "m2"}, {"id": "m1"}, {"id": "m3"}]})
            mid = path.rsplit("/", 1)[-1]
            fmt = q.get("format", [""])[0]
            if fmt == "minimal":
                return httpx.Response(200, json={"id": mid, "internalDate": {"m1": "1000", "m2": "2000", "m3": "3000"}[mid],
                                                 "sizeEstimate": sizes.get(mid, 100), "labelIds": ["SPAM"] if mid == "m2" else ["INBOX"]})
            if fmt == "raw":
                return httpx.Response(200, json={"id": mid, "raw": base64.urlsafe_b64encode(RAW).decode().rstrip("=")})
            if fmt == "metadata":
                return httpx.Response(200, json={"id": mid, "payload": {"headers": [{"name": "From", "value": SENDER},
                                                                                    {"name": "Subject", "value": "huge"}]}})
            return httpx.Response(404)
        return h

    def read(self, **kw):
        args = dict(senders=[SENDER, "b@x.in"], after=AFTER, include_spam=True, skip={"gmail:m3"},
                    limit=10, max_bytes=1000, first_sync=False)
        args.update(kw)
        return run(cloud_readers.gmail_read("tok", **args))

    def test_search_is_strict_and_results_oldest_first(self):
        with _patched(self.handler()):
            out = self.read()
        listing = parse_qs(urlparse(str(self.requests[0].url)).query)
        self.assertEqual(listing["q"][0], f"from:({SENDER} OR b@x.in) after:1791158400 -in:trash")   # 2026-10-05 00:00 UTC
        self.assertEqual(listing["includeSpamTrash"][0], "true")
        self.assertEqual(self.requests[0].headers["authorization"], "Bearer tok")
        self.assertEqual([m.provider_id for m in out.messages], ["gmail:m1", "gmail:m2"])   # m3 skipped
        self.assertEqual([m.folder for m in out.messages], ["INBOX", "SPAM"])
        self.assertEqual(out.messages[0].raw, RAW)
        self.assertEqual(out.messages[0].internaldate, datetime(1970, 1, 1, 0, 0, 1))

    def test_spam_left_out_when_not_wanted(self):
        with _patched(self.handler()):
            self.read(include_spam=False)
        listing = parse_qs(urlparse(str(self.requests[0].url)).query)
        self.assertNotIn("includeSpamTrash", listing)
        self.assertNotIn("-in:trash", listing["q"][0])

    def test_oversized_mail_keeps_headers_only(self):
        with _patched(self.handler(sizes={"m1": 5000})):
            out = self.read()
        big = out.messages[0]
        self.assertTrue(big.too_large)
        self.assertIn(b"Subject: huge", big.raw)

    def test_batch_limit_reports_more_waiting(self):
        with _patched(self.handler()):
            out = self.read(limit=1)
        self.assertEqual(len(out.messages), 1)
        self.assertTrue(out.more_waiting)

    def test_revoked_token_asks_for_reconnect(self):
        with _patched(self.handler(status=401)), self.assertRaises(OAuthError) as ctx:
            self.read()
        self.assertTrue(ctx.exception.reauth)


class GraphTests(unittest.TestCase):

    def setUp(self):
        self.requests: list[httpx.Request] = []
        self.downloaded: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if "/mailFolders/inbox/messages" in url and "page2" not in url:
            return httpx.Response(200, json={
                "value": [
                    {"id": "B", "receivedDateTime": "2026-10-07T10:00:00Z", "from": {"emailAddress": {"address": "Accounts@Acme-Consol.in"}}},
                    {"id": "N", "receivedDateTime": "2026-10-07T11:00:00Z", "from": {"emailAddress": {"address": "news@airline.example"}}},
                ],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?page2=1",
            })
        if "page2" in url:
            return httpx.Response(200, json={"value": [
                # Sent by accounting software on the supplier's behalf: matched on Reply-To.
                {"id": "A", "receivedDateTime": "2026-10-06T09:00:00Z", "from": {"emailAddress": {"address": "noreply@books.example"}},
                 "replyTo": [{"emailAddress": {"address": SENDER}}]},
            ]})
        if "/mailFolders/junkemail/messages" in url:
            return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
        if url.endswith("/$value"):
            mid = url.split("/messages/")[1].split("/")[0]
            self.downloaded.append(mid)
            return httpx.Response(200, content=RAW)
        return httpx.Response(404)

    def read(self, **kw):
        args = dict(is_sender=lambda a: a.lower() == SENDER, after=AFTER, include_spam=True, skip=set(),
                    limit=10, max_bytes=1000, first_sync=False)
        args.update(kw)
        return run(cloud_readers.graph_read("tok", **args))

    def test_only_onboarded_senders_are_downloaded_oldest_first(self):
        with _patched(self.handler):
            out = self.read()
        self.assertEqual(self.downloaded, ["A", "B"])                 # N never downloaded
        self.assertEqual([m.provider_id for m in out.messages], ["graph:A", "graph:B"])
        first = parse_qs(urlparse(str(self.requests[0].url)).query)
        self.assertEqual(first["$filter"][0], "receivedDateTime ge 2026-10-05T00:00:00Z")
        self.assertEqual(first["$orderby"][0], "receivedDateTime asc")
        self.assertEqual(first["$select"][0], "id,from,sender,replyTo,receivedDateTime")   # sender fields only
        self.assertEqual(self.requests[0].headers["prefer"], 'IdType="ImmutableId"')
        self.assertEqual(out.messages[1].internaldate, datetime(2026, 10, 7, 10, 0, 0))

    def test_already_stored_ids_are_not_downloaded_again(self):
        with _patched(self.handler):
            out = self.read(skip={"graph:A"})
        self.assertEqual(self.downloaded, ["B"])
        self.assertEqual(len(out.messages), 1)


if __name__ == "__main__":
    unittest.main()
