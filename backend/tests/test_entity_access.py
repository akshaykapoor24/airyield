"""Who manages a workspace's entities and login IDs, and what everyone else sees.

The rule is small and load-bearing: it decides every My Profile entity/login-ID read and
write, and a wrong answer either locks the Super Admin out of their own setup or lets a
Finance User edit the GSTIN on every invoice. So the role check is pinned against every
spelling the role column can hold, and the two scopes against the SQL they produce.

The HTTP-level behaviour (403s, 404s, what each member lists) is exercised end to end
against a real database separately; these are the pure parts.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.user import UserRole  # noqa: E402
from app.services.entity_access import (  # noqa: E402
    can_manage_entities, entity_scope, login_scope,
)


def user(role, uid=7):
    return SimpleNamespace(id=uid, role=role)


def sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class TestWhoManages(unittest.TestCase):

    def test_the_super_admin_manages_in_every_spelling(self):
        """The column persists the enum NAME; code paths may hold the member or the value."""
        for role in (UserRole.SUPER_ADMIN, "SUPER_ADMIN", "super_admin"):
            self.assertTrue(can_manage_entities(user(role)), role)

    def test_no_one_else_does(self):
        for role in (UserRole.COMPANY_ADMIN, UserRole.OPERATIONS_USER, UserRole.FINANCE_USER,
                     UserRole.APPROVER, UserRole.VIEWER, UserRole.PLATFORM_ADMIN,
                     "company_admin", "FINANCE_USER"):
            self.assertFalse(can_manage_entities(user(role)), role)


class TestWhatTheySee(unittest.TestCase):

    def test_the_super_admin_sees_their_own_entities(self):
        self.assertEqual(sql(entity_scope(user(UserRole.SUPER_ADMIN))), "user_entities.user_id = 7")

    def test_a_team_member_sees_exactly_their_grants(self):
        s = sql(entity_scope(user(UserRole.FINANCE_USER)))
        self.assertIn("user_entities.id IN", s)
        self.assertIn("user_entity_access.user_id = 7", s)
        self.assertNotIn("user_entities.user_id", s)   # never "entities I happen to own"

    def test_the_super_admin_sees_their_own_login_ids(self):
        self.assertEqual(sql(login_scope(user(UserRole.SUPER_ADMIN))), "user_login_ids.user_id = 7")

    def test_a_team_member_sees_the_login_ids_under_their_grants(self):
        s = sql(login_scope(user(UserRole.COMPANY_ADMIN)))
        self.assertIn("user_login_ids.entity_id IN", s)
        self.assertIn("user_entity_access.user_id = 7", s)


if __name__ == "__main__":
    unittest.main()
