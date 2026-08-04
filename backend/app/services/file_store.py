"""Object storage for uploaded source files, with a local-disk fallback.

GCS stays the primary store, but an outage there — expired credentials, a suspended
or delinquent billing account, no network — must not stop a statement being ingested.
The parse only needs the bytes, and at upload time the bytes are already in hand, so a
failed remote write falls back to the local disk instead of rejecting the upload. The
returned locator records which store actually holds the file:

    "bsp/4/<uuid>/apr.pdf"           → a GCS blob (the shape every existing row uses)
    "local://bsp/4/<uuid>/apr.pdf"   → a file under settings.UPLOAD_DIR

Everything downstream (the Celery parser, preview, download, delete) goes through
``load`` / ``signed_url`` / ``delete`` here and works with either kind, so the fallback
is invisible apart from a warning in the log.

The local root is resolved against the backend package, NOT the process working
directory — the API and the Celery worker are separate processes that need not share
a CWD, and they must agree on where a file landed.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from app.config import settings
from app.services import gcs

logger = logging.getLogger(__name__)

LOCAL_PREFIX = "local://"

# Characters that are illegal in a Windows path (and control characters anywhere).
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')


def _root() -> Path:
    p = Path(settings.UPLOAD_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / p   # …/backend/<UPLOAD_DIR>
    return p


def _sanitize(blob_name: str) -> str:
    """Normalise a blob name to safe, forward-slashed segments.

    Callers build these as f"bsp/{tenant_id}/{batch_id}/{file.filename}" and the filename
    is user-supplied, so `..` and stray separators have to go before the name is ever
    joined onto a local path. Applied to the GCS name too, so both stores agree.
    """
    parts = [p for p in re.split(r"[\\/]+", blob_name or "") if p not in ("", ".", "..")]
    return "/".join(_ILLEGAL.sub("_", p).strip() or "_" for p in parts)


def _local_path(blob_name: str) -> Path:
    root = _root().resolve()
    target = (root / _sanitize(blob_name)).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Refusing to resolve {blob_name!r} outside the upload directory.")
    return target


def is_local(locator: str | None) -> bool:
    return bool(locator) and locator.startswith(LOCAL_PREFIX)


async def store(content: bytes, blob_name: str, content_type: str, bucket_name: str) -> tuple[str, bool]:
    """Persist `content`; returns (locator, stored_remotely). Never raises for a remote
    outage — that's the whole point. Only a local-disk failure propagates."""
    blob_name = _sanitize(blob_name)
    if bucket_name:
        try:
            await gcs.upload_bytes(content, blob_name, content_type, bucket_name)
            return blob_name, True
        except Exception as exc:  # noqa: BLE001 — fall back rather than lose the upload
            logger.warning(
                "[store] GCS unavailable, falling back to local disk | blob=%s | error: %s",
                blob_name, exc,
            )
    else:
        logger.warning("[store] No bucket configured, storing locally | blob=%s", blob_name)

    path = _local_path(blob_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, content)
    logger.info("[store] Stored locally | path=%s | size=%d bytes", path, len(content))
    return LOCAL_PREFIX + blob_name, False


async def load(locator: str, bucket_name: str) -> bytes:
    """Read a stored file back, from wherever `store` put it."""
    if is_local(locator):
        path = _local_path(locator[len(LOCAL_PREFIX):])
        if not path.exists():
            raise FileNotFoundError(f"Stored file is missing from local storage: {path}")
        return await asyncio.to_thread(path.read_bytes)
    return await gcs.download_bytes(locator, bucket_name)


async def delete(locator: str | None, bucket_name: str) -> None:
    """Best-effort delete — a missing file must never block deleting its statement."""
    if not locator:
        return
    if is_local(locator):
        try:
            _local_path(locator[len(LOCAL_PREFIX):]).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[store] Local delete failed (ignored) | %s | %s", locator, exc)
        return
    await gcs.delete_blob(locator, bucket_name)


async def signed_url(
    locator: str,
    bucket_name: str,
    expiry_minutes: int = 60,
    inline: bool = False,
    content_type: str | None = None,
) -> str | None:
    """A directly-openable URL for a GCS blob, or None for a locally-stored file.

    None means "this one has to be streamed by the API" — see the `/file` endpoints,
    which authorise with a short-lived token so a plain window.open still works.
    """
    if is_local(locator):
        return None
    return await gcs.generate_signed_url(
        locator, bucket_name, expiry_minutes=expiry_minutes, inline=inline, content_type=content_type
    )


def file_name(locator: str | None) -> str:
    return (locator or "").rsplit("/", 1)[-1]
