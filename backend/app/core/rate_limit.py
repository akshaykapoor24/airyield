"""Fixed-window rate limiting for the auth endpoints, backed by Redis.

No new dependency: redis is already installed for Celery and REDIS_URL is already
configured. The async client is used deliberately — a sync one would block the
event loop on every authenticated request.

FAIL-OPEN. If Redis is unreachable, requests are allowed and a warning is logged
once per 30s. Auth must not hard-break because a cache is down; the honest
trade-off is that throttling silently stops during an outage. The circuit
breaker is what makes that safe: without it a dead Redis costs 250ms on every
auth request, which is the difference between "degrades gracefully" and "the
login page is broken".

Emails are hashed into keys so Redis never stores plaintext addresses.

On the limits themselves: per-IP does the real work, but a distributed attacker
defeats it, so per-email is the backstop. Per-email login limiting counts only
FAILURES and is cleared on success — otherwise an attacker could lock a victim
out of their own account just by submitting wrong passwords. It is deliberately
the more generous of the two for the same reason.
"""
import hashlib
import logging
import time
from typing import Optional

from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)

# How long to stop trying after a Redis failure, and the per-attempt timeout.
_BREAKER_SECONDS = 30.0
_TIMEOUT_SECONDS = 0.25

_disabled_until = 0.0
_client = None


async def _redis():
    """The shared async client, or None while the breaker is open."""
    global _client, _disabled_until
    if time.monotonic() < _disabled_until:
        return None
    if _client is None:
        try:
            import redis.asyncio as aioredis
            _client = aioredis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=_TIMEOUT_SECONDS,
                socket_timeout=_TIMEOUT_SECONDS,
                decode_responses=True,
            )
        except Exception as exc:
            _trip(exc)
            return None
    return _client


def _trip(exc: Exception) -> None:
    global _disabled_until, _client
    if time.monotonic() >= _disabled_until:
        logger.warning(
            "[rate_limit] Redis unavailable (%s) — rate limiting is OFF for %ds.",
            exc, int(_BREAKER_SECONDS),
        )
    _disabled_until = time.monotonic() + _BREAKER_SECONDS
    _client = None


def client_ip(request: Request) -> str:
    """Caller IP, honouring X-Forwarded-For only when explicitly trusted.

    TRUST_PROXY_HEADERS must stay False unless a reverse proxy in front of this
    app OVERWRITES the header. Turning it on without one lets any client spoof
    its IP and makes every IP-keyed limit here a no-op.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def email_key(email: str) -> str:
    """Hashed so Redis never holds a plaintext user email."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:32]


async def hit(scope: str, key: str, limit: int, window_s: int) -> tuple[bool, int]:
    """Count one request. Returns (allowed, retry_after_seconds)."""
    conn = await _redis()
    if conn is None:
        return True, 0
    now = int(time.time())
    bucket = now // window_s
    redis_key = f"rl:{scope}:{key}:{bucket}"
    try:
        pipe = conn.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_s)
        count = (await pipe.execute())[0]
    except Exception as exc:
        _trip(exc)
        return True, 0
    if int(count) > limit:
        return False, max(1, (bucket + 1) * window_s - now)
    return True, 0


async def reset(scope: str, key: str, window_s: int) -> None:
    """Clear a counter — used to drop the login failure count on success."""
    conn = await _redis()
    if conn is None:
        return
    try:
        await conn.delete(f"rl:{scope}:{key}:{int(time.time()) // window_s}")
    except Exception as exc:
        _trip(exc)
