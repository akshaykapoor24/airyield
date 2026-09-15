"""Parse a statement's free-text column into the fields a column map cannot reach.

TBO packs a train's entire itinerary into one `NARRATION` cell:

    Train Name-NZM RAJDHANI Train number- 22221 TravelDate-Aug  2 2026
    From-C SHIVAJI MAH T (CSMT) To-H NIZAMUDDIN (NZM)

Everything in there is a field the repository has a column for — `train_name`,
`train_number`, `travel_date`, `origin`, `origin_code`, `destination`, `destination_code` —
and no column mapping can reach inside a sentence to get at them. That is the whole job of
this module, and it is the whole job: this does not detect anomalies, suggest a mapping or
summarise a statement.

THE SCOPE IS ENFORCED BY GRAMMAR, NOT BY THE PROMPT. The response schema is generated from
`tp_api_spec.AI_FILLABLE` with `additionalProperties: false` and a closed, fixed property
list, so the model cannot return a field outside that set even if a future prompt edit asked
it to. A sentence in a prompt is a request; a schema is a constraint.

PYTHON OWNS EVERY CONVERSION. The model copies text out of a sentence and nothing else —
dates are re-parsed here through the same `to_iso_date` the mapped columns go through,
codes are upper-cased here, lengths are capped here, and nulls are dropped here. That split
is the one `ai_deal_extraction` already uses, and the reason is that a model asked to also
normalise will occasionally normalise inventively, whereas `re` will not.

NOTHING HERE WRITES TO THE DATABASE. The result is merged into the upload wizard's existing
per-cell edit map, so a value the AI proposes is reviewed and editable exactly like a value
the user typed, and `/confirm` needs no knowledge that an AI was involved.
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.services import ai_client as _ai
from app.services import tp_api_spec as _tpapi

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 600      # a narration far longer than this is not a narration
MAX_VALUE_CHARS = 120     # a parsed field far longer than this is a mis-read sentence


SYSTEM_PROMPT = """You read one free-text booking description per line and copy the facts \
already written in it into fixed fields. You are a parser, not an analyst.

You are given numbered lines. Each line has an id `n`, a `product` hint (Hotel, Flight, \
Train, Bus, Car or blank) and the raw `text`. Return one object per line, with the same `n`.

