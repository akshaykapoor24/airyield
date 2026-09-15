"""The AI narration pass — everything about it except the model call.

The model is stubbed throughout. What is worth testing is not that OpenAI can read a
sentence, but that this module is honest about what came back: the response arrives from
outside the system, it can be truncated mid-object, it bypasses `strict` entirely on the
salvage and json_object paths, and it is merged into a map of the user's own edits. Every
case below is a way that merge could put a value on the wrong row, overwrite a person's
correction, or quietly claim a row was read when it was not.

The scope guard has its own case: the schema is what stops this feature growing into
anomaly detection or summarisation by prompt edit alone.

No network — `_ai.call_json` is replaced.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import ai_client  # noqa: E402
from app.services import ai_statement_narration as narr  # noqa: E402
from app.services import tp_api_spec  # noqa: E402

TRAIN_TEXT = ("Train Name-NZM RAJDHANI Train number- 22221 TravelDate-Aug  2 2026  "
              "From-C SHIVAJI MAH T (CSMT) To-H NIZAMUDDIN (NZM)")


def _row(n, text=TRAIN_TEXT, product="Train"):
    return {"index": n, "text": text, "product_type": product}


def _model_row(n, **fields):
    """One object shaped like the schema — every key present, absent ones null."""
    out = {"n": n, **{f: None for f in tp_api_spec.AI_FILLABLE}}
    out.update(fields)
    return out


def _run(rows, responses):
    """Drive parse_rows with a canned response per chunk.

    `responses` is a list of strings or exceptions, consumed in call order.
    """
    calls = iter(responses)

    async def fake_call_json(client, **kwargs):
        nxt = next(calls)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    with mock.patch.object(narr._ai, "call_json", fake_call_json), \
         mock.patch.object(narr._ai, "build_client", lambda: object()):
        return asyncio.run(narr.parse_rows(rows))


class TestScopeIsEnforcedByTheSchema(unittest.TestCase):
    """The feature is "parse free text into fields" and nothing else. A prompt can be
    weakened by an edit; a closed grammar cannot."""

    def test_the_row_object_is_closed(self):
        item = narr.NARRATION_SCHEMA["schema"]["properties"]["rows"]["items"]
        self.assertFalse(item["additionalProperties"])
        self.assertTrue(narr.NARRATION_SCHEMA["strict"])

    def test_strict_mode_needs_every_property_required(self):
        item = narr.NARRATION_SCHEMA["schema"]["properties"]["rows"]["items"]
        self.assertEqual(set(item["required"]), set(item["properties"]))

    def test_the_only_fields_are_the_specs_allow_list(self):
        item = narr.NARRATION_SCHEMA["schema"]["properties"]["rows"]["items"]
        self.assertEqual(set(item["properties"]) - {"n"}, set(tp_api_spec.AI_FILLABLE))

    def test_there_is_no_room_for_a_finding_or_a_summary(self):
        item = narr.NARRATION_SCHEMA["schema"]["properties"]["rows"]["items"]
        for outside in ("findings", "anomalies", "summary", "confidence", "mapping", "notes"):
            self.assertNotIn(outside, item["properties"])

    def test_every_fillable_field_is_a_real_column(self):
        from app.services import statement_spec as spec
        fields = set(spec.fields("tp-api"))
        for f in tp_api_spec.AI_FILLABLE:
            with self.subTest(field=f):
                self.assertIn(f, fields)


class TestHappyPath(unittest.TestCase):
    def test_a_train_narration_becomes_fields(self):
        resp = json.dumps({"rows": [_model_row(
            0, train_name="NZM RAJDHANI", train_number="22221",
            travel_date="Aug  2 2026",
            origin="C SHIVAJI MAH T", origin_code="CSMT",
            destination="H NIZAMUDDIN", destination_code="NZM",
        )]})
        out = _run([_row(0)], [resp])
        self.assertEqual(out["rows"]["0"], {
            "train_name": "NZM RAJDHANI", "train_number": "22221",
            # Re-parsed here, not by the model: an AI date and a file date must be the same
            # shape in `data` or a period filter silently misses every AI-filled row.
            "travel_date": "2026-08-02",
            "origin": "C SHIVAJI MAH T", "origin_code": "CSMT",
            "destination": "H NIZAMUDDIN", "destination_code": "NZM",
        })
        self.assertEqual(out["parsed_rows"], 1)
        self.assertEqual(out["confidence"], 1.0)
        self.assertIsNone(out["warning"])

    def test_fields_lists_only_what_was_actually_filled(self):
        """It drives which extra columns the review grid reveals — listing a field nothing
        filled would show an empty column."""
        resp = json.dumps({"rows": [_model_row(0, train_name="NZM RAJDHANI")]})
        out = _run([_row(0)], [resp])
        self.assertEqual(out["fields"], ["train_name"])

    def test_fields_keeps_the_specs_column_order(self):
        resp = json.dumps({"rows": [_model_row(
            0, destination="NZM", train_name="X", origin="CSMT")]})
        out = _run([_row(0)], [resp])
        self.assertEqual(out["fields"], ["train_name", "origin", "destination"])

    def test_codes_are_upper_cased_and_whitespace_collapsed(self):
        resp = json.dumps({"rows": [_model_row(
            0, origin_code="csmt", train_name="NZM   RAJDHANI ")]})
        out = _run([_row(0)], [resp])
        self.assertEqual(out["rows"]["0"]["origin_code"], "CSMT")
        self.assertEqual(out["rows"]["0"]["train_name"], "NZM RAJDHANI")

    def test_rows_with_no_narration_are_never_sent(self):
        out = _run([_row(0, text="  "), _row(1, text="")], [])
        self.assertEqual(out["requested_rows"], 0)
        self.assertEqual(out["rows"], {})
        self.assertEqual(out["confidence"], 0.0)


class TestUntrustworthyResponses(unittest.TestCase):
    """Salvaged and json_object-mode objects bypass `strict`, so nothing that arrives can
    be assumed to have the shape it was asked for."""

    def test_a_truncated_response_still_yields_its_complete_objects(self):
        resp = ('{"rows": [' + json.dumps(_model_row(0, train_name="NZM RAJDHANI"))
                + ', ' + json.dumps(_model_row(1, train_name="TEJAS"))
                + ', {"n": 2, "train_name": "PART')
        out = _run([_row(0), _row(1), _row(2)], [resp])
        self.assertEqual(out["rows"]["0"]["train_name"], "NZM RAJDHANI")
        self.assertEqual(out["rows"]["1"]["train_name"], "TEJAS")
        self.assertNotIn("2", out["rows"])
        self.assertEqual(out["parsed_rows"], 2)

    def test_a_row_id_that_was_never_sent_is_dropped(self):
        """A value landing on the wrong line is worse than a blank one."""
        resp = json.dumps({"rows": [_model_row(0, train_name="REAL"),
                                    _model_row(99, train_name="INVENTED")]})
        out = _run([_row(0)], [resp])
        self.assertEqual(list(out["rows"]), ["0"])

    def test_a_duplicated_row_id_keeps_the_first_answer(self):
        resp = json.dumps({"rows": [_model_row(0, train_name="FIRST"),
                                    _model_row(0, train_name="SECOND")]})
        out = _run([_row(0)], [resp])
        self.assertEqual(out["rows"]["0"]["train_name"], "FIRST")

    def test_an_all_null_row_is_omitted_rather_than_emitted_empty(self):
        resp = json.dumps({"rows": [_model_row(0)]})
        out = _run([_row(0)], [resp])
        self.assertEqual(out["rows"], {})
        self.assertEqual(out["parsed_rows"], 0)
        self.assertEqual(out["confidence"], 0.0)

    def test_placeholder_strings_are_treated_as_absent(self):
        """"N/A" and "-" are what a model reaches for when a sentence almost says
        something. Stored, they would overwrite a real cell on the review step."""
        for junk in ("N/A", "n/a", "-", "--", "none", "null", "   "):
            with self.subTest(junk=junk):
                resp = json.dumps({"rows": [_model_row(0, train_name=junk)]})
                self.assertEqual(_run([_row(0)], [resp])["rows"], {})

    def test_a_malformed_object_is_skipped_not_crashed_on(self):
        resp = json.dumps({"rows": ["not an object", {"no_n": 1},
                                    {"n": "0", "train_name": "STR ID"},
                                    _model_row(0, train_name="GOOD")]})
        out = _run([_row(0)], [resp])
        self.assertEqual(out["rows"]["0"]["train_name"], "GOOD")

    def test_an_absurdly_long_value_is_dropped(self):
        """A value far longer than any station name means the model returned the sentence
        rather than the field it was asked for."""
        resp = json.dumps({"rows": [_model_row(0, train_name="X" * 500)]})
        self.assertEqual(_run([_row(0)], [resp])["rows"], {})

    def test_an_unparseable_ai_date_is_dropped_rather_than_stored_raw(self):
        """A date the converter cannot read must not reach `data` as prose — a mapped
        column would never contain one, so a period filter would break on it."""
        resp = json.dumps({"rows": [_model_row(0, travel_date="sometime next month")]})
        self.assertEqual(_run([_row(0)], [resp])["rows"], {})


class TestPartialFailure(unittest.TestCase):
    """A chunk that fails must not fail the request: a user who got 118 of 120 rows filled
    in wants those 118 far more than an error page."""

    def setUp(self):
        # Force one row per chunk so each canned response is its own call.
        p = mock.patch.object(narr, "_chunks", lambda rows: [[r] for r in rows])
        p.start()
        self.addCleanup(p.stop)

    def test_the_rows_that_parsed_are_returned_and_the_rest_are_reported(self):
        ok = json.dumps({"rows": [_model_row(0, train_name="NZM RAJDHANI")]})
        out = _run([_row(0), _row(1)], [ok, RuntimeError("upstream 500")])
        self.assertEqual(out["rows"]["0"]["train_name"], "NZM RAJDHANI")
        self.assertEqual(out["parsed_rows"], 1)
        self.assertEqual(out["requested_rows"], 2)
        self.assertIn("1 of 2 rows could not be read", out["warning"])

    def test_an_auth_failure_is_raised_rather_than_warned_about(self):
        """Every retry reaches the same answer, so it is the whole request's problem —
        the router turns it into one clear message instead of a half-filled grid."""
        with self.assertRaises(ai_client.FatalAIError):
            _run([_row(0), _row(1)],
                 [ai_client.FatalAIError("invalid api key"),
                  json.dumps({"rows": [_model_row(1)]})])


class TestChunking(unittest.TestCase):
    def test_long_narrations_split_on_characters_not_just_row_count(self):
        """The same row count must produce more calls when the text is longer.

        Twenty 40-character narrations and twenty 600-character ones are one chunk by row
        count and a 15x difference by size — and it is the long one that truncates, which
        is the failure the character budget exists to prevent.
        """
        count = 20
        short = narr._chunks([_row(i, text="y" * 40) for i in range(count)])
        long = narr._chunks([_row(i, text="y" * narr.MAX_TEXT_CHARS) for i in range(count)])
        self.assertEqual(len(short), 1)
        self.assertGreater(len(long), len(short))

    def test_a_chunk_never_exceeds_the_row_limit(self):
        from app.config import settings
        rows = [_row(i, text="short") for i in range(settings.AI_EXTRACT_ROWS_PER_CHUNK * 3)]
        for chunk in narr._chunks(rows):
            self.assertLessEqual(len(chunk), settings.AI_EXTRACT_ROWS_PER_CHUNK)

    def test_a_single_oversized_narration_still_gets_its_own_chunk(self):
        """It must not be dropped for not fitting — `parse_rows` caps the text first, and
        the chunker has to emit it either way."""
        self.assertEqual(len(narr._chunks([_row(0, text="y" * 50_000)])), 1)

    def test_every_row_survives_chunking_exactly_once(self):
        rows = [_row(i, text="z" * 300) for i in range(40)]
        flat = [r for c in narr._chunks(rows) for r in c]
        self.assertEqual([r["index"] for r in flat], list(range(40)))

    def test_the_request_is_capped_at_the_previewed_rows(self):
        """The cap matches the wizard's own preview limit, so "the AI covers exactly the
        rows you can see and edit" is true."""
        from app.config import settings
        rows = [_row(i, text="short") for i in range(settings.AI_NARRATION_MAX_ROWS + 25)]
        out = _run(rows, [json.dumps({"rows": []})] * 200)
        self.assertEqual(out["requested_rows"], settings.AI_NARRATION_MAX_ROWS)


if __name__ == "__main__":
    unittest.main()
