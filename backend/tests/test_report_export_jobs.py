"""Report download job rules that must not drift: liveness, storage naming, request limits,
download-link binding and the worker's claim fence.

Pinned here because each one is a quiet failure in production rather than a crash:
  * a queued report that ever reads "stalled" invites a Retry that double-queues it;
  * a blob path without the random storage key makes report files guessable;
  * a local report root under UPLOAD_DIR publishes every passenger name via /uploads;
  * a file token not bound to the owner can be replayed against someone else's row;
  * a claim whose NOT EXISTS does not correlate lets one workspace run parallel builds.

No DB, no network: SQL is compiled, not executed; DB calls are faked where a function needs one.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_export_jobs -v   (from backend/tests)
"""
import asyncio
import logging
import os
import secrets
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

import app.models  # noqa: F401,E402
from app.config import settings  # noqa: E402
from app.models.report_export import STATUSES, ReportExport  # noqa: E402
from app.schemas.report_download import (  # noqa: E402
    MAX_INCLUDED_UPLOADS, MAX_TITLE_LENGTH, MAX_UNTICKED_UPLOADS, ExportCreate,
    normalize_source_types,
)
from app.services import file_store  # noqa: E402
from app.services.report_download import jobs, storage  # noqa: E402
from app.utils.security import create_file_token, verify_file_token  # noqa: E402

NOW = datetime(2026, 9, 15, 12, 0, 0)


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class DisplayStatusTests(unittest.TestCase):
    def test_queued_waits_while_a_worker_keeps_touching_it(self):
        # A queued row is stamped at creation/retry and on every busy-workspace re-queue.
        for hb in (None, NOW, NOW - timedelta(minutes=5), NOW - jobs.QUEUED_STUCK_AFTER):
            self.assertEqual(jobs.display_status("queued", hb, NOW), "waiting")

    def test_queued_untouched_past_the_threshold_is_stalled(self):
        # Its Celery message was lost (broker restart / no reports worker): offer Retry and
        # stop it holding a cap slot, instead of "Waiting" forever.
        hb = NOW - jobs.QUEUED_STUCK_AFTER - timedelta(seconds=1)
        self.assertEqual(jobs.display_status("queued", hb, NOW), "stalled")
        self.assertTrue(jobs.is_stuck_queued(hb, NOW))
        self.assertFalse(jobs.is_stuck_queued(None, NOW))

    def test_processing_with_fresh_heartbeat_is_generating(self):
        self.assertEqual(jobs.display_status("processing", NOW - timedelta(seconds=30), NOW), "generating")

    def test_processing_exactly_at_the_threshold_is_still_generating(self):
        self.assertEqual(jobs.display_status("processing", NOW - jobs.STALE_AFTER, NOW), "generating")

    def test_processing_past_ten_minutes_is_stalled(self):
        self.assertEqual(jobs.STALE_AFTER, timedelta(minutes=10))
        self.assertEqual(
            jobs.display_status("processing", NOW - timedelta(minutes=10, seconds=1), NOW), "stalled")

    def test_processing_without_heartbeat_is_stalled(self):
        self.assertEqual(jobs.display_status("processing", None, NOW), "stalled")

    def test_completed_is_ready_until_it_expires(self):
        self.assertEqual(jobs.display_status("completed", None, NOW), "ready")
        self.assertEqual(jobs.display_status("completed", None, NOW, NOW + timedelta(days=1)), "ready")
        self.assertEqual(jobs.display_status("completed", None, NOW, NOW), "expired")
        self.assertEqual(jobs.display_status("completed", None, NOW, NOW - timedelta(seconds=1)), "expired")

    def test_terminal_states(self):
        self.assertEqual(jobs.display_status("failed", None, NOW), "failed")
        self.assertEqual(jobs.display_status("expired", None, NOW), "expired")
        self.assertEqual(jobs.display_status("deleted", None, NOW), "expired")

    def test_every_model_status_maps_to_a_chip(self):
        chips = {"waiting", "generating", "stalled", "ready", "failed", "expired"}
        for s in STATUSES:
            self.assertIn(jobs.display_status(s, NOW, NOW), chips)

    def test_sql_liveness_uses_the_same_threshold(self):
        threshold = (NOW - jobs.STALE_AFTER).isoformat(sep=" ")
        active = _sql(jobs.active_clause(NOW))
        stale = _sql(jobs.stale_processing_clause(NOW))
        self.assertIn(f"heartbeat_at >= '{threshold}'", active)
        self.assertIn(f"heartbeat_at < '{threshold}'", stale)
        self.assertIn("heartbeat_at IS NULL", stale)
        self.assertIn("'queued'", active)
        self.assertNotIn("'queued'", stale)


