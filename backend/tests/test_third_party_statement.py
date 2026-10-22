"""Third-party statement uploads have a header row and their lines are linked to it — no DB,
no network.

A Third Party GDS / LCC / API upload is one `third_party_statements` row (who, which file,
when) plus its lines in the type's own table, whose `batch_id` is a foreign key to it. These
pin the link itself, that the migration builds the same table the model describes, that an
upload writes its header before its lines, and that the statements router reads an upload's
own facts off the header rather than off whichever line comes first.

Run:  python -m unittest discover backend/tests
"""
import asyncio
import os
import re
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: E402,F401 — registers every table on Base.metadata
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api.v1 import statements as router  # noqa: E402
from app.database import Base  # noqa: E402
from app.models.statement_row import STATEMENT_MODELS  # noqa: E402
from app.models.third_party_statement import THIRD_PARTY_SLUGS, ThirdPartyStatement  # noqa: E402

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION = VERSIONS / "tp_statements_01_add_statement_header.py"
TALLY_MIGRATION = VERSIONS / "tp_gds_duplicates_01_tally_and_repeats.py"
PERIOD_MIGRATION = VERSIONS / "tp_gds_period_01_statement_period.py"
DATE_FORMATS_MIGRATION = VERSIONS / "tp_gds_date_formats_01_declared_date_formats.py"
USER = SimpleNamespace(id=7, tenant_id=3, full_name="Test User")


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class _Result:
    """An empty result, in every shape the router reads one."""
    rowcount = 0

    def all(self):
        return []

    def first(self):
        return None


class FakeSession:
    """Records what the router adds, flushes and executes, in order."""

    def __init__(self):
        self.log: list[tuple[str, object]] = []

    def add(self, obj):
        self.log.append(("add", obj))

    def add_all(self, objs):
        self.log.append(("add_all", list(objs)))

    async def flush(self):
        self.log.append(("flush", None))

    async def execute(self, stmt):
        self.log.append(("execute", stmt))
        return _Result()


class LinkTests(unittest.TestCase):
    def test_every_third_party_line_table_points_at_the_header(self):
        for slug in THIRD_PARTY_SLUGS:
            with self.subTest(slug=slug):
                col = STATEMENT_MODELS[slug].__table__.c.batch_id
                self.assertEqual(
                    [(fk.target_fullname, fk.ondelete) for fk in col.foreign_keys],
                    [("third_party_statements.batch_id", "CASCADE")],
                )
                self.assertFalse(col.nullable)
                self.assertTrue(col.index)

    def test_no_other_statement_table_gains_the_link(self):
        """MO GDS shares the third-party parser but is the workspace's own record."""
        for slug, model in STATEMENT_MODELS.items():
            if slug in THIRD_PARTY_SLUGS:
                continue
            with self.subTest(slug=slug):
                self.assertEqual(list(model.__table__.c.batch_id.foreign_keys), [])

    def test_header_sorts_before_its_lines(self):
        """tenant_deletion walks sorted_tables in reverse, so lines go before the header."""
        names = [t.name for t in Base.metadata.sorted_tables]
        for slug in THIRD_PARTY_SLUGS:
            with self.subTest(slug=slug):
                self.assertLess(names.index("third_party_statements"),
                                names.index(STATEMENT_MODELS[slug].__tablename__))

    def test_slug_check_names_exactly_the_three_types(self):
        ck = next(c for c in ThirdPartyStatement.__table__.constraints
                  if c.name == "ck_third_party_statements_slug")
        self.assertEqual(set(re.findall(r"'([^']+)'", str(ck.sqltext))), set(THIRD_PARTY_SLUGS))


class MigrationTests(unittest.TestCase):
    src = MIGRATION.read_text(encoding="utf-8")

    def test_chains_onto_an_existing_revision_without_forking(self):
        down = re.search(r"^down_revision[^=]*=\s*'([^']+)'", self.src, re.M).group(1)
        revisions, siblings = set(), []
        for f in VERSIONS.glob("*.py"):
            s = f.read_text(encoding="utf-8")
            r = re.search(r"^revision[^=]*=\s*['\"]([^'\"]+)", s, re.M)
            if r:
                revisions.add(r.group(1))
            d = re.search(r"^down_revision[^=]*=\s*(.+)$", s, re.M)
            if d and f != MIGRATION and f"'{down}'" in d.group(1):
                siblings.append(f.name)
        self.assertIn(down, revisions)
        self.assertEqual(siblings, [], "another migration also revises the same parent")

    def test_creates_every_model_column(self):
        # The header as created here, plus the tally tp_gds_duplicates_01 added to it, the
        # statement period tp_gds_period_01 did and the date formats tp_gds_date_formats_01 did.
        src = (self.src + TALLY_MIGRATION.read_text(encoding="utf-8")
               + PERIOD_MIGRATION.read_text(encoding="utf-8")
               + DATE_FORMATS_MIGRATION.read_text(encoding="utf-8"))
        for col in ThirdPartyStatement.__table__.c:
            with self.subTest(column=col.name):
                self.assertIn(f"sa.Column('{col.name}'", src)

    def test_check_constraint_matches_the_model(self):
        listed = re.search(r'"slug IN \(([^)]*)\)"', self.src).group(1)
        self.assertEqual(set(re.findall(r"'([^']+)'", listed)), set(THIRD_PARTY_SLUGS))

    def test_backfills_and_links_each_line_table_under_its_own_slug(self):
        for slug in THIRD_PARTY_SLUGS:
            table = STATEMENT_MODELS[slug].__tablename__
            with self.subTest(table=table):
                self.assertIn(f"'{table}': '{slug}'", self.src)
        self.assertIn("op.create_foreign_key(", self.src)
        self.assertIn("ondelete='CASCADE'", self.src)


