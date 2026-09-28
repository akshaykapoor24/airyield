"""The Subscriptions page's Verified column, and the email behind its Resend button.

An unverified owner cannot sign in at all, so the failure modes are: an unverified
account the column does not show, a manual verification that reads as if the user clicked
the link (hiding that a security check was skipped), and a Resend that says a link went
when the mail server refused it.

No DB, no network.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402

from app.services import email_service  # noqa: E402
from app.services.workspace_verification import state_for  # noqa: E402

AT = datetime(2026, 9, 28, 10, 0)


def _user(uid, email, verified, verified_by_id=None, verified_at=None):
    return SimpleNamespace(id=uid, email=email, is_verified=verified,
                           verified_by_id=verified_by_id, verified_at=verified_at)


class TestState(unittest.TestCase):
    def test_unverified_owner(self):
        owner = _user(1, "owner@acme.com", False)
        s = state_for(owner, [owner], {})
        self.assertEqual((s["status"], s["unverified_emails"], s["verified_at"]),
                         ("unverified", ["owner@acme.com"], None))

    def test_verified_by_link_names_nobody(self):
        owner = _user(1, "owner@acme.com", True, verified_at=AT)
        s = state_for(owner, [owner], {})
        self.assertEqual((s["status"], s["verified_at"], s["verified_by"]), ("verified", AT, None))

    def test_verified_by_hand_names_the_admin(self):
        """A skipped mailbox check must never read like a clicked link."""
        owner = _user(1, "owner@acme.com", True, verified_by_id=99, verified_at=AT)
        self.assertEqual(state_for(owner, [owner], {99: "Akshay Kapoor"})["verified_by"], "Akshay Kapoor")

    def test_a_removed_admin_still_reads_as_manual(self):
        owner = _user(1, "owner@acme.com", True, verified_by_id=99, verified_at=AT)
        self.assertEqual(state_for(owner, [owner], {})["verified_by"], "a platform admin")

    def test_any_unverified_member_makes_the_workspace_unverified(self):
        """Today only owners start unverified; the column must not rely on that."""
        owner = _user(1, "owner@acme.com", True)
        stray = _user(2, "new@acme.com", False)
        s = state_for(owner, [stray, owner], {})
        self.assertEqual((s["status"], s["unverified_emails"]), ("unverified", ["new@acme.com"]))

    def test_a_workspace_with_no_accounts(self):
        s = state_for(None, [], {})
        self.assertEqual((s["status"], s["unverified_emails"], s["verified_at"]), ("no_users", [], None))


class TestVerificationEmail(unittest.TestCase):
    def test_signup_swallows_a_failure(self):
        with mock.patch.object(email_service.smtplib, "SMTP", side_effect=OSError("refused")), \
                self.assertLogs(email_service.logger, level="ERROR"):
            asyncio.run(email_service.send_verification_email("a@b.com", "https://x/verify?t=1"))

    def test_the_admin_resend_hears_about_it(self):
        with mock.patch.object(email_service.smtplib, "SMTP", side_effect=OSError("refused")), \
                self.assertLogs(email_service.logger, level="ERROR"), self.assertRaises(OSError):
            asyncio.run(email_service.send_verification_email("a@b.com", "https://x/verify?t=1", raise_errors=True))


if __name__ == "__main__":
    unittest.main()