class StorageNamingTests(unittest.TestCase):
    def _row(self, **kw):
        base = dict(id=42, tenant_id=7, created_by_id=3, storage_key="k" * 32,
                    file_name="airyield-report-20260701-20260731-r42.xlsx")
        base.update(kw)
        return SimpleNamespace(**base)

    def test_blob_name_embeds_the_storage_key(self):
        key = secrets.token_urlsafe(24)
        row = self._row(storage_key=key)
        self.assertEqual(
            storage.blob_name(row),
            f"reports/7/3/42-{key}/airyield-report-20260701-20260731-r42.xlsx",
        )

    def test_blob_name_is_deterministic_for_the_row(self):
        self.assertEqual(storage.blob_name(self._row()), storage.blob_name(self._row()))
        self.assertNotEqual(storage.blob_name(self._row()), storage.blob_name(self._row(storage_key="x" * 32)))

    def test_blob_name_needs_a_file_name(self):
        with self.assertRaises(ValueError):
            storage.blob_name(self._row(file_name=None))

    def test_storage_key_fits_its_column(self):
        self.assertLessEqual(len(secrets.token_urlsafe(24)), ReportExport.__table__.c.storage_key.type.length)

    def test_export_file_name_is_ascii_and_carries_no_user_text(self):
        name = storage.export_file_name(42, date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(name, "airyield-report-20260701-20260731-r42.xlsx")
        self.assertTrue(name.isascii())

    def test_local_root_is_not_under_the_public_upload_dir(self):
        root = storage.local_root()
        public = file_store._root().resolve()
        self.assertTrue(root.is_absolute())
        self.assertNotEqual(root, public)
        self.assertNotIn(public, root.parents)

    def test_local_root_refuses_a_directory_inside_uploads(self):
        inside = str(file_store._root() / "reports")
        with mock.patch.object(settings, "REPORTS_LOCAL_DIR", inside):
            with self.assertRaises(RuntimeError):
                storage.local_root()

    def test_bucket_falls_back_bsp_then_tickets(self):
        with mock.patch.multiple(settings, GCS_REPORTS_BUCKET_NAME="", GCS_BSP_BUCKET_NAME="",
                                 GCS_TICKETS_BUCKET_NAME="tickets"):
            self.assertEqual(storage.reports_bucket(), "tickets")
        with mock.patch.multiple(settings, GCS_REPORTS_BUCKET_NAME="", GCS_BSP_BUCKET_NAME="bsp",
                                 GCS_TICKETS_BUCKET_NAME="tickets"):
            self.assertEqual(storage.reports_bucket(), "bsp")
        with mock.patch.multiple(settings, GCS_REPORTS_BUCKET_NAME="reports", GCS_BSP_BUCKET_NAME="bsp"):
            self.assertEqual(storage.reports_bucket(), "reports")


class ContentDispositionTests(unittest.TestCase):
    def test_plain_ascii_name(self):
        self.assertEqual(
            storage.content_disposition("report-r1.xlsx"),
            "attachment; filename=\"report-r1.xlsx\"; filename*=UTF-8''report-r1.xlsx",
        )

    def test_non_ascii_gets_an_ascii_fallback_and_rfc5987_form(self):
        header = storage.content_disposition("rapport-é₹.xlsx")
        fallback = header.split(";")[1].strip()
        self.assertEqual(fallback, 'filename="rapport-__.xlsx"')
        self.assertTrue(header.isascii())
        self.assertIn("filename*=UTF-8''rapport-%C3%A9%E2%82%B9.xlsx", header)

    def test_quotes_and_backslashes_cannot_break_the_header(self):
        header = storage.content_disposition('a"b\\c.xlsx')
        self.assertIn('filename="a_b_c.xlsx"', header)
        self.assertIn("filename*=UTF-8''a%22b%5Cc.xlsx", header)


def _payload(**kw):
    base = {
        "date_from": "2026-07-01",
        "date_to": "2026-07-31",
        "source_types": ["bsp", "tgq-hmpr"],
        "included_uploads": [{"source_type": "bsp", "upload_id": "b1"}],
    }
    base.update(kw)
    return base


class ExportCreateSchemaTests(unittest.TestCase):
    def test_minimal_payload_gets_documented_defaults(self):
        req = ExportCreate(**_payload())
        self.assertEqual(req.basis, "transaction")
        self.assertEqual(req.bsp_scope, "whole_statement")
        self.assertTrue(req.options.include_detail_sheets)
        self.assertFalse(req.options.include_pii)
        self.assertEqual(req.options.undated_rows, "include")
        self.assertEqual(req.unticked_uploads, [])
        self.assertIsNone(req.title)

    def test_unknown_source_type_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            ExportCreate(**_payload(source_types=["bsp", "not-a-source"]))
        self.assertIn("not-a-source", str(ctx.exception))

    def test_title_limit(self):
        ExportCreate(**_payload(title="t" * MAX_TITLE_LENGTH))
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(title="t" * (MAX_TITLE_LENGTH + 1)))
        self.assertEqual(MAX_TITLE_LENGTH, 200)

    def test_blank_title_is_none(self):
        self.assertIsNone(ExportCreate(**_payload(title="   ")).title)
        self.assertEqual(ExportCreate(**_payload(title="  July  ")).title, "July")

    def test_included_upload_limits(self):
        self.assertEqual(MAX_INCLUDED_UPLOADS, 500)
        many = [{"source_type": "bsp", "upload_id": f"b{i}"} for i in range(MAX_INCLUDED_UPLOADS)]
        self.assertEqual(len(ExportCreate(**_payload(included_uploads=many)).included_uploads), 500)
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(included_uploads=many + [{"source_type": "bsp", "upload_id": "extra"}]))
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(included_uploads=[]))

    def test_unticked_upload_limit(self):
        too_many = [{"source_type": "bsp", "upload_id": f"u{i}"} for i in range(MAX_UNTICKED_UPLOADS + 1)]
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(unticked_uploads=too_many))

    def test_period_must_be_ordered_and_bounded(self):
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(date_from="2026-08-01", date_to="2026-07-01"))
        start = date(2025, 1, 1)
        ok_end = start + timedelta(days=settings.REPORT_EXPORT_MAX_PERIOD_DAYS - 1)
        ExportCreate(**_payload(date_from=start.isoformat(), date_to=ok_end.isoformat()))
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(date_from=start.isoformat(),
                                    date_to=(ok_end + timedelta(days=1)).isoformat()))

    def test_upload_must_belong_to_a_selected_type(self):
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(included_uploads=[{"source_type": "ndc", "upload_id": "n1"}]))

    def test_upload_cannot_be_both_included_and_unticked(self):
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(unticked_uploads=[{"source_type": "bsp", "upload_id": "b1"}]))

    def test_duplicates_are_collapsed(self):
        req = ExportCreate(**_payload(
            source_types=["bsp", "bsp", " tgq-hmpr "],
            included_uploads=[{"source_type": "bsp", "upload_id": "b1"},
                              {"source_type": "bsp", "upload_id": "b1"}],
        ))
        self.assertEqual(req.source_types, ["bsp", "tgq-hmpr"])
        self.assertEqual(len(req.included_uploads), 1)

    def test_bad_enums_are_rejected(self):
        for field, value in (("basis", "booking"), ("bsp_scope", "rows")):
            with self.assertRaises(ValidationError):
                ExportCreate(**_payload(**{field: value}))
        with self.assertRaises(ValidationError):
            ExportCreate(**_payload(options={"undated_rows": "drop"}))

    def test_normalize_source_types_for_the_query_string(self):
        self.assertEqual(normalize_source_types("ndc, bsp,,ndc".split(",")), ["ndc", "bsp"])
        with self.assertRaises(ValueError):
            normalize_source_types([" ", ""])


