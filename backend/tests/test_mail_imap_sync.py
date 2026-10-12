"""IMAP sync against a fake server — the cursor must never skip a message for good.

Reproduces a real loss seen on Zoho (2026-10-08): a mail from an onboarded sender arrived a
minute before a check. The server had already given it a UID (UIDNEXT moved past it) but had
not yet indexed its From header for SEARCH, so the FROM search missed it — and the cursor
jumped to UIDNEXT-1, never to look below it again.

Run:  python -m unittest tests.test_mail_imap_sync      (from backend/)
"""

import os
import sys
import unittest
from datetime import date
from email.message import EmailMessage
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.mail import imap_client  # noqa: E402

SENDER = "manvendrachauhan292001@gmail.com"


def _raw(frm: str, subject: str) -> bytes:
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subject
    m.set_content("x")
    return m.as_bytes()


class FakeImap:
    """Just enough IMAP4 for _read_sync: STATUS, EXAMINE, UID SEARCH, UID FETCH."""

    def __init__(self):
        self.messages: dict[int, dict] = {}     # uid → {from, date, raw}
        self.unindexed: set[int] = set()        # delivered, but invisible to FROM searches
        self.fetched: list[int] = []

    def add(self, uid, frm, when=date(2026, 10, 8), indexed=True):
        self.messages[uid] = {"from": frm, "date": when, "raw": _raw(frm, f"mail {uid}")}
        if not indexed:
            self.unindexed.add(uid)

    # imaplib surface
    def status(self, folder, what):
        nxt = max(self.messages, default=0) + 1
        return "OK", [f'{folder} (UIDNEXT {nxt} UIDVALIDITY 1)'.encode()]

    def select(self, folder, readonly=False):
        assert readonly, "the sync must open folders read-only (EXAMINE)"
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [" ".join(str(u) for u in sorted(self._search(list(args)))).encode()]
        if command == "FETCH":
            uids = [int(u) for u in args[0].split(",")]
            if "RFC822.SIZE" in args[1]:
                return "OK", [f'{i} (UID {u} RFC822.SIZE {len(self.messages[u]["raw"])} INTERNALDATE "08-Oct-2026 12:08:01 +0530")'.encode()
                              for i, u in enumerate(uids, 1)]
            assert "PEEK" in args[1], "bodies must be fetched with BODY.PEEK so nothing is marked read"
            self.fetched += uids
            return "OK", [(f"1 (UID {uids[0]} BODY[] {{1}}".encode(), self.messages[uids[0]]["raw"]), b")"]
        raise AssertionError(command)

    def logout(self):
        return "BYE", []

    # a tiny SEARCH evaluator: UID <range>, SINCE <date>, FROM "<s>", OR <k1> <k2>
    def _search(self, tokens):
        pos = 0

        def key():
            nonlocal pos
            t = tokens[pos]
            pos += 1
            if t == "OR":
                a, b = key(), key()
                return lambda u: a(u) or b(u)
            if t == "FROM":
                needle = tokens[pos].strip('"').lower()
                pos += 1
                return lambda u: u not in self.unindexed and needle in self.messages[u]["from"].lower()
            if t == "UID":
                lo, hi = tokens[pos].split(":")
                pos += 1
                lo = int(lo)
                return lambda u: u >= lo and (hi == "*" or u <= int(hi))
            if t == "SINCE":
                from datetime import datetime
                d = datetime.strptime(tokens[pos], "%d-%b-%Y").date()
                pos += 1
                return lambda u: self.messages[u]["date"] >= d
            raise AssertionError(t)

        preds = []
        while pos < len(tokens):
            preds.append(key())
        hits = {u for u in self.messages if all(p(u) for p in preds)}
        # Real servers: "n:*" with n beyond the last UID still returns the newest message.
        if tokens[:1] == ["UID"] and tokens[1].endswith(":*") and self.messages \
                and int(tokens[1].split(":")[0]) > max(self.messages):
            hits = {max(self.messages)}
        return hits


def run(server, cursors, existing=()):
    with mock.patch.object(imap_client, "open_session", return_value=server):
        return imap_client._read_sync(
            "imap.example.com", 993, "u", "p", folders=["INBOX"], cursors=cursors, senders=[SENDER],
            since=date(2026, 9, 8), existing={imap_client.provider_message_id("INBOX", 1, u) for u in existing},
            limit=100, max_bytes=10_000_000, lookback=date(2026, 10, 5))


class IndexLagTests(unittest.TestCase):

    def test_a_mail_not_yet_searchable_is_picked_up_on_the_next_check(self):
        server = FakeImap()
        server.add(1, f"Me <{SENDER}>")
        first = run(server, {})
        self.assertEqual([m.uid for m in first.messages], [1])

        # Delivered seconds before the next check: UID assigned, From not indexed yet.
        server.add(2, f"Me <{SENDER}>", indexed=False)
        server.add(3, "someone@else.example")                     # not an onboarded sender
        second = run(server, first.cursors, existing={1})
        self.assertEqual(second.messages, [])
        self.assertEqual(second.cursors["INBOX"]["last_uid"], 3)  # the cursor DID move past it…

        server.unindexed.clear()                                  # …the index catches up
        third = run(server, second.cursors, existing={1})
        self.assertEqual([m.uid for m in third.messages], [2])    # …and the lookback still finds it

    def test_stored_mail_is_never_fetched_twice(self):
        server = FakeImap()
        server.add(1, SENDER)
        server.add(2, SENDER)
        first = run(server, {})
        again = run(server, first.cursors, existing={1, 2})
        self.assertEqual(again.messages, [])

    def test_ignored_uids_are_not_downloaded_again(self):
        # IMAP FROM is a substring match: this address contains the sender's, but is not it.
        server = FakeImap()
        server.add(1, f"x.{SENDER}.evil.example")
        first = run(server, {})
        self.assertEqual([m.uid for m in first.messages], [1])    # fetched once, then judged not ours
        cursors = first.cursors
        cursors["INBOX"]["ignored"] = [1]                         # what sync.py records for it
        server.fetched.clear()
        run(server, cursors)
        self.assertEqual(server.fetched, [])

    def test_first_import_respects_the_backfill_window(self):
        server = FakeImap()
        server.add(1, SENDER, when=date(2026, 8, 1))              # older than 30 days
        server.add(2, SENDER, when=date(2026, 10, 1))
        first = run(server, {})
        self.assertEqual([(m.uid, m.first_sync) for m in first.messages], [(2, True)])


if __name__ == "__main__":
    unittest.main()
