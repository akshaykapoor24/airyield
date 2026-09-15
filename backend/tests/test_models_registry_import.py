"""report_exports is registered everywhere a table has to be.

``tenant_deletion.GROUP_REQUIREMENTS`` is computed from ``Base.metadata`` at import time, and
alembic/env.py builds its target metadata from ``from app.models import *``. A model that is
not imported through app.models is invisible to both — the deletion registry would crash on an
unknown table, and autogenerate would propose dropping the live one. This file fails first.

It also keeps the hand-written migration and the model from drifting apart column by column.

No DB, no network.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_models_registry_import -v   (from backend/tests)
"""
import importlib
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

MIGRATION = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
             / "report_exports_01_add_report_exports.py")


class ModelsRegistryTests(unittest.TestCase):
    def test_app_models_registers_report_exports(self):
        import app.models
        from app.database import Base

        self.assertIn("report_exports", Base.metadata.tables)
        self.assertIn("ReportExport", app.models.__all__)

    def test_star_import_used_by_alembic_env_exposes_the_model(self):
        namespace: dict = {}
        exec("from app.models import *", namespace)  # noqa: S102 — mirrors alembic/env.py
        self.assertIn("ReportExport", namespace)

    def test_tenant_deletion_imports_and_owns_the_table(self):
        tenant_deletion = importlib.import_module("app.services.tenant_deletion")

        group = tenant_deletion.GROUPS_BY_KEY["reports"]
        self.assertEqual(group.tables, ("report_exports",))
        self.assertEqual(group.category, tenant_deletion.GroupCategory.RECORDS)
        # created_by_id has no ON DELETE, so deleting users must take reports with it.
        self.assertIn("reports", tenant_deletion.GROUP_REQUIREMENTS["users"])
        self.assertIn("reports", tenant_deletion.GROUP_REQUIREMENTS["workspace"])

    def test_tenant_usage_excludes_the_table(self):
        from app.services.tenant_usage import EXCLUDED_TABLES, USAGE_SOURCES

        self.assertIn("report_exports", EXCLUDED_TABLES)
        self.assertNotIn("report_exports", {s.model.__tablename__ for s in USAGE_SOURCES})

    def test_status_check_constraint_and_indexes(self):
        import app.models  # noqa: F401
        from app.database import Base
        from app.models.report_export import STATUSES

        table = Base.metadata.tables["report_exports"]
        checks = {c.name: str(c.sqltext) for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}
        self.assertIn("ck_report_exports_status", checks)
        for s in STATUSES:
            self.assertIn(f"'{s}'", checks["ck_report_exports_status"])
        self.assertTrue({
            "ix_report_exports_owner_created", "ix_report_exports_status_heartbeat",
            "ix_report_exports_status_expires",
        } <= {i.name for i in table.indexes})


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.text = MIGRATION.read_text(encoding="utf-8")

    def test_revision_chain(self):
        self.assertIsNotNone(re.search(r"^revision: str = 'report_exports_01'$", self.text, re.M))
        down = re.search(r"^down_revision: [^=]+= '([^']+)'$", self.text, re.M).group(1)
        self.assertEqual(down, "lcc_pax_01")
        revisions = set()
        for p in MIGRATION.parent.glob("*.py"):
            m = re.search(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]",
                          p.read_text(encoding="utf-8", errors="replace"), re.M)
            if m:
                revisions.add(m.group(1))
        self.assertIn(down, revisions)

    def test_migration_columns_match_the_model(self):
        import app.models  # noqa: F401
        from app.database import Base

        migrated = set(re.findall(r"sa\.Column\('([a-z_]+)'", self.text))
        self.assertEqual(migrated, set(Base.metadata.tables["report_exports"].c.keys()))

    def test_bsp_indexes_are_concurrent_and_guarded(self):
        self.assertIn("autocommit_block()", self.text)
        self.assertIn("indisvalid", self.text)
        for name in ("ix_bsp_rows_owner_document", "ix_bsp_rows_owner_rtdn"):
            self.assertIn(name, self.text)
        self.assertIn("postgresql_concurrently=True, if_not_exists=True", self.text)
        self.assertIn("postgresql_concurrently=True, if_exists=True", self.text)


if __name__ == "__main__":
    unittest.main()