class FileTokenTests(unittest.TestCase):
    def test_subject_includes_the_owner(self):
        self.assertEqual(jobs.file_token_subject(42, 3), "report_export:42:3")

    def test_token_for_one_owner_does_not_open_another_owners_row(self):
        token = create_file_token(jobs.file_token_subject(42, 3), jobs.FILE_TOKEN_KIND, 10)
        self.assertTrue(verify_file_token(token, jobs.file_token_subject(42, 3), jobs.FILE_TOKEN_KIND))
        self.assertFalse(verify_file_token(token, jobs.file_token_subject(42, 4), jobs.FILE_TOKEN_KIND))
        self.assertFalse(verify_file_token(token, jobs.file_token_subject(43, 3), jobs.FILE_TOKEN_KIND))
        self.assertFalse(verify_file_token(token, jobs.file_token_subject(42, 3), "bsp_detail"))


def _export(**kw):
    base = dict(id=42, created_by_id=3, status="completed", file_locator="local://reports/7/3/42-k/r.xlsx",
                storage_bucket="", expires_at=jobs.utcnow() + timedelta(days=1),
                file_name="airyield-report-20260701-20260731-r42.xlsx")
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeDB:
    def __init__(self, row):
        self.row = row

    async def scalar(self, _stmt):
        return self.row


