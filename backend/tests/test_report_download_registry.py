"""Report download registry — every statement table has exactly one report source.

No DB. The registry is what the upload listing, the selection check and the builder read
to decide which tables to query and which sheet a type lands on, so the checks here are
the ones whose failure would silently drop or mis-file an upload:

  * every model in STATEMENT_MODELS / ADJUSTMENT_MODELS (plus LCC Detailed and the two BSP
    row tables) is covered, by the model the router itself uses;
  * keys, labels, sheet titles and ranks are unique, and titles are legal Excel sheet names
    that still fit once a split suffix " (N)" is added;
  * the scoping, header and status facts agree with the real model columns;
  * each (category, type) nav pair exists in the frontend's STATEMENT_NAV.

Run:  python -m unittest test_report_download_registry   (from backend/tests)
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.airline_adjustment import ADJUSTMENT_MODELS  # noqa: E402
from app.models.bsp_statement import BspStatementRow  # noqa: E402
from app.models.bsp_summary import BspSummaryRow  # noqa: E402
from app.models.lcc_detailed import LccDetailed  # noqa: E402
from app.models.statement_row import STATEMENT_MODELS  # noqa: E402
from app.services.report_download import columns, registry  # noqa: E402
from app.services.report_download.registry import (  # noqa: E402
    CATEGORY_ORDER, FIXED_SHEETS, SOURCE_BY_KEY, SOURCES, get_source, source_keys,
)

FRONTEND_STATEMENTS_TS = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "src", "lib", "statements.ts",
))

EXPECTED_KEYS = (
    "bsp", "bsp-summary", "adm", "acm", "ra", "tgq-hmpr", "ndc", "lcc-detailed", "lcc-di",
    "lcc-divided-pnr", "lcc-flown-report", "lcc-cta-bta", "tp-gds", "tp-lcc", "tp-api",
)


def _keys_where(predicate):
    return {s.key for s in SOURCES if predicate(s)}


class CoverageTest(unittest.TestCase):
    def test_keys_in_sheet_order(self):
        self.assertEqual(source_keys(), EXPECTED_KEYS)
        self.assertEqual(tuple(SOURCE_BY_KEY), EXPECTED_KEYS)

    def test_every_statement_model_has_its_source(self):
        by_model = {s.model: s for s in SOURCES}
        for slug, model in STATEMENT_MODELS.items():
            with self.subTest(slug=slug):
                self.assertIn(model, by_model)
                self.assertEqual(by_model[model].key, slug)
                self.assertEqual(by_model[model].storage, "spec")

    def test_every_adjustment_model_has_its_source(self):
        by_model = {s.model: s for s in SOURCES}
        for slug, model in ADJUSTMENT_MODELS.items():
            with self.subTest(slug=slug):
                self.assertIn(model, by_model)
                self.assertEqual(by_model[model].key, slug)
                self.assertEqual(by_model[model].storage, "adjustment")

    def test_dedicated_schemas_are_covered(self):
        self.assertIs(get_source("bsp").model, BspStatementRow)
        self.assertIs(get_source("bsp-summary").model, BspSummaryRow)
        self.assertIs(get_source("lcc-detailed").model, LccDetailed)

    def test_each_model_used_once(self):
        models = [s.model for s in SOURCES]
        self.assertEqual(len(models), len(set(models)))

    def test_storage_matches_model_registry(self):
        for s in SOURCES:
            with self.subTest(key=s.key):
                if s.storage == "spec":
                    self.assertIs(STATEMENT_MODELS[s.key], s.model)
                elif s.storage == "adjustment":
                    self.assertIs(ADJUSTMENT_MODELS[s.key], s.model)
                else:
                    self.assertIsNotNone(s.header_model)

    def test_get_source(self):
        self.assertEqual(get_source("tp-api").label, "Third Party API")
        with self.assertRaises(KeyError):
            get_source("lcc-detailed-v2")


class NamingTest(unittest.TestCase):
    def test_unique_keys_labels_titles(self):
        for attr in ("key", "label", "sheet_title"):
            values = [getattr(s, attr) for s in SOURCES]
            with self.subTest(attr=attr):
                self.assertEqual(len(values), len(set(values)))
        titles = [s.sheet_title.lower() for s in SOURCES] + [f.title.lower() for f in FIXED_SHEETS]
        self.assertEqual(len(titles), len(set(titles)))

    def test_titles_are_valid_excel_sheet_names(self):
        for title in [s.sheet_title for s in SOURCES] + [f.title for f in FIXED_SHEETS]:
            with self.subTest(title=title):
                self.assertTrue(title.strip())
                self.assertLessEqual(len(title), 31)
                self.assertIsNone(re.search(r"[\[\]:*?/\\]", title))
                self.assertFalse(title.startswith("'") or title.endswith("'"))
                # a split part "<title> (12)" must not need truncating
                self.assertLessEqual(len(f"{title} (12)"), 31)

    def test_expected_labels_and_titles(self):
        self.assertEqual(
            [s.label for s in SOURCES],
            ["BSP", "BSP Summary", "ADM", "ACM", "RA", "TGQ HMPR", "NDC", "LCC Detailed Statement",
             "LCC DI Statement", "LCC Divided PNR", "LCC Flown Report", "LCC CTA/BTA Report",
             "Third Party GDS", "Third Party LCC", "Third Party API"],
        )
        self.assertEqual(
            [s.sheet_title for s in SOURCES],
            ["BSP Detailed", "BSP Summary", "ADM", "ACM", "RA", "TGQ HMPR", "NDC", "LCC Detailed",
             "LCC DI", "LCC Divided PNR", "LCC Flown Report", "LCC CTA-BTA", "TP GDS", "TP LCC", "TP API"],
        )

    def test_every_source_explains_its_period_fields(self):
        for s in SOURCES:
            with self.subTest(key=s.key):
                self.assertTrue(s.period_fields.strip())


class OrderingTest(unittest.TestCase):
    def test_ranks_unique_contiguous_and_after_fixed_sheets(self):
        self.assertEqual([f.rank for f in FIXED_SHEETS], [1, 2, 3])
        self.assertEqual([s.rank for s in SOURCES], list(range(4, 19)))
        self.assertEqual(
            [f.key for f in FIXED_SHEETS],
            [registry.README_SHEET.key, registry.SUMMARY_SHEET.key, registry.COMBINED_SHEET.key],
        )

    def test_categories_follow_category_order(self):
        self.assertEqual(CATEGORY_ORDER, (columns.CAT_BSP, columns.CAT_LCC, columns.CAT_TP))
        positions = [CATEGORY_ORDER.index(s.category) for s in SOURCES]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual({s.category for s in SOURCES}, set(CATEGORY_ORDER))


class ModelFactsTest(unittest.TestCase):
    def test_batch_attr_exists_and_references_header(self):
        for s in SOURCES:
            with self.subTest(key=s.key):
                column = getattr(s.model, s.batch_attr).property.columns[0]
                if s.header_model is None:
                    for attr in ("source_file", "uploaded_at"):
                        self.assertTrue(hasattr(s.model, attr), attr)
                else:
                    targets = {fk.target_fullname for fk in column.foreign_keys}
                    self.assertEqual(targets, {f"{s.header_model.__tablename__}.batch_id"})

    def test_rows_are_owner_scoped(self):
        # Every row table carries both scope columns, so queries never need a join just to scope.
        for s in SOURCES:
            with self.subTest(key=s.key):
                self.assertTrue(hasattr(s.model, "tenant_id"))
                self.assertTrue(hasattr(s.model, "created_by_id"))
                if s.header_model is not None:
                    self.assertTrue(hasattr(s.header_model, "tenant_id"))
                    self.assertTrue(hasattr(s.header_model, "created_by_id"))

    def test_completed_only_sources_have_a_status_header(self):
        self.assertEqual(_keys_where(lambda s: s.completed_only), {"bsp", "bsp-summary", "lcc-detailed"})
        for s in SOURCES:
            if s.completed_only:
                self.assertTrue(hasattr(s.header_model, "status"), s.key)

    def test_flags(self):
        self.assertEqual(_keys_where(lambda s: not s.feeds_combined), {"bsp-summary"})
        self.assertEqual(_keys_where(lambda s: s.exclude_totals), {"tgq-hmpr", "ndc"})
        for s in SOURCES:
            if s.exclude_totals:
                self.assertTrue(hasattr(s.model, "is_total"), s.key)
        self.assertEqual(
            _keys_where(lambda s: s.schema_unverified), {"lcc-flown-report", "lcc-cta-bta", "tp-lcc"},
        )
        self.assertEqual(
            _keys_where(lambda s: s.sign_mode == "type_signed"),
            {"adm", "acm", "ra", "tgq-hmpr", "ndc", "tp-gds", "tp-lcc", "tp-api"},
        )
        self.assertEqual({s.sign_mode for s in SOURCES}, {"native", "type_signed"})
        self.assertEqual(
            {s.storage for s in SOURCES}, {"bsp", "bsp_summary", "adjustment", "spec", "lcc_detailed"},
        )

    def test_combined_columns_are_unique(self):
        self.assertEqual(len(columns.COMBINED_COLUMNS), 62)
        self.assertEqual(len(set(columns.COMBINED_KEYS)), 62)
        self.assertEqual(len(set(columns.COMBINED_HEADERS)), 62)


def _statement_nav_pairs(ts_source: str) -> set[tuple[str, str]]:
    """(category slug, type slug) pairs out of STATEMENT_NAV's text.

    A category object is ``{ slug, label, types: [ … ] }``; everything up to the next category
    object belongs to it. Type (and variant) slugs inside that span are collected.
    """
    start = ts_source.index("export const STATEMENT_NAV")
    body = ts_source[start:]
    body = body[: body.index("\n];") + 3]
    cat_re = re.compile(r'\{\s*slug:\s*"([\w-]+)",\s*label:\s*"[^"]*",\s*types:\s*\[')
    cats = list(cat_re.finditer(body))
    pairs = set()
    for i, match in enumerate(cats):
        end = cats[i + 1].start() if i + 1 < len(cats) else len(body)
        for type_slug in re.findall(r'slug:\s*"([\w-]+)"', body[match.end():end]):
            pairs.add((match.group(1), type_slug))
    return pairs


class FrontendNavTest(unittest.TestCase):
    def test_nav_pairs_exist_in_statement_nav(self):
        if not os.path.exists(FRONTEND_STATEMENTS_TS):
            self.skipTest("frontend/src/lib/statements.ts not present")
        with open(FRONTEND_STATEMENTS_TS, encoding="utf-8") as fh:
            pairs = _statement_nav_pairs(fh.read())
        self.assertIn(("lcc", "statement-detailed"), pairs)   # the parser itself works
        self.assertNotIn(("bsp", "statement-detailed"), pairs)
        for s in SOURCES:
            with self.subTest(key=s.key):
                self.assertIn(s.nav, pairs)


if __name__ == "__main__":
    unittest.main()
