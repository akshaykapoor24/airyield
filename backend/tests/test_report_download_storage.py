"""file_store's report-download additions: a caller-chosen local root and streaming stores.

What is pinned:
  * ``store_path`` without a bucket MOVES the build output under the given local root and
    hands back a ``local://`` locator that ``load`` / ``local_path`` / ``delete`` resolve under
    the SAME root — never under UPLOAD_DIR, which main.py serves publicly;
  * a GCS failure falls back to that local root (same contract as ``store``), and a GCS
    success leaves the local file for the caller's temp-dir cleanup;
  * locators cannot climb out of the root, and a GCS locator has no local path;
  * callers that pass no root keep today's UPLOAD_DIR behaviour.

No DB, no network: GCS is patched.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_download_storage -v   (from backend/tests)
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import file_store, gcs  # noqa: E402

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class StorePathLocalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.build_dir = base / "build"
        self.root = base / "report_files"
        self.build_dir.mkdir()
        self.source = self.build_dir / "r42.xlsx"
        self.source.write_bytes(b"PK\x03\x04 workbook bytes")

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip_without_a_bucket(self):
        locator, remote = asyncio.run(file_store.store_path(
            self.source, "reports/7/3/42-key/r42.xlsx", XLSX, "", local_root=self.root))

        self.assertFalse(remote)
        self.assertEqual(locator, "local://reports/7/3/42-key/r42.xlsx")
        self.assertFalse(self.source.exists(), "the build output is moved, not copied")

        path = file_store.local_path(locator, self.root)
        self.assertEqual(path, (self.root / "reports/7/3/42-key/r42.xlsx").resolve())
        self.assertTrue(path.is_file())
        self.assertEqual(
            asyncio.run(file_store.load(locator, "", local_root=self.root)),
            b"PK\x03\x04 workbook bytes",
        )

        asyncio.run(file_store.delete(locator, "", local_root=self.root))
        self.assertFalse(path.exists())
        # Deleting again is a no-op, never an error.
        asyncio.run(file_store.delete(locator, "", local_root=self.root))

    def test_load_of_a_missing_local_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            asyncio.run(file_store.load("local://reports/none.xlsx", "", local_root=self.root))

    def test_gcs_failure_falls_back_to_the_local_root(self):
        with mock.patch.object(gcs, "upload_file", mock.AsyncMock(side_effect=RuntimeError("billing disabled"))):
            locator, remote = asyncio.run(file_store.store_path(
                self.source, "reports/1/2/3-k/r.xlsx", XLSX, "a-bucket", local_root=self.root))
        self.assertFalse(remote)
        self.assertTrue(file_store.local_path(locator, self.root).is_file())

    def test_gcs_success_streams_the_file_and_leaves_it_for_cleanup(self):
        upload = mock.AsyncMock(return_value="reports/1/2/3-k/r.xlsx")
        with mock.patch.object(gcs, "upload_file", upload):
            locator, remote = asyncio.run(file_store.store_path(
                self.source, "reports/1/2/3-k/r.xlsx", XLSX, "a-bucket", local_root=self.root))
        self.assertTrue(remote)
        self.assertEqual(locator, "reports/1/2/3-k/r.xlsx")
        upload.assert_awaited_once_with(str(self.source), "reports/1/2/3-k/r.xlsx", XLSX, "a-bucket")
        self.assertTrue(self.source.exists())
        self.assertFalse(self.root.exists(), "nothing is written locally after a remote store")

    def test_blob_name_is_sanitised_the_same_way_as_store(self):
        locator, _ = asyncio.run(file_store.store_path(
            self.source, "reports//7/../3/r<1>.xlsx", XLSX, "", local_root=self.root))
        self.assertEqual(locator, "local://reports/7/3/r_1_.xlsx")


class LocalPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "report_files"

    def tearDown(self):
        self._tmp.cleanup()

    def test_traversal_segments_cannot_leave_the_root(self):
        for locator in ("local://../../outside.xlsx", "local://..\\..\\outside.xlsx",
                        "local://reports/../../../x.xlsx"):
            path = file_store.local_path(locator, self.root)
            self.assertIn(self.root.resolve(), path.parents, locator)

    def test_a_path_outside_the_root_is_refused(self):
        outside = (Path(self._tmp.name) / "elsewhere").resolve()
        with mock.patch.object(file_store, "_sanitize", return_value=str(outside)):
            with self.assertRaises(ValueError):
                file_store.local_path("local://anything", self.root)

    def test_a_gcs_locator_has_no_local_path(self):
        with self.assertRaises(ValueError):
            file_store.local_path("reports/7/3/42-k/r.xlsx", self.root)

    def test_without_a_root_the_upload_dir_is_used_as_before(self):
        path = file_store.local_path("local://bsp/4/u/apr.pdf")
        self.assertIn(file_store._root().resolve(), path.parents)


if __name__ == "__main__":
    unittest.main()