class WriteTests(unittest.TestCase):
    def test_header_is_added_and_flushed_before_the_lines(self):
        db, lines, at = FakeSession(), [object(), object()], datetime(2026, 10, 14, 9, 30)
        asyncio.run(router._write_lines(
            db, "tp-gds", USER, lines, batch_id="b-1", source_file="TRIUMPHH 01-07 AUG.xlsx",
            file_url="statements/3/tp-gds/b-1/TRIUMPHH 01-07 AUG.xlsx", uploaded_at=at))

        self.assertEqual([k for k, _ in db.log], ["add", "flush", "add_all"])
        header = db.log[0][1]
        self.assertIsInstance(header, ThirdPartyStatement)
        self.assertEqual(
            (header.batch_id, header.tenant_id, header.created_by_id, header.slug,
             header.source_file, header.uploaded_at),
            ("b-1", 3, 7, "tp-gds", "TRIUMPHH 01-07 AUG.xlsx", at))
        self.assertEqual(db.log[2][1], lines)

    def test_no_period_stamps_nothing_on_the_lines(self):
        """LCC and API declare no period; their lines are added exactly as given."""
        db, lines = FakeSession(), [object()]
        asyncio.run(router._write_lines(
            db, "tp-lcc", USER, lines, batch_id="b-1", source_file="f.xlsx",
            file_url=None, uploaded_at=datetime(2026, 10, 14)))
        header = db.log[0][1]
        self.assertEqual((header.period_from, header.period_to), (None, None))
        self.assertEqual(db.log[2][1], lines)

    def test_other_types_write_lines_only(self):
        for slug in ("ndc", "tgq-hmpr", "mo-gds"):
            with self.subTest(slug=slug):
                db = FakeSession()
                asyncio.run(router._write_lines(
                    db, slug, USER, [object()], batch_id="b-1", source_file="f.xlsx",
                    file_url=None, uploaded_at=datetime(2026, 10, 14)))
                self.assertEqual([k for k, _ in db.log], ["add_all"])


class ReadTests(unittest.TestCase):
    def test_third_party_upload_facts_come_from_the_header(self):
        for slug in THIRD_PARTY_SLUGS:
            with self.subTest(slug=slug):
                src, conds = router._upload_facts(slug, STATEMENT_MODELS[slug], "b-1", USER)
                self.assertIs(src, ThirdPartyStatement)
                sql = _sql(select(src.source_file).where(*conds))
                self.assertIn("FROM third_party_statements", sql)
                for col in ("batch_id", "slug", "tenant_id", "created_by_id"):
                    self.assertIn(f"third_party_statements.{col} =", sql)

    def test_other_types_still_read_a_line(self):
        model = STATEMENT_MODELS["mo-gds"]
        src, _ = router._upload_facts("mo-gds", model, "b-1", USER)
        self.assertIs(src, model)

    def test_uploads_list_is_one_header_per_upload(self):
        db = FakeSession()
        self.assertEqual(asyncio.run(router.list_batches("tp-gds", db=db, current_user=USER)), [])
        sql = _sql(db.log[0][1])
        self.assertIn("FROM third_party_statements LEFT OUTER JOIN", sql)
        self.assertIn("GROUP BY third_party_gds.batch_id", sql)
        self.assertNotIn("third_party_gds.source_file", sql)
        self.assertIn("third_party_statements.period_from", sql)
        self.assertNotIn("near_match_id", sql)

    def test_other_types_list_stays_a_group_by_over_lines(self):
        db = FakeSession()
        asyncio.run(router.list_batches("mo-gds", db=db, current_user=USER))
        sql = _sql(db.log[0][1])
        self.assertNotIn("third_party_statements", sql)
        self.assertIn("GROUP BY mid_office_gds.batch_id, mid_office_gds.source_file", sql)


if __name__ == "__main__":
    unittest.main()