class DownloadTests(unittest.TestCase):
    STREAM = "http://testserver/api/v1/report-download/exports/42/file"

    def _status_of(self, coro) -> int:
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(coro)
        return ctx.exception.status_code

    def test_local_report_gets_an_owner_bound_token_link(self):
        url = asyncio.run(jobs.download_url(_export(), self.STREAM))
        self.assertTrue(url.startswith(self.STREAM + "?token="))
        token = url.split("?token=", 1)[1]
        self.assertTrue(verify_file_token(token, "report_export:42:3", "report_export"))

    def test_not_ready_is_409_and_expired_is_410(self):
        self.assertEqual(self._status_of(jobs.download_url(_export(status="processing", file_locator=None), self.STREAM)), 409)
        self.assertEqual(self._status_of(jobs.download_url(_export(status="expired", file_locator=None), self.STREAM)), 410)
        past = jobs.utcnow() - timedelta(seconds=1)
        self.assertEqual(self._status_of(jobs.download_url(_export(expires_at=past), self.STREAM)), 410)

    def test_stream_refuses_bad_tokens_and_missing_rows_alike(self):
        good = create_file_token("report_export:42:3", "report_export", 10)
        other_owner = create_file_token("report_export:42:9", "report_export", 10)
        self.assertEqual(self._status_of(jobs.open_local_file(_FakeDB(None), 42, good)), 403)
        self.assertEqual(self._status_of(jobs.open_local_file(_FakeDB(_export()), 42, other_owner)), 403)
        self.assertEqual(self._status_of(jobs.open_local_file(_FakeDB(_export(status="deleted")), 42, good)), 403)

    def test_stream_serves_only_an_existing_local_completed_file(self):
        good = create_file_token("report_export:42:3", "report_export", 10)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(storage, "local_root", return_value=Path(tmp)):
                # file not there yet
                self.assertEqual(self._status_of(jobs.open_local_file(_FakeDB(_export()), 42, good)), 404)
                target = Path(tmp) / "reports/7/3/42-k/r.xlsx"
                target.parent.mkdir(parents=True)
                target.write_bytes(b"xlsx")
                path, name = asyncio.run(jobs.open_local_file(_FakeDB(_export()), 42, good))
                self.assertEqual(path, target.resolve())
                self.assertEqual(name, "airyield-report-20260701-20260731-r42.xlsx")
                remote = _export(file_locator="reports/7/3/42-k/r.xlsx", storage_bucket="b")
                self.assertEqual(self._status_of(jobs.open_local_file(_FakeDB(remote), 42, good)), 404)


class ClaimStatementTests(unittest.TestCase):
    def test_claim_is_fenced_and_one_build_per_workspace(self):
        from app.workers.report_tasks import claim_statement

        sql = _sql(claim_statement(42, "task-1", NOW))
        self.assertIn("attempt=(report_exports.attempt + 1)", sql)
        self.assertIn("report_exports.status = 'queued' OR report_exports.status = 'processing'", sql)
        # The NOT EXISTS must correlate to the row being claimed, not scan a second copy.
        self.assertIn("NOT (EXISTS (SELECT", sql)
        self.assertIn("report_exports_1.tenant_id = report_exports.tenant_id", sql)
        self.assertIn("report_exports_1.id != 42", sql)
        self.assertIn("RETURNING report_exports.attempt", sql)


# ── worker control flow, with the DB and the builder faked ───────────────────

class _FakeConn:
    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def close(self):
        return None

    def in_transaction(self):
        return False


