"""The provider-facing half of every AI feature: one client, one call, one salvage.

Lifted verbatim out of ``services/ai_deal_extraction.py`` when a second feature needed the
same three things (see ``services/ai_statement_narration.py``). Nothing here knows about
deals, statements or any other domain — a caller supplies its own system prompt and JSON
schema and gets back the model's raw text.

WHY THIS IS SHARED RATHER THAN COPIED. ``repair_truncated_json`` is a hand-written brace
walker that reads partial JSON out of a response the model ran out of tokens mid-way
through. It is the subtlest code in either feature, it is exercised only on a failure path
that is hard to reproduce deliberately, and a second copy would drift from this one the
first time either was fixed. The retry ladder has the same property: it honours
``retry-after``, treats auth failures as fatal rather than retrying them four times, and
deliberately does NOT let the SDK retry underneath it.

``ai_deal_extraction`` keeps its private names as aliases of these, so that module and its
tests were not touched when this was extracted.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re

logger = logging.getLogger(__name__)


class FatalAIError(Exception):
    """Auth/permission problems — retrying every chunk reaches the same answer three
    minutes later, so fail the whole request at once."""


def build_client():
    """An AsyncOpenAI client that cannot wedge a worker and does not retry behind our back."""
    import httpx
    from openai import AsyncOpenAI
    from app.config import settings

    # The old client had neither a timeout nor a retry override, so one hung TCP
    # connection could wedge a worker indefinitely. max_retries=0 because the ladder in
    # `call_json` is ours; the SDK's silent retries would corrupt attempt accounting and
    # re-spend tokens invisibly.
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=httpx.Timeout(settings.OPENAI_TIMEOUT_SECONDS, connect=10.0),
        max_retries=0,
    )


def is_reasoning_model(model: str | None) -> bool:
    """GPT-5 and the o-series reject `temperature`, `seed` and `max_tokens` on chat
    completions — they take `max_completion_tokens` (which also covers their hidden
    reasoning) and an optional `reasoning_effort` instead."""
    name = (model or "").lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def max_tokens_for(row_count: int, per_row: int, floor: int = 400) -> int:
    """Output ceiling for a chunk of `row_count` rows.

    `max_tokens` is reserved against the org's TPM at ADMISSION, not on completion, so
    over-sizing it costs concurrency on every call whether or not the tokens are used.
    `per_row` is therefore per-feature: a deal object and a parsed narration are not the
    same size.
    """
    return min(16000, floor + per_row * max(row_count, 1))


# ══════════════════════════════════════════════════════════════════════════════
# JSON SALVAGE
# ══════════════════════════════════════════════════════════════════════════════

def repair_truncated_json(content: str, key: str = "rows") -> list[dict]:
    """Extract all complete objects from potentially truncated JSON."""
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*\[', content)
    if match:
        array_content = content[match.end():]
    else:
        bare = re.search(r"\[", content)
        if not bare:
            return []
        array_content = content[bare.end():]

    # Walk through characters to find the boundary of each complete object
    depth = 0
    in_string = False
    escape_next = False
    last_complete_end = -1

    for i, ch in enumerate(array_content):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_complete_end = i

    if last_complete_end == -1:
        return []

    try:
        return json.loads("[" + array_content[: last_complete_end + 1] + "]")
    except json.JSONDecodeError:
        return []


def salvage_or_parse(raw: str, key: str = "rows") -> list[dict]:
    """The rows in a response, whether or not the response is complete JSON."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return repair_truncated_json(raw, key)
    if isinstance(parsed, list):
        return parsed
    rows = parsed.get(key) if isinstance(parsed, dict) else None
    if isinstance(rows, list):
        return rows
    return []


# ══════════════════════════════════════════════════════════════════════════════
# MODEL CALLS
# ══════════════════════════════════════════════════════════════════════════════

async def call_json(client, *, system_prompt: str, user_content: str | list, schema: dict,
                    max_tokens: int, label: str = "ai", row_count: int = 0,
                    strict: bool = True, model: str | None = None,
                    reasoning_effort: str | None = None) -> str:
    """One chat completion returning JSON text, with the retry ladder and the strict fallback.

    Returns the raw string rather than parsed rows: a truncated response is still worth
    salvaging, and only the caller knows what shape it expected.

    `user_content` may be a list of content parts (text and image_url) for a vision read —
    scanned contracts have no text layer. `model` overrides OPENAI_MODEL for one feature;
    a reasoning model gets the parameters it accepts (see `is_reasoning_model`).
    """
    from openai import (
        APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError,
        InternalServerError, PermissionDeniedError, RateLimitError,
    )
    from app.config import settings

    if strict:
        response_format = {"type": "json_schema", "json_schema": schema}
    else:
        response_format = {"type": "json_object"}

    chosen = model or settings.OPENAI_MODEL
    if is_reasoning_model(chosen):
        tuning = {"max_completion_tokens": max_tokens}
        if reasoning_effort:
            tuning["reasoning_effort"] = reasoning_effort
    else:
        tuning = {"temperature": 0, "seed": settings.AI_EXTRACT_SEED, "max_tokens": max_tokens}

    attempt = 0
    while True:
        try:
            # Deliberately chat.completions.create() and not .parse(): .parse() raises
            # LengthFinishReasonError on a truncated response, which would make the
            # salvage path in the caller unreachable.
            response = await client.chat.completions.create(
                model=chosen,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format=response_format,
                **tuning,
            )
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise FatalAIError(str(exc)) from exc
        except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError) as exc:
            attempt += 1
            if attempt >= settings.AI_EXTRACT_MAX_ATTEMPTS:
                logger.warning("%s call giving up after %s attempts: %s", label, attempt, exc)
                raise
            delay = min(2 ** attempt * 2, 60) * random.uniform(0.5, 1.0)
            retry_after = getattr(getattr(exc, "response", None), "headers", {}) or {}
            try:
                delay = max(delay, float(retry_after.get("retry-after", 0)))
            except (TypeError, ValueError):
                pass
            logger.info("retrying %s in %.1fs (attempt %s): %s", label, delay, attempt, exc)
            await asyncio.sleep(delay)
            continue
        except BadRequestError:
            if strict:
                logger.warning("strict schema rejected; retrying %s in json_object mode", label)
                return await call_json(
                    client, system_prompt=system_prompt, user_content=user_content,
                    schema=schema, max_tokens=max_tokens, label=label,
                    row_count=row_count, strict=False, model=model,
                    reasoning_effort=reasoning_effort,
                )
            raise

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        logger.info(
            "%s chunk rows=%s finish=%s completion_tokens=%s max_tokens=%s fingerprint=%s",
            label, row_count, choice.finish_reason, completion_tokens, max_tokens,
            getattr(response, "system_fingerprint", None),
        )
        if completion_tokens and completion_tokens > 0.8 * max_tokens:
            logger.warning(
                "%s chunk used %s of %s output tokens — the per-row token estimate may be "
                "mis-calibrated for this input", label, completion_tokens, max_tokens,
            )
        return choice.message.content or "{}"
