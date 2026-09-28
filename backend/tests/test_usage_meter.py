"""Per-workspace cost metering: what gets recorded, when, against whom, and what it costs.

The failure modes this guards are the quiet ones: an OpenAI call or an upload that is
never recorded (the console under-bills), one recorded twice, a price that falls through
to the wrong model, an unknown model reading as free, and a unit test that writes a
ledger row into whatever database DATABASE_URL points at.

No DB, no network: usage_meter._execute — the one function that writes — is replaced.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.services import ai_client, ai_pricing, file_store, gcs, tenant_resources, usage_meter  # noqa: E402


def _params(stmt) -> dict:
    return stmt.compile(dialect=postgresql.dialect()).params


class _Recorder:
    """Stands in for usage_meter._execute and keeps what would have been written."""

    def __init__(self):
        self.statements = []

    async def __call__(self, stmt, what):
        self.statements.append(stmt)

    @property
    def params(self) -> list[dict]:
        return [_params(s) for s in self.statements]


class _MeterTest(unittest.TestCase):
    def setUp(self):
        self.rec = _Recorder()
        patcher = mock.patch.object(usage_meter, "_execute", self.rec)
        patcher.start()
        self.addCleanup(patcher.stop)


# ── pricing ──────────────────────────────────────────────────────────────────

class TestPricing(unittest.TestCase):
    def test_the_two_models_this_app_pins_are_priced(self):
        self.assertEqual(ai_pricing.price_for(settings.OPENAI_MODEL), (2.50, 1.25, 10.00))
        self.assertEqual(ai_pricing.price_for(settings.SERIES_AI_MODEL), (5.00, 0.50, 30.00))

    def test_longest_prefix_wins(self):
        """gpt-4o-mini must never be billed at gpt-4o's rate, nor gpt-5-mini at gpt-5's."""
        self.assertEqual(ai_pricing.price_for("gpt-4o-mini-2024-07-18"), (0.15, 0.075, 0.60))
        self.assertEqual(ai_pricing.price_for("gpt-5-mini-2025-08-07"), (0.25, 0.025, 2.00))
        self.assertEqual(ai_pricing.price_for("gpt-5-2025-08-07"), (1.25, 0.125, 10.00))

    def test_a_dotted_version_is_not_its_parent(self):
        """gpt-5.5 is not gpt-5 with a suffix; a bare startswith() would say it was."""
        self.assertEqual(ai_pricing.price_for("gpt-5.5-2026-04-23")[2], 30.00)

    def test_an_unknown_model_is_unpriced_not_free(self):
        self.assertIsNone(ai_pricing.price_for("o9-preview"))
        self.assertIsNone(ai_pricing.cost_usd("o9-preview", 1000, 0, 1000))
        self.assertIsNone(ai_pricing.price_for(""))

    def test_cached_tokens_are_a_subset_of_prompt_tokens(self):
        # 1M prompt of which 400k cached, 100k output on gpt-4o:
        # 600k × 2.50 + 400k × 1.25 + 100k × 10.00 = 1.50 + 0.50 + 1.00
        self.assertAlmostEqual(
            ai_pricing.cost_usd("gpt-4o-2024-08-06", 1_000_000, 400_000, 100_000), 3.00)

    def test_env_override_wins_and_adds_models(self):
        with mock.patch.object(settings, "AI_MODEL_PRICES", {"gpt-4o": [1, 1, 1], "o9": [2, 2, 2]}):
            self.assertEqual(ai_pricing.price_for("gpt-4o-2024-08-06"), (1.0, 1.0, 1.0))
            self.assertEqual(ai_pricing.price_for("o9-preview"), (2.0, 2.0, 2.0))

    def test_a_malformed_override_is_ignored(self):
        with mock.patch.object(settings, "AI_MODEL_PRICES", {"gpt-4o": [1, 2]}):
            self.assertEqual(ai_pricing.price_for("gpt-4o"), (2.50, 1.25, 10.00))


# ── classification ───────────────────────────────────────────────────────────

class TestClassify(unittest.TestCase):
    def test_uploads_by_first_segment(self):
        self.assertEqual(usage_meter.classify("bsp/4/uuid/apr.pdf"), ("bsp", "upload"))
        self.assertEqual(usage_meter.classify("statements/4/ndc/b/x.xlsx"), ("statements", "upload"))

    def test_generated_objects(self):
        self.assertEqual(usage_meter.classify("reports/7/5/42-key/r.xlsx"), ("reports", "generated"))
        self.assertEqual(
            usage_meter.classify("lcc-detailed/4/b/account/a.csv._preview.xlsx"),
            ("lcc-detailed", "generated"))

    def test_tenant_from_path(self):
        self.assertEqual(usage_meter.tenant_from_path("deals/12/batch/f.pdf"), 12)
        self.assertIsNone(usage_meter.tenant_from_path("series/0/9/c.pdf"))   # "no tenant"
        self.assertIsNone(usage_meter.tenant_from_path("logos"))
        self.assertIsNone(usage_meter.tenant_from_path("misc/abc/f"))


# ── scope ────────────────────────────────────────────────────────────────────

class TestScope(_MeterTest):
    def test_nothing_is_recorded_outside_a_scope(self):
        """The guarantee that keeps every other test in this suite off the database."""
        asyncio.run(usage_meter.record_ai_call(feature="ai-extract", model="gpt-4o", usage=None))
        asyncio.run(usage_meter.record_object_stored(
            storage="gcs", bucket="b", object_name="bsp/1/x.pdf", size_bytes=10, content_type=None))
        asyncio.run(usage_meter.record_object_deleted(storage="gcs", bucket="b", object_name="bsp/1/x.pdf"))
        self.assertEqual(self.rec.statements, [])

    def test_the_kill_switch(self):
        async def run():
            with usage_meter.scope(1, 2), mock.patch.object(settings, "USAGE_METERING_ENABLED", False):
                await usage_meter.record_ai_call(feature="ai-extract", model="gpt-4o", usage=None)
        asyncio.run(run())
        self.assertEqual(self.rec.statements, [])

    def test_concurrent_requests_do_not_share_a_scope(self):
        """Each request is its own task; one's workspace must never bill the other's call."""
        async def request(tenant, user, delay):
            usage_meter.enter_scope(tenant, user)
            await asyncio.sleep(delay)
            await usage_meter.record_ai_call(feature=f"t{tenant}", model="gpt-4o", usage=None)

        async def run():
            await asyncio.gather(request(1, 10, 0.02), request(2, 20, 0.0))
        asyncio.run(run())
        by_feature = {p["feature"]: p["user_id"] for p in self.rec.params}
        self.assertEqual(by_feature, {"t1": 10, "t2": 20})

    def test_gathered_chunks_inherit_the_request_scope(self):
        """Deal extraction fans chunks out with asyncio.gather; each must still be billed."""
        async def run():
            usage_meter.enter_scope(3, 30)
            await asyncio.gather(*[
                usage_meter.record_ai_call(feature="ai-extract", model="gpt-4o", usage=None)
                for _ in range(4)
            ])
        asyncio.run(run())
        self.assertEqual([p["user_id"] for p in self.rec.params], [30] * 4)

    def test_a_bounded_scope_is_reset(self):
        with usage_meter.scope(1, 2):
            self.assertEqual(usage_meter.current_scope(), usage_meter.UsageScope(1, 2))
        self.assertIsNone(usage_meter.current_scope())


class TestNeverRaises(unittest.TestCase):
    def test_a_failing_write_is_swallowed(self):
        """A metering failure must never fail the upload or AI call it was recording."""
        broken = mock.MagicMock()
        broken.begin.side_effect = RuntimeError("relation ai_usage_events does not exist")

        async def run():
            with usage_meter.scope(1, 2), mock.patch.object(usage_meter, "_get_engine", return_value=broken):
                await usage_meter.record_ai_call(feature="ai-extract", model="gpt-4o", usage=None)
        with self.assertLogs(usage_meter.logger, level="WARNING"):
            asyncio.run(run())


# ── what is recorded ─────────────────────────────────────────────────────────

class TestRecordAiCall(_MeterTest):
    def test_tokens_including_cached_and_reasoning(self):
        usage = SimpleNamespace(
            prompt_tokens=1200, completion_tokens=800,
            prompt_tokens_details=SimpleNamespace(cached_tokens=1024),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=500),
        )

        async def run():
            with usage_meter.scope(5, 6):
                await usage_meter.record_ai_call(
                    feature="series-extract", model="gpt-5.5-2026-04-23", usage=usage, duration_ms=91000)
        asyncio.run(run())
        (p,) = self.rec.params
        self.assertEqual(
            {k: p[k] for k in ("user_id", "feature", "model", "prompt_tokens", "cached_prompt_tokens",
                               "completion_tokens", "reasoning_tokens", "duration_ms")},
            {"user_id": 6, "feature": "series-extract", "model": "gpt-5.5-2026-04-23",
             "prompt_tokens": 1200, "cached_prompt_tokens": 1024, "completion_tokens": 800,
             "reasoning_tokens": 500, "duration_ms": 91000})
        self.assertIn(5, p.values())   # the tenant, inside its FK-safe subquery

    def test_a_mock_usage_reads_as_zero_tokens(self):
        async def run():
            with usage_meter.scope(1, 1):
                await usage_meter.record_ai_call(feature="ai", model="gpt-4o", usage=mock.MagicMock())
        asyncio.run(run())
        self.assertEqual(self.rec.params[0]["prompt_tokens"], 0)


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _response(model="gpt-4o-2024-08-06", prompt=100, completion=50):
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"rows": []}'))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                              prompt_tokens_details=None, completion_tokens_details=None),
        system_fingerprint=None,
    )


class TestCallJsonIsMetered(_MeterTest):
    def _call(self, completions, **kw):
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        async def run():
            with usage_meter.scope(9, 99):
                return await ai_client.call_json(
                    client, system_prompt="s", user_content="u", schema={"name": "x", "schema": {}},
                    max_tokens=1000, label="ai-narration", **kw)
        return asyncio.run(run())

    def test_one_completion_one_row_with_the_served_model(self):
        self._call(_FakeCompletions([_response(model="gpt-4o-2024-08-06")]), model="gpt-4o")
        (p,) = self.rec.params
        self.assertEqual((p["feature"], p["model"], p["prompt_tokens"], p["completion_tokens"]),
                         ("ai-narration", "gpt-4o-2024-08-06", 100, 50))

    def test_a_retried_rate_limit_is_not_billed(self):
        """Only the completion that came back is a row; the 429 before it cost nothing."""
        from openai import RateLimitError

        err = RateLimitError("slow down", response=mock.MagicMock(status_code=429, headers={}), body=None)
        with mock.patch.object(ai_client.asyncio, "sleep", mock.AsyncMock()):
            self._call(_FakeCompletions([err, _response()]))
        self.assertEqual(len(self.rec.statements), 1)

    def test_the_strict_fallback_is_billed_once(self):
        from openai import BadRequestError

        err = BadRequestError("schema", response=mock.MagicMock(status_code=400), body=None)
        self._call(_FakeCompletions([err, _response()]))
        self.assertEqual(len(self.rec.statements), 1)


class TestStorageHooks(_MeterTest):
    def test_gcs_upload_records_size_and_location(self):
        bucket = mock.MagicMock()

        async def run():
            with usage_meter.scope(4, 40), mock.patch.object(gcs, "_bucket", return_value=bucket):
                await gcs.upload_bytes(b"x" * 2048, "bsp/4/u/apr.pdf", "application/pdf", "bsp-bucket")
        asyncio.run(run())
        (p,) = self.rec.params
        self.assertEqual(
            {k: p[k] for k in ("storage", "bucket", "object_name", "source", "origin", "size_bytes", "user_id")},
            {"storage": "gcs", "bucket": "bsp-bucket", "object_name": "bsp/4/u/apr.pdf", "source": "bsp",
             "origin": "upload", "size_bytes": 2048, "user_id": 40})

    def test_a_failed_upload_records_nothing(self):
        bucket = mock.MagicMock()
        bucket.blob.return_value.upload_from_string.side_effect = RuntimeError("billing disabled")

        async def run():
            with usage_meter.scope(4, 40), mock.patch.object(gcs, "_bucket", return_value=bucket):
                await gcs.upload_bytes(b"x", "bsp/4/u/apr.pdf", "application/pdf", "bsp-bucket")
        with self.assertRaises(RuntimeError):
            asyncio.run(run())
        self.assertEqual(self.rec.statements, [])

    def test_gcs_delete_marks_deleted_only_when_the_object_is_gone(self):
        from google.api_core.exceptions import NotFound

        for side_effect, expected in ((None, 1), (NotFound("gone"), 1), (RuntimeError("403"), 0)):
            with self.subTest(side_effect=side_effect):
                self.rec.statements.clear()
                bucket = mock.MagicMock()
                bucket.blob.return_value.delete.side_effect = side_effect

                async def run():
                    with usage_meter.scope(None, None), mock.patch.object(gcs, "_bucket", return_value=bucket):
                        await gcs.delete_blob("bsp/4/u/apr.pdf", "bsp-bucket")
                asyncio.run(run())
                self.assertEqual(len(self.rec.statements), expected)

    def test_local_fallback_is_recorded_once_as_local(self):
        """GCS fails, the file lands on disk: one row, storage=local — not one per branch."""
        with tempfile.TemporaryDirectory() as tmp:
            async def run():
                with usage_meter.scope(4, 40), \
                        mock.patch.object(gcs, "_bucket", side_effect=RuntimeError("no network")):
                    locator, remote = await file_store.store(
                        b"abc", "bsp/4/u/apr.pdf", "application/pdf", "bsp-bucket", local_root=Path(tmp))
                    await file_store.delete(locator, "bsp-bucket", local_root=Path(tmp))
                    return locator, remote
            with self.assertLogs(gcs.logger, level="ERROR"):
                locator, remote = asyncio.run(run())
        self.assertFalse(remote)
        stored, deleted = self.rec.params
        self.assertEqual((stored["storage"], stored["bucket"], stored["object_name"], stored["size_bytes"]),
                         ("local", "", "bsp/4/u/apr.pdf", 3))
        self.assertIn("bsp/4/u/apr.pdf", deleted.values())


# ── read side ────────────────────────────────────────────────────────────────

class TestAiSummary(unittest.TestCase):
    def test_unpriced_calls_are_counted_not_zeroed(self):
        t = tenant_resources._Tally()
        t.add("gpt-4o-2024-08-06", 2, 1_000_000, 0, 0)     # $2.50
        t.add("o9-preview", 3, 1_000_000, 0, 1_000_000)     # unknown price
        self.assertEqual((t.calls, t.unpriced_calls), (5, 3))
        self.assertAlmostEqual(t.cost, 2.50)

    def test_members_beyond_the_panel_fold_into_one_line(self):
        members = {}
        for uid in range(8):
            members[uid] = tenant_resources._Tally(calls=1, cost=float(uid))
        out = tenant_resources._ai_summary(
            tenant_resources._Tally(), tenant_resources._Tally(), {}, members, {})
        self.assertEqual(len(out["by_member"]), 6)
        self.assertEqual(out["by_member"][0]["label"], "User #7")          # most expensive first
        self.assertEqual(out["by_member"][-1]["label"], "3 others")
        self.assertAlmostEqual(out["by_member"][-1]["cost_usd"], 0 + 1 + 2)


class TestFootprint(unittest.TestCase):
    def test_bytes_split_by_row_share_and_null_tenant_stays_with_the_platform(self):
        anchors = {"deals": "deals", "deal_rules": "deals", "gst": "gst"}
        sizes = {"deals": 1000, "deal_rules": 400, "gst": 300}
        rows = {"deals": {1: 3, 2: 1}, "gst": {None: 9, 1: 1}}
        out = tenant_resources.attribute(anchors, sizes, rows, lambda name: name)
        self.assertEqual(out[1], {"deals": 750, "deal_rules": 300, "gst": 30})
        self.assertEqual(out[2], {"deals": 250, "deal_rules": 100})
        self.assertNotIn(None, out)

    def test_an_empty_or_unmeasured_table_attributes_nothing(self):
        out = tenant_resources.attribute({"a": "a", "b": "b"}, {"a": 0, "b": 50}, {"a": {1: 5}}, str)
        self.assertEqual(out, {})

    def test_child_tables_resolve_to_a_tenant_scoped_ancestor(self):
        tenant_resources._load_all_models()
        tables = Base.metadata.tables
        self.assertEqual(tenant_resources._anchor("deal_incentive_slab_values", tables), "deals")
        self.assertEqual(tenant_resources._anchor("bsp_parse_errors", tables), "bsp_statements")
        self.assertEqual(tenant_resources._anchor("deals", tables), "deals")
        self.assertIsNone(tenant_resources._anchor("airlines", tables))    # global master

    def test_every_table_is_either_attributed_or_global(self):
        """A table the footprint cannot place would silently read as platform overhead."""
        tenant_resources._load_all_models()
        tables = Base.metadata.tables
        # Global masters, plus the platform's own invoices to workspaces (not theirs).
        global_masters = {"airlines", "airports", "routes", "airline_class_masters", "suppliers", "tenants",
                          "platform_invoices"}
        unplaced = sorted(n for n in tables if n not in global_masters
                          and tenant_resources._anchor(n, tables) is None)
        self.assertEqual(unplaced, [])


class TestFileUsageShape(unittest.TestCase):
    def test_every_upload_path_kind_has_a_label(self):
        """Blob names built in the routers must classify to a labelled source."""
        for name in ("bsp/1/b/f.pdf", "bsp-summary/1/b/f.pdf", "deals/1/b/f.pdf", "tickets/1/b/f.xls",
                     "customer-statements/1/b/f.xls", "statements/1/ndc/b/f.xlsx",
                     "lcc-detailed/1/b/role/f.csv", "adjustments/1/adm/b/f.xlsx",
                     "series/1/9/c.pdf", "logos/1/abc.png", "reports/1/2/3-k/r.xlsx"):
            with self.subTest(name=name):
                self.assertIn(usage_meter.classify(name)[0], tenant_resources.SOURCE_LABELS)


if __name__ == "__main__":
    unittest.main()