class _FakeEngine:
    async def connect(self):
        return _FakeConn()

    async def dispose(self):
        return None


def _fake_build_modules(behaviour):
    """Stand-ins for selection.py / builder.py with the contract's names and shapes."""
    import types
    from dataclasses import dataclass

    builder = types.ModuleType("fake_builder")
    selection = types.ModuleType("fake_selection")

    class ReportCancelled(Exception):
        pass

    class ReportTimeout(Exception):
        pass

    @dataclass
    class BuildState:
        processed: int = 0
        stage: str = ""
        cancelled: bool = False
        deadline: float = 0.0

        def tick(self, n: int = 0, stage=None):
            self.processed += n
            if stage:
                self.stage = stage
            if self.cancelled:
                raise ReportCancelled()

    class Workbook:
        def __init__(self, path):
            self.path = path
            self.discarded = False

        def save(self):
            Path(self.path).write_bytes(b"PK xlsx")

        def discard(self):
            self.discarded = True

    async def build_report(conn, sel, params, meta, path, state):
        builder.calls.append((sel, params, meta, path))
        builder.tempdir_during_build = tempfile.gettempdir()
        return behaviour(builder, path, state)

    class SelectionError(ValueError):
        pass

    async def resolve_selection(conn, tenant_id, user_id, included, unticked=()):
        selection.calls.append((tenant_id, user_id, list(included), list(unticked)))
        return SimpleNamespace(uploads=(), unticked=())

    builder.ReportCancelled, builder.ReportTimeout = ReportCancelled, ReportTimeout
    builder.BuildState, builder.Workbook, builder.build_report = BuildState, Workbook, build_report
    builder.calls = []
    selection.SelectionError, selection.resolve_selection, selection.calls = SelectionError, resolve_selection, []
    return builder, selection


def _ok(builder, path, state):
    state.tick(100, "Writing")
    return SimpleNamespace(workbook=builder.Workbook(path), sheet_row_counts={"combined": 100},
                           summary={"rows": 100}, combined_rows=100, files_included=[], files_excluded=[])


