"""What an OpenAI call cost, from the tokens ai_usage_events recorded.

Applied at READ time, not stored on the row: a wrong price here is corrected for every past
call the moment it is fixed. Re-pricing history with today's table is right for this app
because it pins dated snapshots (gpt-4o-2024-08-06, gpt-5.5-2026-04-23), and OpenAI does not
reprice a snapshot after release.

USD per 1M tokens, standard tier, as (input, cached_input, output). Checked against
https://developers.openai.com/api/docs/pricing on 2026-09-28. Output includes reasoning
tokens — OpenAI bills hidden reasoning as output, and completion_tokens already counts it.

A model with no entry is reported as UNPRICED, never as $0: an unknown cost that reads as
free is the one mistake a cost column must not make. Add it to AI_MODEL_PRICES in .env
(see app/config.py) and the console picks it up without a deploy.
"""
from __future__ import annotations

from app.config import settings

# Keys match a model id exactly or as a prefix; the longest match wins, so "gpt-4o-mini"
# never falls through to "gpt-4o" and "gpt-5-mini" never to "gpt-5".
_BUILT_IN: dict[str, tuple[float, float, float]] = {
    "gpt-5.5":      (5.00, 0.50, 30.00),   # SERIES_AI_MODEL
    "gpt-5":        (1.25, 0.125, 10.00),
    "gpt-5-mini":   (0.25, 0.025, 2.00),
    "gpt-4.1":      (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4o":       (2.50, 1.25, 10.00),   # OPENAI_MODEL (gpt-4o-2024-08-06)
    "gpt-4o-mini":  (0.15, 0.075, 0.60),
}


def _table() -> dict[str, tuple[float, float, float]]:
    table = dict(_BUILT_IN)
    for key, value in (settings.AI_MODEL_PRICES or {}).items():
        if isinstance(value, (list, tuple)) and len(value) == 3:
            table[key.strip().lower()] = (float(value[0]), float(value[1]), float(value[2]))
    return table


def price_for(model: str | None) -> tuple[float, float, float] | None:
    name = (model or "").strip().lower()
    if not name:
        return None
    table = _table()
    if name in table:
        return table[name]
    # A snapshot id extends its family's name with a dash: gpt-4o-2024-08-06, gpt-5.5-2026-….
    matches = [k for k in table if name.startswith(k + "-")]
    return table[max(matches, key=len)] if matches else None


def cost_usd(model: str | None, prompt_tokens: int, cached_prompt_tokens: int,
             completion_tokens: int) -> float | None:
    """Dollars for these tokens on this model, or None when the model has no price.

    cached_prompt_tokens is a SUBSET of prompt_tokens (that is how the API reports it), so
    only the uncached remainder is charged at the full input rate.
    """
    price = price_for(model)
    if price is None:
        return None
    input_rate, cached_rate, output_rate = price
    cached = min(max(cached_prompt_tokens, 0), max(prompt_tokens, 0))
    uncached = max(prompt_tokens, 0) - cached
    return (uncached * input_rate + cached * cached_rate + max(completion_tokens, 0) * output_rate) / 1_000_000