RULES
1. COPY, NEVER INFER. Every value must be text that literally appears in the line. If the \
line does not state a fact, return null for it. Do not guess a station code from a station \
name, an airline from a flight number, or a year that is not written.
2. Return null — not "", not "N/A", not "-" — for anything absent.
3. Strip the label, keep the value. "Train number- 22221" is `train_number` "22221". \
"Train Name-NZM RAJDHANI" is `train_name` "NZM RAJDHANI".
4. A parenthesised code after a place name is that place's code, and the name is the name \
without it. "From-C SHIVAJI MAH T (CSMT)" is `origin` "C SHIVAJI MAH T" and `origin_code` \
"CSMT". If there is no parenthesised code, `origin_code` is null.
5. Dates: copy them as they are written ("Aug  2 2026"). Do not reformat, do not reorder, \
do not add a year. The caller converts them.
6. `origin`/`destination` are the journey's endpoints whatever the product: stations for a \
train, cities or airports for a flight, boarding and dropping points for a bus, pickup and \
drop for a car, and for a hotel the city it is in as `destination` with `origin` null.
7. `airline_property_name` is the operator or property named in the line — the train's \
operator is NOT one, so leave it null for a train unless the line names a separate operator.
8. If a line is empty, is not a booking description, or you cannot read it, return the \
object with `n` and every other field null. Never drop a line and never renumber."""


def _schema() -> dict:
    """A closed object per line, generated from the spec's own allow-list.

    `additionalProperties: false` plus `required` naming every key is what `strict` mode
    needs, and it is also what makes the scope non-negotiable: there is no key in this
    grammar for a finding, a suggestion or a summary.
    """
    props: dict = {"n": {"type": "integer"}}
    for field in _tpapi.AI_FILLABLE:
        props[field] = {"type": ["string", "null"]}
    return {
        "name": "narration_fields",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["rows"],
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(props),
                        "properties": props,
                    },
                },
            },
        },
    }


NARRATION_SCHEMA = _schema()


def _chunks(rows: list[dict]) -> list[list[dict]]:
    """Split into calls by BOTH row count and character budget.

    Row count alone is not enough: thirty 40-character narrations and thirty 400-character
    ones are the same chunk by one measure and a 10x difference by the other, and it is the
    long one that truncates.
    """
    from app.config import settings

    per_chunk = max(1, settings.AI_EXTRACT_ROWS_PER_CHUNK)
    max_chars = max(500, settings.AI_EXTRACT_CHUNK_MAX_CHARS)

    out: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for r in rows:
        n = len(r["text"]) + 40   # the id and product hint travel with it
        if cur and (len(cur) >= per_chunk or size + n > max_chars):
            out.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += n
    if cur:
        out.append(cur)
    return out


def _render(chunk: list[dict]) -> str:
    return json.dumps(
        [{"n": r["index"], "product": r.get("product_type") or "", "text": r["text"]}
         for r in chunk],
        ensure_ascii=False,
    )


def _clean_value(field: str, raw) -> str | None:
    """One model-returned value → what actually goes on the row, or None to drop it."""
    if raw is None:
        return None
    s = " ".join(str(raw).split())
    # The model is told to use null, but "N/A" and "-" are what a model reaches for when a
    # sentence almost says something. Treating them as values would overwrite a real cell
    # with a placeholder on the review step.
    if not s or s.lower() in {"n/a", "na", "null", "none", "-", "--"}:
        return None
    if len(s) > MAX_VALUE_CHARS:
        return None
    cfg = _tpapi.AI_NARRATION
    if field in cfg["date_fields"]:
        # Re-parsed through exactly the converter the mapped date columns use, so an AI
        # date and a file date are the same shape in `data` — otherwise a period filter
        # would silently miss every AI-filled row.
        return _tpapi.to_iso_date(s)
    if field in cfg["upper_fields"]:
        return s.upper()
    return s


async def _one_chunk(client, chunk: list[dict]) -> list[dict]:
    from app.config import settings

    raw = await _ai.call_json(
        client,
        system_prompt=SYSTEM_PROMPT,
        user_content=_render(chunk),
        schema=NARRATION_SCHEMA,
        max_tokens=_ai.max_tokens_for(len(chunk), settings.AI_NARRATION_OUT_TOK_PER_ROW),
        label="ai-narration",
        row_count=len(chunk),
    )
    return _ai.salvage_or_parse(raw)


async def parse_rows(rows: list[dict]) -> dict:
    """[{index, text, product_type}] → the fields the AI could read out of each line.

    `rows` are the wizard's own preview rows, so `index` is its `__index__` and the result
    keys back onto the same row without any position arithmetic.

    A chunk that fails does NOT fail the request: the rows that parsed are returned and the
    rest are reported in `warning`, because a user who got 118 of 120 rows filled in wants
    those 118 far more than they want an error page.
    """
    from app.config import settings

    usable = [r for r in rows if (r.get("text") or "").strip()][:settings.AI_NARRATION_MAX_ROWS]
    requested = len(usable)
    if not requested:
        return {"fields": [], "rows": {}, "requested_rows": 0, "parsed_rows": 0,
                "confidence": 0.0, "warning": None}

    for r in usable:
        r["text"] = r["text"][:MAX_TEXT_CHARS]

    chunks = _chunks(usable)
    client = _ai.build_client()
    sem = asyncio.Semaphore(max(1, settings.AI_EXTRACT_MAX_CONCURRENCY))

    async def run(chunk):
        async with sem:
            return await _one_chunk(client, chunk)

    results = await asyncio.gather(*(run(c) for c in chunks), return_exceptions=True)

    wanted = {r["index"] for r in usable}
    out: dict[int, dict] = {}
    filled_fields: set[str] = set()
    failed_chunks = 0

    for chunk, res in zip(chunks, results):
        if isinstance(res, _ai.FatalAIError):
            raise res
        if isinstance(res, BaseException):
            failed_chunks += 1
            logger.warning("narration chunk failed: %s", res)
            continue
        for obj in res:
            if not isinstance(obj, dict) or not isinstance(obj.get("n"), int):
                continue    # salvaged and json_object-mode objects bypass `strict`
            n = obj["n"]
            # A row id the model invented, or echoed twice. Neither is trusted: the first
            # answer for a real row wins and everything else is dropped, because a value
            # landing on the wrong line is worse than a blank one.
            if n not in wanted or n in out:
                continue
            vals = {}
            for field in _tpapi.AI_FILLABLE:
                v = _clean_value(field, obj.get(field))
                if v is not None:
                    vals[field] = v
            if vals:
                out[n] = vals
                filled_fields.update(vals)

    parsed = len(out)
    warning = None
    if failed_chunks:
        missing = requested - sum(len(c) for c, r in zip(chunks, results)
                                  if not isinstance(r, BaseException))
        warning = (f"{missing} of {requested} rows could not be read — they are unchanged, "
                   f"so fill them in by hand or press AI Analysis again.")

    return {
        # The union actually filled, so the review grid knows which extra columns to show.
        "fields": [f for f in _tpapi.AI_FILLABLE if f in filled_fields],
        "rows": {str(k): v for k, v in out.items()},
        "requested_rows": requested,
        "parsed_rows": parsed,
        "confidence": round(parsed / requested, 3) if requested else 0.0,
        "warning": warning,
    }