class WorkerFlowTests(unittest.TestCase):
    def setUp(self):
        from app.workers import report_tasks as rt
        self.rt = rt
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "report_files"
        self.claim = rt._Claim(
            id=42, attempt=3, tenant_id=7, created_by_id=5,
            params={"date_from": "2026-07-01", "date_to": "2026-07-31", "basis": "transaction",
                    "bsp_scope": "whole_statement", "source_types": ["bsp"],
                    "options": {"include_detail_sheets": True, "include_pii": False, "undated_rows": "include"}},
            selection={"included": [{"source_type": "bsp", "upload_id": "b1"}],
                       "unticked": [{"source_type": "tgq-hmpr", "upload_id": "t1"}]},
            storage_key="key", title="July", estimated_rows=10,
        )
        # The failure paths log full tracebacks on purpose; keep the test output readable.
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._tmp.cleanup()

    def _run(self, behaviour, *, claim="default", owner="default", finalize=True, store_error=None):
        import app.services.report_download as pkg

        rt = self.rt
        builder, selection = _fake_build_modules(behaviour)
        claim = self.claim if claim == "default" else claim
        owner = rt._Owner("Asha", "asha@example.com", "Acme") if owner == "default" else owner
        store = mock.AsyncMock(
            side_effect=store_error,
            return_value=("local://reports/7/5/42-key/airyield-report-20260701-20260731-r42.xlsx", False))

        async def idle_heartbeat(*_args):
            await asyncio.Event().wait()

        self.fail_mock = mock.AsyncMock()
        self.finalize_mock = mock.AsyncMock(return_value=finalize)
        self.delete_mock = mock.AsyncMock()
        self.requeue_mock = mock.AsyncMock()
        saved_tempdir = tempfile.tempdir
        with mock.patch.dict(sys.modules, {"app.services.report_download.builder": builder,
                                           "app.services.report_download.selection": selection}), \
                mock.patch.object(pkg, "builder", builder, create=True), \
                mock.patch.object(pkg, "selection", selection, create=True), \
                mock.patch.object(rt, "_new_engine", return_value=_FakeEngine()), \
                mock.patch.object(rt, "_housekeeping", mock.AsyncMock()), \
                mock.patch.object(rt, "_claim", mock.AsyncMock(return_value=claim)), \
                mock.patch.object(rt, "_requeue_if_waiting", self.requeue_mock), \
                mock.patch.object(rt, "_active_owner", mock.AsyncMock(return_value=owner)), \
                mock.patch.object(rt, "_heartbeat", idle_heartbeat), \
                mock.patch.object(rt, "_fail", self.fail_mock), \
                mock.patch.object(rt, "_finalize", self.finalize_mock), \
                mock.patch.object(file_store, "store_path", store), \
                mock.patch.object(file_store, "delete", self.delete_mock), \
                mock.patch.object(storage, "local_root", return_value=self.root), \
                mock.patch.object(storage, "reports_bucket", return_value=""):
            state = rt._RunState()
            asyncio.run(rt._run(42, "task-9", state))
        self.assertEqual(tempfile.tempdir, saved_tempdir, "tempfile.tempdir is restored")
        return builder, selection, store, state

    def _fail_codes(self):
        return [c.args[2] for c in self.fail_mock.await_args_list]

    def test_success_builds_in_a_private_temp_dir_stores_and_finalizes(self):
        builder, selection, store, state = self._run(_ok)
        self.assertEqual(state.attempt, 3)
        self.assertEqual(selection.calls, [(7, 5, [("bsp", "b1")], [("tgq-hmpr", "t1")])])
        _sel, params, meta, path = builder.calls[0]
        self.assertEqual(params, self.claim.params)
        self.assertEqual((meta.export_id, meta.title, meta.generated_by_email), (42, "July", "asha@example.com"))
        self.assertTrue(os.path.basename(builder.tempdir_during_build).startswith("ayreport-42-"))
        self.assertFalse(os.path.exists(builder.tempdir_during_build), "temp dir removed")
        store.assert_awaited_once()
        self.assertEqual(store.await_args.args[1],
                         "reports/7/5/42-key/airyield-report-20260701-20260731-r42.xlsx")
        self.assertEqual(store.await_args.kwargs["local_root"], self.root)
        self.finalize_mock.assert_awaited_once()
        self.assertEqual(self.finalize_mock.await_args.kwargs["file_size"], len(b"PK xlsx"))
        self.delete_mock.assert_not_awaited()
        self.fail_mock.assert_not_awaited()

    def test_losing_the_finalize_fence_deletes_the_stored_file(self):
        self._run(_ok, finalize=False)
        self.delete_mock.assert_awaited_once()
        self.assertTrue(self.delete_mock.await_args.args[0].startswith("local://reports/7/5/42-key/"))
        self.fail_mock.assert_not_awaited()

    def test_cancellation_writes_nothing(self):
        def cancelled(builder, path, state):
            raise builder.ReportCancelled()
        self._run(cancelled)
        self.fail_mock.assert_not_awaited()
        self.finalize_mock.assert_not_awaited()

    def test_timeout_fails_with_timeout_for_this_attempt(self):
        def slow(builder, path, state):
            raise builder.ReportTimeout()
        self._run(slow)
        self.assertEqual(self._fail_codes(), ["TIMEOUT"])
        self.assertEqual(self.fail_mock.await_args.args[:2], (42, 3))

    def test_unexpected_error_fails_with_a_safe_reference_message(self):
        def broken(builder, path, state):
            raise KeyError("data->>'secret_column'")
        self._run(broken)
        self.assertEqual(self._fail_codes(), ["BUILD_ERROR"])
        message = self.fail_mock.await_args.args[3]
        self.assertIn("Reference #42", message)
        self.assertNotIn("secret_column", message)

    def test_storage_failure_is_storage_error(self):
        self._run(_ok, store_error=OSError("disk full"))
        self.assertEqual(self._fail_codes(), ["STORAGE_ERROR"])
        self.finalize_mock.assert_not_awaited()

    def test_inactive_account_fails_before_building(self):
        builder, _sel, _store, _state = self._run(_ok, owner=None)
        self.assertEqual(self._fail_codes(), ["ACCOUNT_INACTIVE"])
        self.assertEqual(builder.calls, [])

    def test_nothing_claimed_hands_off_to_requeue(self):
        builder, _sel, _store, state = self._run(_ok, claim=None)
        self.requeue_mock.assert_awaited_once()
        self.assertIsNone(state.attempt)
        self.assertEqual(builder.calls, [])
        self.fail_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
