"""Where a contract's PDF lives: the series bucket in GCS, or a private local directory.

Everything goes through services/file_store, so a GCS outage degrades to local disk rather
than losing the upload. The local root is NOT UPLOAD_DIR — that directory is served as
public static files, and a group contract carries passenger names and sometimes passport
numbers. Same reasoning, and same arrangement, as services/report_download/storage.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.config import settings
from app.services import file_store


def bucket() -> str:
    return settings.GCS_SERIES_BUCKET_NAME or settings.GCS_DEALS_BUCKET_NAME


def local_root() -> Path:
    root = Path(settings.SERIES_DOCS_LOCAL_DIR)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root   # …/backend/<dir>
    return root


def blob_name(tenant_id: int | None, document_id: int, file_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", file_name or "contract.pdf").strip() or "contract.pdf"
    return f"series/{tenant_id or 0}/{document_id}/{safe}"


async def store(content: bytes, *, tenant_id: int | None, document_id: int,
                file_name: str, content_type: str) -> tuple[str, bool]:
    return await file_store.store(
        content, blob_name(tenant_id, document_id, file_name), content_type, bucket(),
        local_root=local_root(),
    )


async def load(locator: str) -> bytes:
    return await file_store.load(locator, bucket(), local_root=local_root())


async def delete(locator: str | None) -> None:
    await file_store.delete(locator, bucket(), local_root=local_root())
